"""Build a Resolve project archive directly from a Premiere timeline manifest.

The archive layout and the small XML surgery helpers here follow the MIT-licensed
``drp-format`` project by DaVinci Resolve MCP Contributors. We intentionally start
from its Resolve-authored media/timeline template instead of inventing the opaque
Resolve object schema.
"""

from __future__ import annotations

import json
import re
import struct
import uuid
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

import zstandard

from .drp_archive import DrpArchiveError, inspect_drp_archive
from .offline_media import _replace_length_delimited


class DirectDrpError(RuntimeError):
    """A source timeline could not safely be authored as a DRP archive."""


_UUID = r"[0-9a-fA-F-]{36}"
_EMPTY_BIN_FIELDS = "0000000200000027800a0610ccf7dfac0d18ccf7dfac0d20ccf7dfac0d5a100a0c3030303030302030303030301200"


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise DirectDrpError("Повреждён protobuf-медиадескриптор Resolve.")


def _resolve_media_path(blob: bytes) -> str:
    if len(blob) < 10 or blob[8] != 0x81:
        raise DirectDrpError("Неизвестный формат сжатого медиадескриптора Resolve.")
    try:
        payload = zstandard.ZstdDecompressor().decompress(blob[9:])
    except zstandard.ZstdError as error:
        raise DirectDrpError("Не удалось распаковать медиадескриптор Resolve.") from error
    fields: dict[int, bytes] = {}
    offset = 0
    while offset < len(payload):
        key, offset = _varint(payload, offset)
        wire_type, field_number = key & 7, key >> 3
        if wire_type == 2:
            length, offset = _varint(payload, offset)
            value = payload[offset:offset + length]
            offset += length
            if field_number in (1, 2):
                fields[field_number] = value
        elif wire_type == 0:
            _, offset = _varint(payload, offset)
        elif wire_type == 1:
            offset += 8
        elif wire_type == 5:
            offset += 4
        else:
            raise DirectDrpError("В медиадескрипторе Resolve встретился неизвестный protobuf-тип.")
        if offset > len(payload):
            raise DirectDrpError("Обрезан медиадескриптор Resolve.")
    if 1 not in fields or 2 not in fields:
        raise DirectDrpError("В медиадескрипторе Resolve нет пути к исходному файлу.")
    directory, filename = fields[1].decode("utf-8"), fields[2].decode("utf-8")
    return str(Path(directory) / filename)


def _element(xml: str, tag: str) -> str:
    match = re.search(fr"<{tag}\b[^>]*>[\s\S]*?</{tag}>", xml)
    if not match:
        raise DirectDrpError(f"В шаблоне Resolve не найден элемент {tag}.")
    return match.group(0)


def _uuid_attr(xml: str, tag: str) -> str:
    match = re.search(fr"<{tag}\b[^>]*\bDbId=\"({_UUID})\"", xml)
    if not match:
        raise DirectDrpError(f"В шаблоне Resolve не найден идентификатор {tag}.")
    return match.group(1)


def _fresh_ids(xml: str, *, sequence_id: str | None = None) -> tuple[str, str]:
    """Give one cloned object graph new Resolve IDs without touching opaque blobs."""
    blobs: list[str] = []

    def hide_blob(match: re.Match[str]) -> str:
        blobs.append(match.group(0))
        return f"__PR2DAVINCI_BLOB_{len(blobs) - 1}__"

    protected = re.sub(r"<FieldsBlob>[^<]*</FieldsBlob>", hide_blob, xml)
    mapping = {value: str(uuid.uuid4()) for value in re.findall(fr'\bDbId="({_UUID})"', protected)}
    old_sequence = re.search(fr"<UniqueSequenceId>({_UUID})</UniqueSequenceId>", protected)
    if old_sequence:
        mapping[old_sequence.group(1)] = sequence_id or str(uuid.uuid4())
    for old, new in mapping.items():
        protected = protected.replace(old, new)
    protected = re.sub(
        r"<UniqueMediaPoolItemId>[^<]*</UniqueMediaPoolItemId>",
        lambda _m: f"<UniqueMediaPoolItemId>{uuid.uuid4()}</UniqueMediaPoolItemId>",
        protected,
    )
    for index, blob in enumerate(blobs):
        protected = protected.replace(f"__PR2DAVINCI_BLOB_{index}__", blob)
    root_id = next(iter(mapping.values()), "")
    return protected, root_id


