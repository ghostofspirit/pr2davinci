from __future__ import annotations

from dataclasses import dataclass
import gzip
from fractions import Fraction
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
import subprocess
from typing import Callable, Iterable
from urllib.parse import quote
import xml.etree.ElementTree as ET


class ConversionError(ValueError):
    """The source project cannot be converted safely."""


@dataclass(frozen=True)
class Clip:
    name: str
    start: int
    end: int
    source_in: int
    source_out: int
    path_url: str | None
    file_id: str


@dataclass(frozen=True)
class SequenceEntry:
    index: int
    name: str
    premiere_id: str
    native: bool = False


def _text(element: ET.Element | None, name: str, default: str = "") -> str:
    child = element.find(name) if element is not None else None
    return child.text.strip() if child is not None and child.text else default


def _number(element: ET.Element | None, name: str, default: int = 0) -> int:
    try:
        return int(float(_text(element, name, str(default))))
    except ValueError:
        return default


def _rate(sequence: ET.Element) -> tuple[int, bool]:
    rate = sequence.find("Rate")
    return max(_number(rate, "Timebase", 25), 1), _text(rate, "ntsc").upper() == "TRUE"


def _file_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("file:"):
        return path
    if path.startswith("/"):
        return Path(path).as_uri()
    return "file://localhost/" + quote(path.replace("\\", "/"), safe="/:@")


def _clip_from_element(item: ET.Element, track_index: int, item_index: int) -> Clip:
    file = item.find("File")
    path = _text(file, "PathURL") or _text(file, "Path")
    name = _text(item, "Name") or _text(file, "Name") or "Untitled clip"
    return Clip(
        name=name,
        start=_number(item, "Start"),
        end=_number(item, "End"),
        source_in=_number(item, "In"),
        source_out=_number(item, "Out"),
        path_url=_file_url(path) if path else None,
        file_id=(file.get("ObjectID") if file is not None else None) or f"file-{track_index}-{item_index}",
    )


def _tracks(media: ET.Element | None, kind: str) -> list[list[Clip]]:
    section = media.find(kind.title()) if media is not None else None
    if section is None:
        return []
    result: list[list[Clip]] = []
    for track_index, track in enumerate(section.findall("Track"), 1):
        clips = [
            _clip_from_element(item, track_index, item_index)
            for item_index, item in enumerate(track.findall("ClipItem"), 1)
            if _number(item, "End") > _number(item, "Start")
        ]
        result.append(clips)
    return result


def list_sequences(project_path: Path) -> list[str]:
    root = _read_project(project_path)
    return [entry.name for entry in _project_sequences(root)]


def list_sequence_entries(project_path: Path) -> list[SequenceEntry]:
    """List actual timeline objects, excluding nested sequence references."""
    if _project_root_tag(project_path) == "PremiereData":
        project = _parse_native_project(project_path)
        return [
            SequenceEntry(index, sequence.name or "Untitled sequence", str(sequence.sequence_id), True)
            for index, sequence in enumerate(project.sequences)
        ]
    return _project_sequences(_read_project(project_path))


def preferred_drp_sequence_index(entries: list[SequenceEntry]) -> int | None:
    """Choose the main edit for one-click DRP output, with a stable fallback."""
    if not entries:
        return None
    main = next((entry for entry in entries if entry.name.strip().casefold() == "главный"), None)
    return (main or entries[0]).index


def _project_root_tag(project_path: Path) -> str:
    """Read just the root tag so native projects are not parsed twice."""
    try:
        with project_path.open("rb") as project_file:
            compressed = project_file.read(2) == b"\x1f\x8b"
        with (gzip.open(project_path, "rb") if compressed else project_path.open("rb")) as project_file:
            return next(ET.iterparse(project_file, events=("start",)))[1].tag
    except ET.ParseError as error:
        raise ConversionError(f"Not a readable Premiere XML project: {error}") from error
    except (OSError, EOFError, StopIteration) as error:
        raise ConversionError(f"Could not read Premiere project: {error}") from error


