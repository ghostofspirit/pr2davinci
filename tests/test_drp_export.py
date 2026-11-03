from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from premiere_to_resolve.converter import SequenceEntry
from premiere_to_resolve.drp_export import export_prproj_to_drp


class DirectDrpExportWorkflowTests(unittest.TestCase):
    def test_shared_export_builds_manifest_for_all_native_sequences(self):
        entries = [
            SequenceEntry(0, "Главный", "sequence-1", native=True),
            SequenceEntry(1, "Эпизод", "sequence-2", native=True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project.prproj"
            source.touch()
            output = root / "project.drp"
            captured: dict[str, object] = {}

            def write_manifest(source_path, manifest_path, sequence_index, on_warning):
                captured["source"] = source_path
                captured["sequence_index"] = sequence_index
                captured["warning_callback"] = on_warning
                Path(manifest_path).write_text("{}", encoding="utf-8")

            def build_drp(manifest_path, output_path, on_log=None):
                captured["manifest"] = Path(manifest_path).read_text(encoding="utf-8")
                captured["log_callback"] = on_log
                Path(output_path).write_bytes(b"DRP")
                return Path(output_path)

            with patch("premiere_to_resolve.drp_export.list_sequence_entries", return_value=entries), \
                 patch("premiere_to_resolve.drp_export.write_resolve_manifest", side_effect=write_manifest), \
                 patch("premiere_to_resolve.drp_export.create_drp_from_manifest", side_effect=build_drp):
                result = export_prproj_to_drp(source, output)

            self.assertEqual(result, output)
            self.assertEqual(output.read_bytes(), b"DRP")
            self.assertEqual(captured["source"], source)
            self.assertIsNone(captured["sequence_index"])
            self.assertEqual(captured["manifest"], "{}")


if __name__ == "__main__":
    unittest.main()