def _set_first(xml: str, tag: str, value: str) -> str:
    escaped = escape(value)
    pattern = re.compile(fr"<{tag}>([\s\S]*?)</{tag}>")
    result, count = pattern.subn(f"<{tag}>{escaped}</{tag}>", xml, count=1)
    if not count:
        raise DirectDrpError(f"В шаблоне Resolve не найдено поле {tag}.")
    return result


def _set_object_name(xml: str, object_tag: str, value: str) -> str:
    pattern = re.compile(
        fr"(<{object_tag}\b[^>]*>[\s\S]*?<FieldsBlob>[^<]*</FieldsBlob>[\s\S]*?<Name>)[\s\S]*?(</Name>)"
    )
    result, count = pattern.subn(lambda m: f"{m.group(1)}{escape(value)}{m.group(2)}", xml, count=1)
    if not count:
        raise DirectDrpError(f"В объекте {object_tag} не найдено поле имени.")
    return result


def _encode_rate(rate: float) -> str:
    return (struct.pack("<d", rate) + bytes(8)).hex()


def _encode_resolution(width: int, height: int) -> str:
    return struct.pack(">IIII", 0, width, 0, height).hex()


def _patch_media_path(
    media_xml: str, old_path: str, new_path: str, name: str, parent_folder_id: str
) -> str:
    """Retarget the template's text and compressed Resolve media descriptor."""
    old_escaped, new_escaped = escape(old_path), escape(new_path)
    # Resolve keeps the Media Pool path only in the compressed BtVideoInfo Clip
    # blob; some exports also expose it as a plain MediaFilePath field.
    media_xml = media_xml.replace(old_escaped, new_escaped)
    media_xml = _set_object_name(media_xml, "Sm2MpVideoClip", name)
    media_xml = re.sub(
        r"<MpFolder>[^<]*</MpFolder>",
        f"<MpFolder>{parent_folder_id}</MpFolder>",
        media_xml,
        count=1,
    )

    changed = 0

    def repoint_resolve_clip(blob: bytes) -> tuple[bytes, bool]:
        # Resolve wraps a zstd-compressed protobuf in an eight-byte version/size
        # header and a one-byte frame marker. The path is in protobuf fields 1/2.
        if len(blob) < 10 or blob[8] != 0x81:
            return blob, False
        try:
            payload = zstandard.ZstdDecompressor().decompress(blob[9:])
        except zstandard.ZstdError:
            return blob, False
        updated = payload
        from_dir, from_name = Path(old_path).parent.as_posix().encode(), Path(old_path).name.encode()
        to_dir, to_name = Path(new_path).parent.as_posix().encode(), Path(new_path).name.encode()
        did_change = False
        for old, new in ((from_dir, to_dir), (from_name, to_name)):
            if old and old != new:
                updated, replaced = _replace_length_delimited(updated, old, new)
                did_change = did_change or replaced
        if not did_change:
            return blob, False
        frame = b"\x81" + zstandard.ZstdCompressor(level=3).compress(updated)
        return blob[:4] + len(frame).to_bytes(4, "big") + frame, True

    def replace_blob(match: re.Match[str]) -> str:
        nonlocal changed
        blob, did_change = repoint_resolve_clip(bytes.fromhex(match.group(1)))
        if did_change:
            changed += 1
            return f"<Clip>{blob.hex()}</Clip>"
        return match.group(0)

    media_xml = re.sub(r"<Clip>([0-9a-fA-F]+)</Clip>", replace_blob, media_xml)
    if changed == 0:
        raise DirectDrpError(f"Не удалось обновить бинарную ссылку на медиа: {name}")
    return media_xml