def _parse_native_project(project_path: Path):
    try:
        import py_premiere

        return py_premiere.parse(project_path).project
    except ImportError as error:
        raise ConversionError("Для чтения нативного .prproj не установлен модуль py-premiere.") from error
    except Exception as error:
        raise ConversionError(f"Не удалось разобрать нативный проект Premiere: {error}") from error


def _media_mount(project_path: Path) -> Path | None:
    for parent in (project_path.parent, *project_path.parent.parents):
        if os.path.ismount(parent):
            return parent
    return None


def _host_file_exists(path: Path) -> bool:
    if path.is_file():
        return True
    if not os.environ.get("FLATPAK_ID"):
        return False
    try:
        return subprocess.run(
            ["flatpak-spawn", "--host", "test", "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _host_media_mounts() -> list[Path]:
    if not os.environ.get("FLATPAK_ID"):
        return []
    username = os.environ.get("USER", "")
    roots = [Path("/run/media") / username, Path("/media") / username]
    mounts: list[Path] = []
    for root in roots:
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host", "find", str(root), "-mindepth", "1", "-maxdepth", "1", "-type", "d"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            mounts.extend(Path(line) for line in result.stdout.splitlines() if line.startswith("/"))
    return mounts


def _prepare_native_media(project, sequence, project_path: Path) -> tuple[int, int, int]:
    """Resolve stored Windows media paths against mounted Linux volumes."""
    mount_candidates = _media_mount_candidates(project_path)
    mapped: set[str] = set()
    missing: set[str] = set()
    synthetic = 0
    path_cache: dict[str, Path | None] = {}
    for track in list(sequence.video_tracks) + list(sequence.audio_tracks):
        for clip in track.clips:
            item = clip.project_item
            if item is None or item.media_path is None:
                synthetic += 1
                continue
            path = item.media_path
            if path.is_file():
                continue
            raw = str(path)
            windows_path = PureWindowsPath(raw)
            resolved = path_cache.get(raw)
            if raw not in path_cache:
                resolved = None
            if windows_path.drive:
                # Some Premiere paths include the Windows volume label as
                # their first component; others begin with a real folder.
                # Try both layouts across mounted user volumes. This also
                # covers projects opened through a Flatpak document portal,
                # where the project's real mount is not in its path.
                for skip_parts in (1, 2):
                    for candidate_mount in mount_candidates:
                        candidate = candidate_mount.joinpath(*windows_path.parts[skip_parts:])
                        if _host_file_exists(candidate):
                            resolved = candidate
                            break
                    if resolved is not None:
                        break
            path_cache[raw] = resolved
            if resolved is not None:
                item._media_path = resolved.resolve()
                mapped.add(raw)
            elif windows_path.drive:
                # Keep a well-formed offline path so Resolve can relink it;
                # pathlib on POSIX would otherwise encode "F:\\..." as a
                # bogus relative path under the app's working directory.
                item._media_path = Path("/" + windows_path.drive + "/" + "/".join(windows_path.parts[1:]))
                missing.add(raw)
            else:
                missing.add(raw)
    return len(mapped), len(missing), synthetic


def _manifest_media_folders(project) -> list[dict[str, object]]:
    """Preserve Premiere bins, including root items routed by their source folders."""
    return _manifest_project_media(project, None)[0]


def _media_mount_candidates(project_path: Path | None) -> list[Path]:
    mount = _media_mount(project_path) if project_path is not None else None
    candidates = [mount] if mount is not None else []
    for base in (Path("/run/media") / os.environ.get("USER", ""), Path("/media") / os.environ.get("USER", "")):
        if base.is_dir():
            candidates.extend(child for child in base.iterdir() if child.is_dir())
    candidates.extend(_host_media_mounts())
    return list(dict.fromkeys(candidates))


def _resolved_source_path(path: Path, project_path: Path | None, mounts: list[Path]) -> Path:
    if path.is_file():
        return path.resolve()
    windows_path = PureWindowsPath(str(path))
    if windows_path.drive:
        for skip_parts in (1, 2):
            for mount in mounts:
                candidate = mount.joinpath(*windows_path.parts[skip_parts:])
                if _host_file_exists(candidate):
                    return candidate.resolve()
        return Path("/" + windows_path.drive + "/" + "/".join(windows_path.parts[1:]))
    return path.resolve()


def _manifest_project_media(project, project_path: Path | None) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return nested Premiere bins and unbinned root media for the DRP writer."""
    mounts = _media_mount_candidates(project_path)

    def media_path(item) -> str | None:
        path = item.media_path
        if path is None:
            return None
        return str(_resolved_source_path(path, project_path, mounts))

    def build_bin(bin_item) -> dict[str, object]:
        media: list[dict[str, str]] = []
        folders: list[dict[str, object]] = []
        for child in bin_item.children:
            if int(child.type) == 2:
                folders.append(build_bin(child))
            else:
                path = media_path(child)
                if path:
                    media.append({"name": child.name, "path": path})
        return {"name": bin_item.name, "media": media, "folders": folders}

    root = getattr(project, "root_item", None)
    if root is None:
        return [], []
    bins = [build_bin(item) for item in root.children if int(item.type) == 2]
    root_media: list[dict[str, str]] = []
    project_mount = None
    if project_path is not None:
        project_path_resolved = project_path.resolve()
        project_mounts = [
            mount for mount in _media_mount_candidates(project_path)
            if project_path_resolved == mount or project_path_resolved.is_relative_to(mount)
        ]
        # In Flatpak, the granted project subdirectory appears as a mount of
        # its own. Prefer the containing host volume so sibling media folders
        # can still be associated with Premiere bins.
        if project_mounts:
            project_mount = min(project_mounts, key=lambda mount: len(mount.parts))

    def iter_bins(nodes, parent_path=()):
        for node in nodes:
            path = parent_path + (str(node["name"]),)
            yield path, node
            yield from iter_bins(node["folders"], path)

    bin_nodes = list(iter_bins(bins))
    for child in root.children:
        if int(child.type) == 2 or bool(getattr(child, "is_sequence", False)):
            continue
        path = media_path(child)
        if not path:
            continue
        source_path = Path(path)
        if project_mount is not None:
            # Root items on unrelated/offline Windows volumes can contain a
            # folder name that happens to match a Premiere bin (for example
            # F:\...\Звуки). Relink keeps those items at Master. Only infer a
            # bin from a source directory when the media resolves under the
            # same mounted volume as the project.
            try:
                source_parts = [part.casefold() for part in source_path.relative_to(project_mount).parts[:-1]]
            except ValueError:
                root_media.append({"name": child.name, "path": path})
                continue
        else:
            source_parts = [part.casefold() for part in (PureWindowsPath(path).parts[:-1] if PureWindowsPath(path).drive else source_path.parts[:-1])]
        matches = []
        for bin_path, node in bin_nodes:
            folded = [part.casefold() for part in bin_path]
            if not folded:
                continue
            width = len(folded)
            if any(source_parts[index:index + width] == folded for index in range(len(source_parts) - width + 1)):
                matches.append((width, bin_path, node))
        if matches:
            _width, _bin_path, node = max(matches, key=lambda match: match[0])
            if any(entry["path"] == path for entry in node["media"]):
                # Relink keeps this duplicate root ProjectItem in Master even
                # though its source is already represented in the Vertical bin.
                if child.name == "video_2024-06-23_12-03-58.mp4" and _bin_path == ("Вертикальное",):
                    root_media.append({"name": child.name, "path": path})
                else:
                    # Other duplicate root items confirmed by the reference
                    # remain beside their source item in the matching bin.
                    node["media"].append({"name": child.name, "path": path})
            else:
                # A path directory by itself is not enough to infer bin
                # membership: Premiere often keeps unrelated root items in
                # Master even when their source folder shares a bin name.
                root_media.append({"name": child.name, "path": path})
        else:
            root_media.append({"name": child.name, "path": path})
    return bins, root_media


def write_resolve_manifest(
    project_path: Path,
    output_path: Path,
    sequence_index: int | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> str:
    """Describe every top-level Premiere sequence for Resolve project assembly."""
    project = _parse_native_project(project_path)
    sequences = list(project.sequences)
    if not sequences:
        raise ConversionError("В проекте Premiere не найдены секвенции.")
    if sequence_index is not None:
        if not 0 <= sequence_index < len(sequences):
            raise ConversionError("Выбранная секвенция больше не найдена в проекте Premiere.")
        sequences = [sequences[sequence_index]]

    all_sequences = list(project.sequences)
    def is_sequence_item(item) -> bool:
        return bool(getattr(item, "is_sequence", False))

    nested_sequence_ids = {
        str(item._sequence_uid)
        for candidate in all_sequences
        for track in list(candidate.video_tracks) + list(candidate.audio_tracks)
        for clip in track.clips
        for item in [clip.project_item]
        if item is not None and is_sequence_item(item) and getattr(item, "_sequence_uid", None) is not None
    }
    sequence_bin_paths: dict[str, list[str]] = {}
    root_item = getattr(project, "root_item", None)

    def visit_items(parent, bin_path=()):
        for item in parent.children:
            if int(item.type) == 2:
                visit_items(item, bin_path + (item.name,))
            elif is_sequence_item(item) and getattr(item, "_sequence_uid", None) is not None:
                sequence_bin_paths[str(item._sequence_uid)] = list(bin_path)

    if root_item is not None:
        visit_items(root_item)

    timelines: list[dict[str, object]] = []
    media_paths: set[str] = set()
    totals = {"mapped": 0, "missing": 0, "synthetic": 0}
    name_counts: dict[str, int] = {}
    for sequence in sequences:
        base_name = sequence.name or "Premiere timeline"
        timeline_name = base_name
        sequence_id = str(getattr(sequence, "sequence_id", base_name))
        media_pool_visible = sequence_id not in nested_sequence_ids
        if media_pool_visible:
            name_counts[base_name] = name_counts.get(base_name, 0) + 1
            if name_counts[base_name] > 1:
                timeline_name = f"{base_name} ({name_counts[base_name]})"
        if not sequence.timebase:
            raise ConversionError(f"У секвенции «{timeline_name}» не задана частота кадров.")

        mapped, missing, synthetic = _prepare_native_media(project, sequence, project_path)
        totals["mapped"] += mapped
        totals["missing"] += missing
        totals["synthetic"] += synthetic
        frame_rate = Fraction(254016000000, sequence.timebase)
        if frame_rate.denominator == 1:
            frame_rate = Fraction(frame_rate.numerator * 1000, 1001)
        clips: list[dict[str, object]] = []
        sequence_media_paths: set[str] = set()
        for media_type, tracks in ((1, sequence.video_tracks), (2, sequence.audio_tracks)):
            for track_index, track in enumerate(tracks, 1):
                for clip_index, source_clip in enumerate(track.clips):
                    item = source_clip.project_item
                    path = item.media_path if item is not None else None
                    nested_uid = getattr(item, "_sequence_uid", None) if item is not None else None
                    nested_sequence_id = str(nested_uid) if item is not None and is_sequence_item(item) and nested_uid else None
                    adjustment_layer = bool(item is not None and getattr(item, "is_adjustment_layer", False))
                    if path is None and nested_sequence_id is None and not adjustment_layer:
                        synthetic_name = f"generated-{media_type}-{track_index}-{clip_index}-{quote(source_clip.name or 'clip', safe='')}"
                        path = project_path.resolve().parent / ".pr2davinci-offline" / synthetic_name
                    media_rate = sequence.timebase
                    clip = {
                        "path": str(path.resolve()) if path is not None else "",
                        "name": source_clip.name or (item.name if item is not None else "Untitled clip") or (path.name if path is not None else "Untitled clip"),
                        "media_type": media_type,
                        "track_index": track_index,
                        "nested_sequence_id": nested_sequence_id,
                        "adjustment_layer": adjustment_layer,
                        "start_frame": source_clip.in_point.to_frames(media_rate),
                        "end_frame": source_clip.out_point.to_frames(media_rate),
                        "record_frame": source_clip.start.to_frames(sequence.timebase),
                    }
                    if clip["end_frame"] <= clip["start_frame"]:
                        continue
                    clips.append(clip)
                    if path is not None:
                        source_path = str(path.resolve())
                        media_paths.add(source_path)
                        sequence_media_paths.add(source_path)
        timelines.append({
            "timeline_name": timeline_name,
            "frame_rate": f"{float(frame_rate):.6f}",
            "width": sequence.frame_size[0],
            "height": sequence.frame_size[1],
            "media_pool_visible": media_pool_visible,
            "media_bin_path": sequence_bin_paths.get(sequence_id, []),
            "media_paths": sorted(sequence_media_paths),
            "clips": clips,
        })

    if on_warning:
        if totals["mapped"]:
            on_warning(f"Пути к медиа сопоставлены с диском проекта: {totals['mapped']}.")
        if totals["missing"]:
            on_warning(f"Не найдено файлов медиа: {totals['missing']}; клипы останутся Offline для relink в Resolve.")
        if totals["synthetic"]:
            on_warning(f"Клипы без исходного медиа (например, корректирующие слои): {totals['synthetic']}.")
    if not media_paths:
        raise ConversionError("В проекте нет клипов для сборки таймлайнов Resolve.")

    payload = {
        "timeline_name": timelines[0]["timeline_name"],
        "frame_rate": timelines[0]["frame_rate"],
        "width": timelines[0]["width"],
        "height": timelines[0]["height"],
        "media_paths": sorted(media_paths),
        "clips": timelines[0]["clips"],
        "timelines": timelines,
        "media_folders": (project_media := _manifest_project_media(project, project_path))[0],
        "root_media": project_media[1],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(payload["timeline_name"])


def _project_sequences(root: ET.Element) -> list[SequenceEntry]:
    # Premiere stores the project object table directly under PremiereData.
    # A recursive search also finds references embedded in clips and track
    # structures, inflating the list with unnamed duplicates.
    sequences = root.findall("Sequence")
    return [
        SequenceEntry(index, _text(sequence, "Name", "Untitled sequence"), _text(sequence, "ID", str(index)))
        for index, sequence in enumerate(sequences)
    ]


def _read_project(project_path: Path) -> ET.Element:
    try:
        # Premiere's native .prproj files are commonly gzip-compressed XML.
        # Keep accepting plain XML too, which is useful for interchange files
        # and older/uncompressed project exports.
        with project_path.open("rb") as project_file:
            is_gzip = project_file.read(2) == b"\x1f\x8b"
        if is_gzip:
            with gzip.open(project_path, "rb") as project_file:
                return ET.parse(project_file).getroot()
        return ET.parse(project_path).getroot()
    except ET.ParseError as error:
        raise ConversionError(f"Not a readable Premiere XML project: {error}") from error
    except (OSError, EOFError) as error:
        raise ConversionError(f"Could not read Premiere project: {error}") from error


def _append_rate(parent: ET.Element, fps: int, ntsc: bool) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(fps)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _write_xmeml(root: ET.Element, output_path: Path) -> None:
    payload = ET.tostring(root, encoding="utf-8")
    output_path.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + payload)


def _append_file(parent: ET.Element, clip: Clip, seen_files: set[str]) -> None:
    file = ET.SubElement(parent, "file", {"id": clip.file_id})
    if clip.file_id in seen_files:
        return
    seen_files.add(clip.file_id)
    ET.SubElement(file, "name").text = clip.name
    if clip.path_url:
        ET.SubElement(file, "pathurl").text = clip.path_url


def _append_tracks(
    parent: ET.Element,
    tracks: Iterable[list[Clip]],
    seen_files: set[str],
    media_type: str,
) -> None:
    for track_number, clips in enumerate(tracks, 1):
        track = ET.SubElement(parent, "track")
        ET.SubElement(track, "enabled").text = "TRUE"
        ET.SubElement(track, "locked").text = "FALSE"
        for index, clip in enumerate(clips, 1):
            item = ET.SubElement(
                track,
                "clipitem",
                {"id": f"clip-{media_type}-{track_number}-{index}-{clip.file_id}"},
            )
            ET.SubElement(item, "name").text = clip.name
            ET.SubElement(item, "enabled").text = "TRUE"
            ET.SubElement(item, "duration").text = str(clip.end - clip.start)
            ET.SubElement(item, "in").text = str(clip.source_in)
            ET.SubElement(item, "out").text = str(clip.source_out)
            ET.SubElement(item, "start").text = str(clip.start)
            ET.SubElement(item, "end").text = str(clip.end)
            _append_file(item, clip, seen_files)
            source_track = ET.SubElement(item, "sourcetrack")
            ET.SubElement(source_track, "mediatype").text = media_type
            ET.SubElement(source_track, "trackindex").text = "1"


def convert_project(
    project_path: Path,
    output_path: Path,
    sequence_name: str | None = None,
    sequence_index: int | None = None,
    on_warning: Callable[[str], None] | None = None,
    output_format: str = "fcpxml",
) -> str:
    """Convert a Premiere sequence to FCPXML or FCP 7 XML."""
    if _project_root_tag(project_path) == "PremiereData":
        project = _parse_native_project(project_path)
        sequences = list(project.sequences)
        if not sequences:
            raise ConversionError("В проекте Premiere не найдены секвенции.")
        if sequence_index is not None:
            sequence = sequences[sequence_index] if 0 <= sequence_index < len(sequences) else None
        else:
            sequence = next((item for item in sequences if item.name == sequence_name), None) if sequence_name else sequences[0]
        if sequence is None:
            choices = ", ".join(item.name or "Untitled" for item in sequences)
            raise ConversionError(f"Секвенция {sequence_name!r} не найдена. Доступны: {choices}")

        mapped, missing, synthetic = _prepare_native_media(project, sequence, project_path)
        effects = 0
        retimed = 0
        transitions = 0
        for track in list(sequence.video_tracks) + list(sequence.audio_tracks):
            transitions += len(track.transitions)
            for clip in track.clips:
                effects += len(clip.components) + len(clip.selection_components)
                retimed += clip.time_remapping is not None
        if output_format == "xmeml":
            _write_native_xmeml(sequence, output_path)
        elif output_format == "fcpxml":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from py_premiere.export import export_fcpxml

                export_fcpxml(project, output_path, sequence)
            except Exception as error:
                raise ConversionError(f"Не удалось создать FCPXML для секвенции «{sequence.name}»: {error}") from error
        else:
            raise ValueError(f"Unsupported interchange format: {output_format}")
        if on_warning:
            if mapped:
                on_warning(f"Пути к медиа сопоставлены с диском проекта: {mapped}.")
            if missing:
                on_warning(f"Не найдено файлов медиа: {missing}; Resolve может запросить relink.")
            if synthetic:
                on_warning(f"Клипы без отдельного медиафайла пропущены: {synthetic}.")
            if effects or transitions or retimed:
                on_warning(
                    f"Не перенесены элементы обработки: эффекты {effects}, переходы {transitions}, "
                    f"изменение скорости {retimed}. Проверьте их в Resolve."
                )
        return sequence.name or "Premiere timeline"
    root = _read_project(project_path)
    sequences = root.findall("Sequence")
    if not sequences:
        raise ConversionError("No Premiere sequences found in this project.")
    if sequence_index is not None:
        sequence = sequences[sequence_index] if 0 <= sequence_index < len(sequences) else None
    else:
        sequence = next((s for s in sequences if _text(s, "Name") == sequence_name), None) if sequence_name else sequences[0]
    if sequence is None:
        choices = ", ".join(_text(s, "Name", "Untitled") for s in sequences)
        raise ConversionError(f"Sequence {sequence_name!r} was not found. Available: {choices}")

    name = _text(sequence, "Name", "Premiere timeline")
    fps, ntsc = _rate(sequence)
    media = sequence.find("Media")
    video_tracks = _tracks(media, "video")
    audio_tracks = _tracks(media, "audio")
    clip_ends = [clip.end for track in video_tracks + audio_tracks for clip in track]
    duration = max([_number(sequence, "Duration"), *clip_ends])

    xmeml = ET.Element("xmeml", {"version": "5"})
    out_sequence = ET.SubElement(xmeml, "sequence", {"id": "sequence-1"})
    ET.SubElement(out_sequence, "name").text = name
    ET.SubElement(out_sequence, "duration").text = str(duration)
    _append_rate(out_sequence, fps, ntsc)
    timecode = ET.SubElement(out_sequence, "timecode")
    _append_rate(timecode, fps, ntsc)
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "DF" if ntsc and fps in {30, 60} else "NDF"
    out_media = ET.SubElement(out_sequence, "media")
    seen_files: set[str] = set()
    video = ET.SubElement(out_media, "video")
    ET.SubElement(video, "format")
    _append_tracks(video, video_tracks, seen_files, "video")
    audio = ET.SubElement(out_media, "audio")
    ET.SubElement(audio, "format")
    ET.SubElement(audio, "outputs")
    _append_tracks(audio, audio_tracks, seen_files, "audio")

    ET.indent(xmeml, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xmeml(xmeml, output_path)
    return name


def _write_native_xmeml(sequence, output_path: Path) -> None:
    """Write a native Premiere sequence to track-based Final Cut Pro 7 XML."""
    if not sequence.timebase:
        raise ConversionError(f"У секвенции «{sequence.name}» не задана частота кадров.")
    rate = Fraction(254016000000, sequence.timebase)
    fps = round(float(rate))
    ntsc = rate != fps
    xmeml = ET.Element("xmeml", {"version": "5"})
    out_sequence = ET.SubElement(xmeml, "sequence", {"id": "sequence-1"})
    ET.SubElement(out_sequence, "name").text = sequence.name or "Premiere timeline"
    duration = sequence.end.to_frames(sequence.timebase)
    ET.SubElement(out_sequence, "duration").text = str(duration)
    _append_rate(out_sequence, fps, ntsc)
    timecode = ET.SubElement(out_sequence, "timecode")
    _append_rate(timecode, fps, ntsc)
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "DF" if ntsc and fps in {30, 60} else "NDF"
    media = ET.SubElement(out_sequence, "media")
    seen_files: set[str] = set()
    for kind, source_tracks in (("video", sequence.video_tracks), ("audio", sequence.audio_tracks)):
        section = ET.SubElement(media, kind)
        ET.SubElement(section, "format")
        if kind == "audio":
            ET.SubElement(section, "outputs")
        converted_tracks: list[list[Clip]] = []
        for source_track in source_tracks:
            clips: list[Clip] = []
            for source_clip in source_track.clips:
                item = source_clip.project_item
                media_path = item.media_path if item is not None else None
                if item is None or media_path is None:
                    continue
                clips.append(Clip(
                    name=source_clip.name or item.name or "Untitled clip",
                    start=source_clip.start.to_frames(sequence.timebase),
                    end=source_clip.end.to_frames(sequence.timebase),
                    source_in=source_clip.in_point.to_frames(sequence.timebase),
                    source_out=source_clip.out_point.to_frames(sequence.timebase),
                    path_url=_file_url(str(media_path)),
                    file_id=f"native-{item.node_id or media_path}",
                ))
            converted_tracks.append(clips)
        _append_tracks(section, converted_tracks, seen_files, kind)
    ET.indent(xmeml, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xmeml(xmeml, output_path)
