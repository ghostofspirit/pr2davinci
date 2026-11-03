import json
import tempfile
import unittest
from pathlib import Path

from premiere_to_resolve.direct_drp import create_drp_from_manifest
from premiere_to_resolve.direct_drp_compare import compare_drp_archives, write_report_new


class DirectDrpComparisonTests(unittest.TestCase):
    def _make_archive(self, root: Path, name: str, timelines: list[dict], folders=None) -> Path:
        manifest = root / f"{name}.json"
        manifest.write_text(json.dumps({"timelines": timelines, "media_folders": folders or []}), encoding="utf-8")
        return create_drp_from_manifest(manifest, root / f"{name}.drp")

    @staticmethod
    def _timeline(name: str, path: str, count: int) -> dict:
        return {
            "timeline_name": name,
            "frame_rate": "24",
            "width": 1920,
            "height": 1080,
            "clips": [
                {
                    "path": path,
                    "name": Path(path).name,
                    "media_type": 1,
                    "track_index": 1,
                    "start_frame": index * 24,
                    "end_frame": index * 24 + 12,
                    "record_frame": index * 24,
                }
                for index in range(count)
            ],
        }

    def test_comparison_is_deterministic_and_reports_project_differences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bins = [{"name": "Footage", "media": [{"name": "a.mov", "path": "/offline/a.mov"}], "folders": []}]
            reference = self._make_archive(root, "reference", [
                self._timeline("ГЛАВНЫЙ", "/offline/a.mov", 2),
                self._timeline("Эпизод", "/offline/b.mov", 1),
            ], bins)
            generated = self._make_archive(root, "generated", [
                self._timeline("ГЛАВНЫЙ", "/offline/a.mov", 1),
            ], bins)

            first = compare_drp_archives(reference, generated)
            second = compare_drp_archives(reference, generated)

            self.assertEqual(first, second)
            self.assertEqual(first["reference"]["totals"]["timeline_count"], 2)
            self.assertEqual(first["generated"]["totals"]["timeline_count"], 1)
            self.assertEqual(first["differences"]["timeline_differences"], [
                {"name": "ГЛАВНЫЙ", "occurrence": 1, "status": "different",
                 "reference": {"name": "ГЛАВНЫЙ", "sequence_container_linked": True, "video_clips": 2, "audio_clips": 0},
                 "generated": {"name": "ГЛАВНЫЙ", "sequence_container_linked": True, "video_clips": 1, "audio_clips": 0}},
                {"name": "Эпизод", "occurrence": 1, "status": "missing",
                 "reference": {"name": "Эпизод", "sequence_container_linked": True, "video_clips": 1, "audio_clips": 0}, "generated": None},
            ])
            self.assertEqual(first["differences"]["media_bins_missing_from_generated"], [])
            self.assertEqual(first["reference"]["media_bins"], [{"path": "Footage", "media_items": 1}, {"path": "Master", "media_items": 1}])

    def test_report_write_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.json"
            report = {"report_version": 1, "stable": True}
            write_report_new(target, report)
            expected = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            self.assertEqual(target.read_text(encoding="utf-8"), expected)
            with self.assertRaises(FileExistsError):
                write_report_new(target, {"different": True})
            self.assertEqual(target.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