def _replace_vec(xml: str, tag: str, elements: list[str]) -> str:
    body = "\n".join(f"   <Element>{element}</Element>" for element in elements)
    replacement = f"<{tag}>\n{body}\n </{tag}>" if body else f"<{tag}/ >"
    # Resolve writes explicit empty vectors; use their exact self-closing spelling.
    replacement = replacement.replace("/ >", "/>")
    updated, count = re.subn(fr"<{tag}>[\s\S]*?</{tag}>", lambda _m: replacement, xml, count=1)
    if not count:
        if not re.search(fr"<{tag}\s*/>", xml):
            raise DirectDrpError(f"В таймлайне не найден вектор {tag}.")
        updated = re.sub(fr"<{tag}\s*/>", lambda _m: replacement, xml, count=1)
    return updated


def _tracks(seq_xml: str, kind: str) -> list[str]:
    body = _element(seq_xml, f"{kind}TrackVec")
    return re.findall(r"<Element>\s*(<Sm2TiTrack\b[\s\S]*?</Sm2TiTrack>)\s*</Element>", body)


def _clear_track(track_xml: str, sequence_id: str) -> str:
    track_xml, _ = _fresh_ids(track_xml, sequence_id=sequence_id)
    track_xml = re.sub(r"<Items\s*/>|<Items>[\s\S]*?</Items>", "<Items/>", track_xml, count=1)
    track_xml = re.sub(r"<Sequence>[^<]*</Sequence>", f"<Sequence>{sequence_id}</Sequence>", track_xml, count=1)
    return track_xml


def _clip_template(track_xml: str, media_kind: str) -> str:
    match = re.search(fr"<Element>\s*(<Sm2Ti{media_kind}Clip\b[\s\S]*?</Sm2Ti{media_kind}Clip>)\s*</Element>", track_xml)
    if not match:
        raise DirectDrpError(f"В шаблоне нет клипа {media_kind.lower()} для клонирования.")
    return match.group(1)


def _make_timeline_clip(
    template: str,
    *,
    media_id: str | None,
    media_path: str | None,
    name: str,
    start: int,
    duration: int,
    source_in: int,
    fps: float,
) -> str:
    clip, _ = _fresh_ids(template)
    clip_tag = "Sm2TiVideoClip" if "Sm2TiVideoClip" in clip else "Sm2TiAudioClip"
    clip = _set_object_name(clip, clip_tag, name)
    clip = _set_first(clip, "Start", str(start))
    clip = _set_first(clip, "Duration", str(duration))
    clip = re.sub(
        r"<MediaRef>[^<]*</MediaRef>|<MediaRef\s*/>",
        f"<MediaRef>{media_id}</MediaRef>" if media_id else "<MediaRef/>",
        clip,
        count=1,
    )
    clip = re.sub(
        r"<MediaFilePath>[^<]*</MediaFilePath>|<MediaFilePath\s*/>",
        f"<MediaFilePath>{escape(media_path or '')}</MediaFilePath>",
        clip,
        count=1,
    )
    in_blob = struct.pack("<d", source_in * 0.001).hex()
    encoded_in = f"{source_in}|{in_blob}"
    clip = re.sub(r"<In\s*/>|<In>[^<]*</In>", f"<In>{encoded_in}</In>", clip, count=1)
    return re.sub(r"<MediaFrameRate>[^<]*</MediaFrameRate>", f"<MediaFrameRate>{_encode_rate(fps)}</MediaFrameRate>", clip, count=1)


