"""Structural inspection for Resolve project archives.

Resolve's ``.drp`` container is a ZIP archive. Its project and media-pool XML can
contain opaque Resolve payloads that are not well-formed XML, so validation only
parses the comparatively stable ``SeqContainer`` files and scans media-pool IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


class DrpArchiveError(ValueError):
    """The archive is not a structurally readable Resolve project."""


@dataclass(frozen=True)
class DrpInspection:
    timeline_count: int
    video_clip_count: int
    audio_clip_count: int
    media_item_count: int
    unresolved_media_references: int

    @property
    def clip_count(self) -> int:
        return self.video_clip_count + self.audio_clip_count


_MEDIA_POOL_CLIP_ID = re.compile(
    rb'<Sm2Mp(?:Video|Audio)Clip\b[^>]*\bDbId="([^"]+)"'
)


def inspect_drp_archive(path: Path) -> DrpInspection:
    """Inspect a DRP without requiring Resolve or parsing opaque project blobs."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "project.xml" not in names or "MediaPool/Master/MpFolder.xml" not in names:
                raise DrpArchiveError("В архиве отсутствуют project.xml или корневая медиатека.")

            sequence_paths = sorted(
                name for name in names
                if name.startswith("SeqContainer/") and name.endswith(".xml")
            )
            if not sequence_paths:
                raise DrpArchiveError("В архиве не найдены таймлайны Resolve.")

            media_ids: set[bytes] = set()
            for name in names:
                if name.endswith("/MpFolder.xml") or name == "MediaPool/Master/MpFolder.xml":
                    media_ids.update(_MEDIA_POOL_CLIP_ID.findall(archive.read(name)))

            video_count = 0
            audio_count = 0
            references: set[str] = set()
            for name in sequence_paths:
                try:
                    root = ET.fromstring(archive.read(name))
                except ET.ParseError as error:
                    raise DrpArchiveError(f"Повреждён XML таймлайна {Path(name).name}: {error}") from error
                video_count += sum(1 for _ in root.iter("Sm2TiVideoClip"))
                audio_count += sum(1 for _ in root.iter("Sm2TiAudioClip"))
                references.update(
                    (item.text or "").strip()
                    for item in root.iter("MediaRef")
                    if item.text and item.text.strip()
                )

            missing = len(references - {value.decode("utf-8", "replace") for value in media_ids})
            result = DrpInspection(
                timeline_count=len(sequence_paths),
                video_clip_count=video_count,
                audio_clip_count=audio_count,
                media_item_count=len(media_ids),
                unresolved_media_references=missing,
            )
            if result.clip_count == 0:
                raise DrpArchiveError("DRP содержит таймлайн без клипов.")
            return result
    except DrpArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise DrpArchiveError(f"Не удалось прочитать DRP-архив: {error}") from error
