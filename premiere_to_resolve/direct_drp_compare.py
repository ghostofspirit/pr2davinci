"""Headless direct-DRP comparison tools; this module never imports Resolve."""

from __future__ import annotations

import json
from html import unescape
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from .converter import list_sequence_entries, write_resolve_manifest
from .direct_drp import create_drp_from_manifest
from .drp_archive import DrpArchiveError, inspect_drp_archive


class DirectDrpComparisonError(RuntimeError):
    """The requested project or reference archive cannot be compared."""


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_MEDIA = re.compile(rb"<Sm2Mp(?:Video|Audio)Clip\b")


def _folder_info(xml: bytes) -> tuple[str, str, str, int]:
    text = xml.decode("utf-8")
    root = re.search(r'<Sm2MpFolder\b[^>]*\bDbId="([^"]+)"', text)
    name = re.search(r"<Name>([\s\S]*?)</Name>", text)
    parent = re.search(r"<MpFolder>([^<]*)</MpFolder>", text)
    if not root or not name:
        raise DirectDrpComparisonError("Invalid Media Pool folder XML.")
    return root.group(1), unescape(name.group(1)), parent.group(1) if parent else "", len(_MEDIA.findall(xml))


def _archive_structure(path: Path) -> dict[str, object]:
    try:
        inspection = inspect_drp_archive(path)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            folder_paths = sorted(
                name for name in names
                if name == "MediaPool/Master/MpFolder.xml"
                or (name.startswith("MediaPool/") and name.endswith("/MpFolder.xml"))
            )
            folders: dict[str, tuple[str, str, str, int]] = {
                name: _folder_info(archive.read(name)) for name in folder_paths
            }
            ids = {folder_id: (path_name, name, count) for path_name, (folder_id, name, _parent, count) in folders.items()}
            bin_rows = []
            for path_name, (folder_id, name, parent_id, count) in folders.items():
                parts = [name]
                visited = {folder_id}
                while parent_id in ids and parent_id not in visited:
                    visited.add(parent_id)
                    _parent_path, parent_name, _parent_count = ids[parent_id]
                    if parent_name != "Master":
                        parts.append(parent_name)
                    parent_bytes = archive.read(_parent_path)
                    parent_match = re.search(rb"<MpFolder>([^<]*)</MpFolder>", parent_bytes)
                    parent_id = parent_match.group(1).decode() if parent_match else ""
                parts.reverse()
                bin_rows.append({"path": "/".join(parts), "media_items": count})

            sequence_files = {
                Path(name).stem: name for name in names
                if name.startswith("SeqContainer/") and name.endswith(".xml")
            }
            container_clips: dict[str, tuple[int, int]] = {}
            for sequence_id, sequence_path in sequence_files.items():
                root = ET.fromstring(archive.read(sequence_path))
                container_clips[sequence_id] = (
                    sum(1 for _ in root.iter("Sm2TiVideoClip")),
                    sum(1 for _ in root.iter("Sm2TiAudioClip")),
                )
            timelines = []
            referenced_ids: list[str] = []
            # Resolve stores timeline items in whichever Media Pool bin owns
            # them, so inspect every folder XML rather than Master alone.
            for folder_path in folder_paths:
                folder_xml = archive.read(folder_path).decode("utf-8")
                for block in re.findall(r"<Sm2MpTimelineClip\b[\s\S]*?</Sm2MpTimelineClip>", folder_xml):
                    name_match = re.search(r"<Name>([\s\S]*?)</Name>", block)
                    blob_match = re.search(r"<Sm2Sequence\b[\s\S]*?<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", block)
                    if not name_match or not blob_match:
                        continue
                    decoded = bytes.fromhex(blob_match.group(1)).decode("utf-16le", errors="ignore")
                    # SeqRef stores an H prefix immediately before the container UUID.
                    ref_match = re.search(r"H(" + _UUID.pattern + r")", decoded)
                    seq_id = ref_match.group(1) if ref_match else ""
                    if seq_id:
                        referenced_ids.append(seq_id)
                    linked = seq_id in sequence_files
                    video_clips, audio_clips = container_clips.get(seq_id, (None, None)) if linked else (None, None)
                    timelines.append({
                        "name": unescape(name_match.group(1)),
                        "sequence_container_linked": linked,
                        "video_clips": video_clips,
                        "audio_clips": audio_clips,
                    })
            timelines.sort(key=lambda row: (row["name"], row["sequence_container_linked"], str(row["video_clips"]), str(row["audio_clips"])))
            reused_refs = len(referenced_ids) - len(set(referenced_ids))
            category_counts = {
                "project_xml": sum(name == "project.xml" for name in names),
                "sequence_containers": sum(name.startswith("SeqContainer/") and name.endswith(".xml") for name in names),
                "media_pool_folders": len(folder_paths),
                "other_entries": sum(
                    name != "project.xml"
                    and not (name.startswith("SeqContainer/") and name.endswith(".xml"))
                    and name not in folder_paths
                    for name in names
                ),
            }
        return {
            "archive_entries": len(names),
            "archive_categories": category_counts,
            "timelines": timelines,
            "sequence_links": {
                "media_pool_timeline_count": len(timelines),
                "broken_timeline_references": sum(not row["sequence_container_linked"] for row in timelines),
                "unreferenced_sequence_containers": len(set(sequence_files) - set(referenced_ids)),
                "reused_sequence_references": reused_refs,
            },
            "media_bins": sorted(bin_rows, key=lambda row: row["path"]),
            "totals": {
                "timeline_count": inspection.timeline_count,
                "video_clips": inspection.video_clip_count,
                "audio_clips": inspection.audio_clip_count,
                "media_items": inspection.media_item_count,
                "unresolved_media_references": inspection.unresolved_media_references,
            },
        }
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, ET.ParseError, DrpArchiveError) as error:
        raise DirectDrpComparisonError(f"Could not inspect {path.name}: {error}") from error


