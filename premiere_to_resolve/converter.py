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
    mount = _media_mount(project_path)
    mount_candidates = [mount] if mount is not None else []
    for base in (Path("/run/media") / os.environ.get("USER", ""), Path("/media") / os.environ.get("USER", "")):
        if base.is_dir():
            mount_candidates.extend(child for child in base.iterdir() if child.is_dir())
    mount_candidates.extend(_host_media_mounts())
    mount_candidates = list(dict.fromkeys(mount_candidates))
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


def write_resolve_manifest(
    project_path: Path,
    output_path: Path,
    sequence_index: int,
    on_warning: Callable[[str], None] | None = None,
) -> str:
    """Describe a native Premiere sequence for direct Resolve API assembly."""
    project = _parse_native_project(project_path)
    sequences = list(project.sequences)
    sequence = sequences[sequence_index] if 0 <= sequence_index < len(sequences) else None
    if sequence is None:
        raise ConversionError("Выбранная секвенция больше не найдена в проекте Premiere.")
    if not sequence.timebase:
        raise ConversionError(f"У секвенции «{sequence.name}» не задана частота кадров.")

    mapped, missing, synthetic = _prepare_native_media(project, sequence, project_path)
    frame_rate = Fraction(254016000000, sequence.timebase)
    if frame_rate.denominator == 1:
        frame_rate = Fraction(frame_rate.numerator * 1000, 1001)
    clips: list[dict[str, object]] = []
    media_paths: set[str] = set()
    for media_type, tracks in ((1, sequence.video_tracks), (2, sequence.audio_tracks)):
        for track_index, track in enumerate(tracks, 1):
            for source_clip in track.clips:
                item = source_clip.project_item
                path = item.media_path if item is not None else None
                if item is None or path is None or not _host_file_exists(path):
                    continue
                # Premiere clip in/out values use its media clock. The source
                # stream rate is not currently exposed by all py-premiere
                # versions; Resolve's API expects frame numbers, so preserve
                # the established Premiere-to-sequence conversion here.
                media_rate = sequence.timebase
                clip = {
                    "path": str(path.resolve()),
                    "name": source_clip.name or item.name or path.name,
                    "media_type": media_type,
                    "track_index": track_index,
                    "start_frame": source_clip.in_point.to_frames(media_rate),
                    "end_frame": source_clip.out_point.to_frames(media_rate),
                    "record_frame": source_clip.start.to_frames(sequence.timebase),
                }
                if clip["end_frame"] <= clip["start_frame"]:
                    continue
                clips.append(clip)
                media_paths.add(str(path.resolve()))

    if on_warning:
        if mapped:
            on_warning(f"Пути к медиа сопоставлены с диском проекта: {mapped}.")
        if missing:
            on_warning(f"Не найдено файлов медиа: {missing}; недоступные клипы будут пропущены.")
        if synthetic:
            on_warning(f"Клипы без отдельного медиафайла пропущены: {synthetic}.")
    if not clips:
        raise ConversionError("В выбранной секвенции нет клипов с доступными медиафайлами.")

    payload = {
        "timeline_name": sequence.name or "Premiere timeline",
        "frame_rate": f"{float(frame_rate):.3f}",
        "width": sequence.frame_size[0],
        "height": sequence.frame_size[1],
        "media_paths": sorted(media_paths),
        "clips": clips,
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
