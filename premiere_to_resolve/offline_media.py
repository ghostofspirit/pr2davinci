"""Create temporary Resolve-readable proxies for media that should stay offline.

Resolve's scripting API will not create Media Pool entries for missing paths. We
therefore build one lightweight proxy per source, assemble the timeline against
those proxies, then rewrite the DRP's media references back to the Premiere
paths. The proxies are temporary and are never included in the final archive.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape


class OfflineMediaError(RuntimeError):
    pass


def proxy_path_for(source_path: str | Path, proxy_dir: Path) -> Path:
    key = os.fsencode(str(source_path))
    return proxy_dir / f"{hashlib.sha256(key).hexdigest()}.mp4"


def create_offline_proxies(
    source_paths: list[str],
    proxy_dir: Path,
    frame_count: int,
    frame_rate: str,
) -> dict[str, str]:
    """Generate one shared black A/V essence and unique hard-linked proxy names."""
    if not source_paths:
        raise OfflineMediaError("В секвенции не найдено ссылок на медиа.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise OfflineMediaError(
            "Для создания офлайн-клипов нужен ffmpeg. Установите ffmpeg и повторите передачу."
        )

    proxy_dir.mkdir(parents=True, exist_ok=True)
    frame_count = max(2, int(frame_count) + 2)
    with tempfile.NamedTemporaryFile(prefix="offline-base-", suffix=".mp4", dir=proxy_dir, delete=False) as handle:
        base_path = Path(handle.name)
    base_path.unlink()
    try:
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=64x64:r={frame_rate}",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-frames:v", str(frame_count), "-c:v", "libx264", "-preset", "ultrafast",
            "-tune", "stillimage", "-crf", "40", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "16k", "-shortest", "-movflags", "+faststart",
            str(base_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode != 0 or not base_path.is_file() or base_path.stat().st_size == 0:
            detail = result.stderr.strip() or f"ffmpeg завершился с кодом {result.returncode}."
            raise OfflineMediaError(f"Не удалось создать временные офлайн-клипы: {detail}")

        mappings: dict[str, str] = {}
        for source in dict.fromkeys(source_paths):
            proxy = proxy_path_for(source, proxy_dir)
            if not proxy.exists():
                try:
                    os.link(base_path, proxy)
                except OSError:
                    shutil.copyfile(base_path, proxy)
            mappings[source] = str(proxy)
        return mappings
    except subprocess.TimeoutExpired as error:
        raise OfflineMediaError("Создание временных офлайн-клипов превысило лимит времени.") from error
    finally:
        base_path.unlink(missing_ok=True)


_HEX_BLOB = re.compile(r">([0-9a-fA-F]{40,})<")


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _replace_length_delimited(blob: bytes, old: bytes, new: bytes) -> tuple[bytes, bool]:
    offset = blob.find(old)
    if offset < 0:
        return blob, False
    old_length = _varint(len(old))
    prefix = offset - len(old_length)
    if prefix < 0 or blob[prefix:offset] != old_length:
        return blob, False
    return blob[:prefix] + _varint(len(new)) + new + blob[offset + len(old):], True


def _repoint_blob(blob: bytes, old_path: str, new_path: str) -> tuple[bytes, bool]:
    old_dir = os.fsencode(str(Path(old_path).parent))
    old_name = os.fsencode(Path(old_path).name)
    new_dir = os.fsencode(str(Path(new_path).parent))
    new_name = os.fsencode(Path(new_path).name)
    result = blob
    changed = False
    for old, new in ((old_dir, new_dir), (old_name, new_name)):
        if old == new:
            continue
        result, found = _replace_length_delimited(result, old, new)
        changed = changed or found
    if changed and len(result) >= 8:
        payload_length = int.from_bytes(result[4:8], "big")
        result = result[:4] + (payload_length + len(result) - len(blob)).to_bytes(4, "big") + result[8:]
    return result, changed


def repoint_drp_media(path: Path, mappings: dict[str, str]) -> dict[str, int]:
    """Point temporary proxy entries at their intended offline source paths."""
    if not mappings:
        raise OfflineMediaError("В DRP нет временных медиа-ссылок для замены.")
    counts = {source: 0 for source in mappings}
    temporary = path.with_suffix(path.suffix + ".repointing")
    try:
        with zipfile.ZipFile(path, "r") as source_zip, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for info in source_zip.infolist():
                data = source_zip.read(info.filename)
                if info.filename.lower().endswith(".xml"):
                    try:
                        xml = data.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise OfflineMediaError(f"Не удалось прочитать XML в DRP: {info.filename}") from error
                    for proxy_path, source_path in mappings.items():
                        proxy_escaped = escape(proxy_path)
                        source_escaped = escape(source_path)
                        text_refs = xml.count(proxy_escaped)
                        xml = xml.replace(proxy_escaped, source_escaped)
                        xml = xml.replace(f"<Name>{Path(proxy_path).name}</Name>", f"<Name>{escape(Path(source_path).name)}</Name>")
                        if text_refs:
                            counts[proxy_path] += text_refs

                        def replace_blob(match: re.Match[str], *, old: str = proxy_path, new: str = source_path) -> str:
                            blob = bytes.fromhex(match.group(1))
                            updated, changed = _repoint_blob(blob, old, new)
                            if changed:
                                counts[old] += 1
                            return f">{updated.hex()}<" if changed else match.group(0)

                        xml = _HEX_BLOB.sub(replace_blob, xml)
                    data = xml.encode("utf-8")
                target_zip.writestr(info, data)
        os.replace(temporary, path)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        temporary.unlink(missing_ok=True)
        raise OfflineMediaError(f"Не удалось обновить ссылки на медиа в DRP: {error}") from error

    untouched = [source for source, replacements in counts.items() if replacements == 0]
    if untouched:
        raise OfflineMediaError(
            f"Resolve не сохранил медиадескрипторы для {len(untouched)} исходников; DRP не завершён."
        )
    return counts
