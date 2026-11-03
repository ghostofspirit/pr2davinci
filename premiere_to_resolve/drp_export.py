"""Shared offline Premiere-to-DRP export workflow used by GUI and CLI."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Callable

from .converter import ConversionError, list_sequence_entries, write_resolve_manifest
from .direct_drp import DirectDrpError, create_drp_from_manifest


def export_prproj_to_drp(
    source: Path,
    output: Path,
    *,
    temporary_root: Path | None = None,
    on_warning: Callable[[str], None] | None = None,
    on_log: Callable[[str, dict[str, object]], None] | None = None,
) -> Path:
    """Write every top-level sequence and project bin into a DRP, without Resolve."""
    source, output = source.expanduser(), output.expanduser()
    entries = list_sequence_entries(source)
    if not entries:
        raise DirectDrpError("В проекте Premiere не найдены секвенции для сохранения в DRP.")
    if not all(entry.native for entry in entries):
        raise DirectDrpError(
            "Прямой экспорт DRP принимает нативные проекты Premiere (.prproj). "
            "Для XML/FCPXML используйте экспорт interchange."
        )

    try:
        with tempfile.TemporaryDirectory(
            prefix="pr2davinci-drtmp-",
            dir=str(temporary_root) if temporary_root else None,
        ) as temporary_directory:
            manifest_path = Path(temporary_directory) / "timelines.json"
            write_resolve_manifest(source, manifest_path, sequence_index=None, on_warning=on_warning)
            return create_drp_from_manifest(manifest_path, output, on_log=on_log)
    except (OSError, ConversionError, DirectDrpError):
        raise
    except Exception as error:
        raise DirectDrpError(f"Не удалось сохранить DRP: {error}") from error