def _make_seq_container(
    template: str,
    *,
    timeline_id: str,
    width: int,
    height: int,
    fps: float,
    video_tracks: list[list[str]],
    audio_tracks: list[list[str]],
) -> tuple[str, str]:
    seq, root_id = _fresh_ids(template, sequence_id=timeline_id)
    if not root_id:
        raise DirectDrpError("Не удалось назначить идентификатор новому таймлайну.")
    for kind, clips_by_track in (("Video", video_tracks), ("Audio", audio_tracks)):
        tracks = _tracks(seq, kind)
        if not tracks:
            raise DirectDrpError(f"В шаблоне отсутствуют дорожки {kind.lower()}.")
        while len(tracks) < len(clips_by_track):
            tracks.append(_clear_track(tracks[0], timeline_id))
        built: list[str] = []
        for index, track in enumerate(tracks):
            track = _clear_track(track, timeline_id)
            clip_elements = clips_by_track[index] if index < len(clips_by_track) else []
            if clip_elements:
                items = "".join(f"<Element>{clip}</Element>" for clip in clip_elements)
                track = re.sub(r"<Items\s*/>", f"<Items>{items}</Items>", track, count=1)
            built.append(track)
        seq = _replace_vec(seq, f"{kind}TrackVec", built)
    return seq, root_id


def _timeline_shell(template_mp: str, template_seq: str, *, name: str, fps: float, width: int, height: int):
    old_seq_id = re.search(fr"<UniqueSequenceId>({_UUID})</UniqueSequenceId>", template_mp)
    if not old_seq_id:
        raise DirectDrpError("В шаблоне не найден ID секвенции.")
    new_seq_id = str(uuid.uuid4())
    timeline, _ = _fresh_ids(template_mp, sequence_id=new_seq_id)
    timeline = _set_object_name(timeline, "Sm2MpTimelineClip", name)
    timeline = re.sub(r"<UniqueSequenceId>[^<]*</UniqueSequenceId>", f"<UniqueSequenceId>{new_seq_id}</UniqueSequenceId>", timeline, count=1)
    timeline = re.sub(r"<FrameRate>[^<]*</FrameRate>", f"<FrameRate>{_encode_rate(fps)}</FrameRate>", timeline, count=1)
    timeline = re.sub(r"<Resolution>[^<]*</Resolution>", f"<Resolution>{_encode_resolution(width, height)}</Resolution>", timeline, count=1)
    timeline = re.sub(
        r"(<Sm2Timeline\b[^>]*>\s*<FieldsBlob\s*/>\s*<Name>)[^<]*(</Name>)",
        lambda m: f"{m.group(1)}{escape(name)}{m.group(2)}",
        timeline,
        count=1,
    )
    return timeline, new_seq_id


def _patch_seq_ref(timeline_xml: str, source_container_id: str, target_container_id: str) -> str:
    """Point the timeline's opaque Sequence.SeqRef at its cloned container."""
    old_ref = ("H" + source_container_id).encode("utf-16le").hex()
    new_ref = ("H" + target_container_id).encode("utf-16le").hex()
    updated = timeline_xml
    replacements = 0

    def patch_sequence(match: re.Match[str]) -> str:
        nonlocal replacements
        sequence = match.group(0)
        blob_pattern = re.compile(r"(<Sm2Sequence\b[\s\S]*?<FieldsBlob>)([0-9a-fA-F]+)(</FieldsBlob>)")

        def patch_blob(blob_match: re.Match[str]) -> str:
            nonlocal replacements
            blob = blob_match.group(2)
            if old_ref not in blob:
                return blob_match.group(0)
            replacements += blob.count(old_ref)
            return f"{blob_match.group(1)}{blob.replace(old_ref, new_ref)}{blob_match.group(3)}"

        return blob_pattern.sub(patch_blob, sequence, count=1)

    updated = re.sub(r"<Sm2Sequence\b[\s\S]*?</Sm2Sequence>", patch_sequence, updated)
    if replacements != 1:
        raise DirectDrpError("Не удалось обновить скрытую ссылку таймлайна на контейнер секвенции.")
    return updated