def compare_drp_archives(reference_path: Path, generated_path: Path) -> dict[str, object]:
    """Return a deterministic, ID-independent structural comparison."""
    reference = _archive_structure(reference_path)
    generated = _archive_structure(generated_path)
    def indexed_timelines(rows):
        counts: dict[str, int] = {}
        result = {}
        for row in rows:
            name = row["name"] or "(unlinked)"
            counts[name] = counts.get(name, 0) + 1
            result[(name, counts[name])] = {**row, "name": name}
        return result

    reference_timeline_map = indexed_timelines(reference["timelines"])
    generated_timeline_map = indexed_timelines(generated["timelines"])
    all_names = sorted(set(reference_timeline_map) | set(generated_timeline_map))
    timeline_differences = []
    for name, occurrence in all_names:
        ref = reference_timeline_map.get((name, occurrence))
        out = generated_timeline_map.get((name, occurrence))
        timeline_differences.append({
            "name": name,
            "occurrence": occurrence,
            "status": "same" if ref and out and ref == out else "missing" if ref and not out else "extra" if out and not ref else "different",
            "reference": ref,
            "generated": out,
        })
    ref_bins = {row["path"]: row for row in reference["media_bins"]}
    out_bins = {row["path"]: row for row in generated["media_bins"]}
    return {
        "report_version": 1,
        "comparison": "direct_drp_structure",
        "reference": reference,
        "generated": generated,
        "differences": {
            "archive_entry_count_difference": generated["archive_entries"] - reference["archive_entries"],
            "total_count_differences": {
                key: generated["totals"][key] - reference["totals"][key]
                for key in reference["totals"]
                if generated["totals"][key] != reference["totals"][key]
            },
            "timeline_differences": timeline_differences,
            "media_bins_missing_from_generated": sorted(set(ref_bins) - set(out_bins)),
            "media_bins_extra_in_generated": sorted(set(out_bins) - set(ref_bins)),
            "media_bin_item_count_differences": [
                {"path": name, "reference": ref_bins[name]["media_items"], "generated": out_bins[name]["media_items"]}
                for name in sorted(set(ref_bins) & set(out_bins))
                if ref_bins[name]["media_items"] != out_bins[name]["media_items"]
            ],
            "archive_category_count_differences": {
                key: generated["archive_categories"][key] - reference["archive_categories"][key]
                for key in reference["archive_categories"]
                if generated["archive_categories"][key] != reference["archive_categories"][key]
            },
        },
    }


def compare_prproj_to_reference(prproj_path: Path, reference_path: Path) -> dict[str, object]:
    """Generate a temporary direct DRP and compare it without Resolve or its API."""
    prproj_path, reference_path = prproj_path.expanduser(), reference_path.expanduser()
    if not prproj_path.is_file():
        raise DirectDrpComparisonError(f"Premiere project not found: {prproj_path}")
    if not reference_path.is_file():
        raise DirectDrpComparisonError(f"Reference DRP not found: {reference_path}")
    try:
        # Direct DRP comparison models a whole-project handoff like Relink:
        # include every top-level Premiere sequence, not only the GUI's
        # one-click preview/default sequence.
        entries = list_sequence_entries(prproj_path)
        if not entries:
            raise DirectDrpComparisonError("В проекте Premiere не найдены секвенции.")
        with tempfile.TemporaryDirectory(prefix="pr2davinci-compare-") as temp_dir:
            temp_dir = Path(temp_dir)
            manifest_path = temp_dir / "manifest.json"
            generated_path = temp_dir / "generated.drp"
            write_resolve_manifest(prproj_path, manifest_path, sequence_index=None)
            create_drp_from_manifest(manifest_path, generated_path)
            report = compare_drp_archives(reference_path, generated_path)
        report["inputs"] = {
            "premiere_project": prproj_path.name,
            "reference_drp": reference_path.name,
        }
        report["runtime_validation"] = "not_performed; Resolve and its API were not launched"
        return report
    except DirectDrpComparisonError:
        raise
    except Exception as error:
        raise DirectDrpComparisonError(str(error)) from error


def write_report_new(path: Path, report: dict[str, object]) -> Path:
    """Write stable JSON once; refuse to replace any existing user file."""
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