def _make_folder_nodes(
    folders: list[dict[str, object]], parent_id: str, archive_parent: str = "MediaPool/Master",
    logical_parent: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    for index, folder in enumerate(folders):
        name = str(folder.get("name") or "Bin")
        archive_name = re.sub(r"[\\/:\x00-\x1f]", "_", name).strip(" .") or "Bin"
        archive_name = f"{index:03d}_{archive_name}"
        folder_id = str(uuid.uuid4())
        node: dict[str, object] = {
            "name": name,
            "id": folder_id,
            "parent_id": parent_id,
            "archive_path": f"{archive_parent}/{archive_name}/MpFolder.xml",
            "media_blocks": [],
            "logical_path": logical_parent + (name,),
        }
        node["children"] = _make_folder_nodes(
            folder.get("folders") or [], folder_id, f"{archive_parent}/{archive_name}",
            logical_parent + (name,),
        )
        node["media"] = folder.get("media") or []
        nodes.append(node)
    return nodes


def _folder_xml(folder: dict[str, object], media_pool_id: str) -> str:
    media_vec = "".join(
        f"\n  <Element>{block}</Element>" for block in folder["media_blocks"]
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!--DbPrjVer="17"-->\n'
        f'<Sm2MpFolder DbId="{folder["id"]}">\n'
        f' <FieldsBlob>{_EMPTY_BIN_FIELDS}</FieldsBlob>\n'
        f' <Name>{escape(str(folder["name"]))}</Name>\n'
        f' <MpFolder>{folder["parent_id"]}</MpFolder>\n'
        f' <UniqueMediaPoolItemId>{uuid.uuid4()}</UniqueMediaPoolItemId>\n'
        f' <MediaVec>{media_vec}\n </MediaVec>\n'
        f' <MediaPool>{media_pool_id}</MediaPool>\n'
        ' <Folded>true</Folded>\n'
        ' <ColorTag>FOLDER_COLOR_NONE</ColorTag>\n'
        ' <LockSysId/>\n'
        ' <DbSavedTime>0</DbSavedTime>\n'
        '</Sm2MpFolder>'
    )


def create_drp_from_manifest(manifest_path: Path, output_path: Path, on_log=None) -> Path:
    """Create a multi-timeline DRP using bundled Resolve-authored archive templates."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DirectDrpError(f"Не удалось прочитать описание секвенций: {error}") from error
    timelines = manifest.get("timelines") or []
    if not timelines:
        raise DirectDrpError("В проекте Premiere не найдены секвенции для сохранения в DRP.")

    assets = Path(__file__).parent / "assets"
    template_path = assets / "resolve-media-clip-h264.drp"
    if not template_path.is_file():
        raise DirectDrpError("Не найден встроенный шаблон DRP.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        index = 2
        while output_path.with_name(f"{output_path.stem} ({index}){output_path.suffix}").exists():
            index += 1
        output_path = output_path.with_name(f"{output_path.stem} ({index}){output_path.suffix}")

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(template_path) as template_zip:
            entries = {name: template_zip.read(name) for name in template_zip.namelist() if not name.endswith("/")}
        mp_path = "MediaPool/Master/MpFolder.xml"
        mp_xml = entries[mp_path].decode("utf-8")
        root_folder_id = _uuid_attr(mp_xml, "Sm2MpFolder")
        media_pool_match = re.search(r"<MediaPool>([^<]+)</MediaPool>", mp_xml)
        if not media_pool_match:
            raise DirectDrpError("В шаблоне не найден идентификатор корневого Media Pool.")
        folder_nodes = _make_folder_nodes(manifest.get("media_folders") or [], root_folder_id)
        media_template = re.search(r"<Sm2MpVideoClip\b[\s\S]*?</Sm2MpVideoClip>", mp_xml)
        timeline_template = re.search(r"<Sm2MpTimelineClip\b[\s\S]*?</Sm2MpTimelineClip>", mp_xml)
        if not media_template or not timeline_template:
            raise DirectDrpError("Встроенный шаблон не содержит записи медиа и секвенции.")
        media_template_xml = media_template.group(0)
        sequence_paths = [name for name in entries if name.startswith("SeqContainer/") and name.endswith(".xml")]
        if len(sequence_paths) != 1:
            raise DirectDrpError("Встроенный шаблон должен содержать ровно один таймлайн.")
        seq_template = entries[sequence_paths[0]].decode("utf-8")
        template_container_id = _uuid_attr(seq_template, "Sm2SequenceContainer")
        media_info = re.search(r"<BtVideoInfo\b[\s\S]*?<Clip>([0-9a-fA-F]+)</Clip>", media_template_xml)
        if not media_info:
            raise DirectDrpError("В медиашаблоне не найден бинарный медиадескриптор.")
        old_media_path = _resolve_media_path(bytes.fromhex(media_info.group(1)))
        media_template_id = _uuid_attr(media_template_xml, "Sm2MpVideoClip")
        video_template_track = _tracks(seq_template, "Video")[0]
        audio_template_track = _tracks(seq_template, "Audio")[0]
        video_clip_template = _clip_template(video_template_track, "Video")
        audio_clip_template = _clip_template(audio_template_track, "Audio")

        media_ids: dict[str, str] = {}
        media_blocks: list[str] = []
        timeline_blocks: list[str] = []
        new_seq_entries: dict[str, bytes] = {}
        total_video = total_audio = 0
        nested_media_refs: dict[str, str] = {}

        def iter_folders(nodes):
            for node in nodes:
                yield node
                yield from iter_folders(node["children"])

        for folder in iter_folders(folder_nodes):
            for media in folder["media"]:
                source_path = str(media.get("path") or "")
                if not source_path:
                    continue
                media_block, media_id = _fresh_ids(media_template_xml)
                media_block = _patch_media_path(
                    media_block,
                    old_media_path,
                    source_path,
                    str(media.get("name") or Path(source_path).name),
                    str(folder["id"]),
                )
                # Keep separate Media Pool objects when Premiere has the same
                # file in multiple bins; DRP stores bin membership per item,
                # even though timeline clip references can share one instance.
                media_ids.setdefault(source_path, media_id)
                folder["media_blocks"].append(media_block)

        def add_root_media(media: dict[str, object]) -> None:
            source_path = str(media.get("path") or "")
            if not source_path:
                return
            media_block, media_id = _fresh_ids(media_template_xml)
            media_block = _patch_media_path(
                media_block, old_media_path, source_path,
                str(media.get("name") or Path(source_path).name), root_folder_id,
            )
            media_ids.setdefault(source_path, media_id)
            media_blocks.append(media_block)

        for media in manifest.get("root_media") or []:
            add_root_media(media)

        folder_by_path = {tuple(node["logical_path"]): node for node in iter_folders(folder_nodes)}

        for timeline in timelines:
            name = str(timeline.get("timeline_name") or "Premiere timeline")
            fps = float(timeline.get("frame_rate") or 24)
            width, height = int(timeline.get("width") or 1920), int(timeline.get("height") or 1080)
            clips = [clip for clip in timeline.get("clips", []) if int(clip.get("end_frame", 0)) > int(clip.get("start_frame", 0))]
            max_video = max((int(c.get("track_index", 1)) for c in clips if int(c.get("media_type", 1)) == 1), default=1)
            max_audio = max((int(c.get("track_index", 1)) for c in clips if int(c.get("media_type", 1)) == 2), default=1)
            video_tracks: list[list[str]] = [[] for _ in range(max_video)]
            audio_tracks: list[list[str]] = [[] for _ in range(max_audio)]
            sequence_origin = round(fps * 3600)

            for clip in clips:
                source_path = str(clip.get("path") or "")
                nested_sequence_id = str(clip.get("nested_sequence_id") or "")
                adjustment_layer = bool(clip.get("adjustment_layer"))
                if not source_path and not nested_sequence_id and not adjustment_layer:
                    continue
                if nested_sequence_id:
                    media_id = nested_media_refs.setdefault(nested_sequence_id, str(uuid.uuid4()))
                elif adjustment_layer:
                    media_id = None
                elif source_path not in media_ids:
                    media_block, media_id = _fresh_ids(media_template_xml)
                    media_block = _patch_media_path(
                        media_block,
                        old_media_path,
                        source_path,
                        str(clip.get("name") or Path(source_path).name),
                        root_folder_id,
                    )
                    media_ids[source_path] = media_id
                    media_blocks.append(media_block)
                else:
                    media_id = media_ids[source_path]
                media_type = int(clip.get("media_type", 1))
                track_index = max(1, int(clip.get("track_index", 1))) - 1
                source_in = int(clip.get("start_frame", 0))
                duration = int(clip.get("end_frame", 0)) - source_in
                record = int(clip.get("record_frame", 0))
                item_name = str(clip.get("name") or Path(source_path).name)
                node = _make_timeline_clip(
                    video_clip_template if media_type == 1 else audio_clip_template,
                    media_id=media_id,
                    media_path=source_path,
                    name=item_name,
                    start=sequence_origin + record,
                    duration=duration,
                    source_in=source_in,
                    fps=fps,
                )
                if media_type == 1:
                    video_tracks[track_index].append(node)
                    total_video += 1
                else:
                    audio_tracks[track_index].append(node)
                    total_audio += 1

            timeline_id = str(uuid.uuid4())
            timeline_block = None
            if timeline.get("media_pool_visible", True):
                timeline_block, timeline_id = _timeline_shell(
                    timeline_template.group(0), seq_template,
                    name=name, fps=fps, width=width, height=height,
                )
            # Rebuild tracks after the shell has received its final per-timeline IDs.
            seq, container_id = _make_seq_container(
                seq_template,
                timeline_id=timeline_id,
                width=width,
                height=height,
                fps=fps,
                video_tracks=video_tracks,
                audio_tracks=audio_tracks,
            )
            if timeline_block is not None:
                timeline_block = _patch_seq_ref(timeline_block, template_container_id, container_id)
                target_folder = folder_by_path.get(tuple(timeline.get("media_bin_path") or []))
                if target_folder is None:
                    timeline_blocks.append(timeline_block)
                else:
                    target_folder["media_blocks"].append(timeline_block)
            new_seq_entries[f"SeqContainer/{container_id}.xml"] = seq.encode("utf-8")

        if not new_seq_entries:
            raise DirectDrpError("В проекте не найдено клипов для сборки таймлайнов.")
        media_vec = f"<MediaVec>\n{''.join(f'<Element>{block}</Element>' for block in media_blocks + timeline_blocks)}\n </MediaVec>"
        mp_xml = re.sub(r"<MediaVec>[\s\S]*?</MediaVec>", lambda _m: media_vec, mp_xml, count=1)
        entries[mp_path] = mp_xml.encode("utf-8")
        for folder in iter_folders(folder_nodes):
            entries[str(folder["archive_path"])] = _folder_xml(
                folder, media_pool_match.group(1)
            ).encode("utf-8")
        for old_name in sequence_paths:
            del entries[old_name]
        entries.update(new_seq_entries)

        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as output_zip:
            for name, data in entries.items():
                output_zip.writestr(name, data)
        inspection = inspect_drp_archive(temp_output)
        if inspection.timeline_count != len(new_seq_entries):
            raise DirectDrpError("Проверка DRP выявила неверное число секвенций.")
        if inspection.video_clip_count != total_video or inspection.audio_clip_count != total_audio:
            raise DirectDrpError("Проверка DRP выявила потерю клипов при сборке.")
        if inspection.unresolved_media_references != len(nested_media_refs):
            raise DirectDrpError(
                "В DRP число ссылок на вложенные секвенции не совпало с числом ожидаемых записей: "
                f"{inspection.unresolved_media_references} вместо {len(nested_media_refs)}."
            )
        temp_output.replace(output_path)
        if on_log:
            on_log("log_drp_verified", {
                "video": inspection.video_clip_count,
                "audio": inspection.audio_clip_count,
                "media": inspection.media_item_count,
            })
        return output_path
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, KeyError, ValueError) as error:
        temp_output.unlink(missing_ok=True)
        if isinstance(error, DirectDrpError):
            raise
        if isinstance(error, DrpArchiveError):
            raise DirectDrpError(f"Собранный DRP не прошёл проверку: {error}") from error
        raise DirectDrpError(f"Не удалось собрать DRP-файл: {error}") from error
    finally:
        temp_output.unlink(missing_ok=True)
