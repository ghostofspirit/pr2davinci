import json
import re
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from premiere_to_resolve.direct_drp import _resolve_media_path, create_drp_from_manifest
from premiere_to_resolve.direct_drp_compare import compare_drp_archives
from premiere_to_resolve.drp_archive import inspect_drp_archive


class DirectDrpTests(unittest.TestCase):
    def test_authors_multiple_populated_timelines_offline_without_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            manifest = folder / "timelines.json"
            manifest.write_text(json.dumps({
                "timelines": [
                    {
                        "timeline_name": "Главный",
                        "frame_rate": "25.000000",
                        "width": 1920,
                        "height": 1080,
                        "clips": [
                            {"path": "/offline/A.mp4", "name": "A.mp4", "media_type": 1, "track_index": 1, "start_frame": 24, "end_frame": 48, "record_frame": 0},
                            {"path": "/offline/B.mp4", "name": "B.mp4", "media_type": 1, "track_index": 2, "start_frame": 0, "end_frame": 36, "record_frame": 72},
                            {"path": "/offline/A.mp4", "name": "A.mp4", "media_type": 2, "track_index": 1, "start_frame": 24, "end_frame": 48, "record_frame": 0},
                        ],
                    },
                    {
                        "timeline_name": "Эпизод",
                        "frame_rate": "23.976000",
                        "width": 3840,
                        "height": 2160,
                        "clips": [
                            {"path": "/offline/C.mov", "name": "C.mov", "media_type": 2, "track_index": 2, "start_frame": 100, "end_frame": 200, "record_frame": 24},
                        ],
                    },
                ],
                "media_folders": [
                    {
                        "name": "Footage",
                        "media": [{"name": "B.mp4", "path": "/offline/B.mp4"}],
                        "folders": [
                            {"name": "Sound", "media": [{"name": "C.mov", "path": "/offline/C.mov"}]}
                        ],
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            output = create_drp_from_manifest(manifest, folder / "project.drp")

            inspection = inspect_drp_archive(output)
            self.assertEqual((inspection.timeline_count, inspection.video_clip_count, inspection.audio_clip_count), (2, 2, 2))
            self.assertEqual(inspection.media_item_count, 3)
            self.assertEqual(inspection.unresolved_media_references, 0)
            with ZipFile(output) as archive:
                media_pool = archive.read("MediaPool/Master/MpFolder.xml").decode("utf-8")
                timeline_names = re.findall(
                    r'<Sm2Timeline DbId="[^"]+">\s*<FieldsBlob/>\s*<Name>(.*?)</Name>', media_pool
                )
                self.assertEqual(timeline_names, ["Главный", "Эпизод"])
                container_ids = {
                    Path(name).stem for name in archive.namelist()
                    if name.startswith("SeqContainer/") and name.endswith(".xml")
                }
                timeline_blocks = re.findall(
                    r"<Sm2MpTimelineClip\b[\s\S]*?</Sm2MpTimelineClip>", media_pool
                )
                for block in timeline_blocks:
                    sequence_blob = re.search(
                        r"<Sm2Sequence\b[\s\S]*?<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", block
                    )
                    self.assertIsNotNone(sequence_blob)
                    linked_containers = {
                        container_id for container_id in container_ids
                        if ("H" + container_id).encode("utf-16le").hex() in sequence_blob.group(1)
                    }
                    self.assertEqual(len(linked_containers), 1)
                linked_ids = []
                for block in timeline_blocks:
                    sequence_blob = re.search(
                        r"<Sm2Sequence\b[\s\S]*?<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", block
                    )
                    linked = [
                        container_id for container_id in container_ids
                        if ("H" + container_id).encode("utf-16le").hex() in sequence_blob.group(1)
                    ]
                    self.assertEqual(len(linked), 1)
                    linked_ids.extend(linked)
                self.assertEqual(set(linked_ids), container_ids)
                self.assertEqual(len(linked_ids), len(set(linked_ids)))
                comparison = compare_drp_archives(output, output)
                self.assertEqual(comparison["generated"]["sequence_links"], {
                    "media_pool_timeline_count": 2,
                    "broken_timeline_references": 0,
                    "unreferenced_sequence_containers": 0,
                    "reused_sequence_references": 0,
                })
                self.assertEqual(comparison["generated"]["timelines"], [
                    {"name": "Главный", "sequence_container_linked": True, "video_clips": 2, "audio_clips": 1},
                    {"name": "Эпизод", "sequence_container_linked": True, "video_clips": 0, "audio_clips": 1},
                ])
                all_folder_xml = "".join(
                    archive.read(name).decode("utf-8")
                    for name in archive.namelist()
                    if name.endswith("/MpFolder.xml")
                )
                media_blocks = re.findall(r"<Sm2MpVideoClip\b[\s\S]*?</Sm2MpVideoClip>", all_folder_xml)
                resolved_paths = []
                for block in media_blocks:
                    clip_blob = re.search(r"<BtVideoInfo\b[\s\S]*?<Clip>([0-9a-fA-F]+)</Clip>", block)
                    self.assertIsNotNone(clip_blob)
                    resolved_paths.append(_resolve_media_path(bytes.fromhex(clip_blob.group(1))))
                self.assertEqual(set(resolved_paths), {"/offline/A.mp4", "/offline/B.mp4", "/offline/C.mov"})
                self.assertIn("MediaPool/Master/000_Footage/MpFolder.xml", archive.namelist())
                self.assertIn("MediaPool/Master/000_Footage/000_Sound/MpFolder.xml", archive.namelist())
                footage = archive.read("MediaPool/Master/000_Footage/MpFolder.xml").decode("utf-8")
                sound = archive.read("MediaPool/Master/000_Footage/000_Sound/MpFolder.xml").decode("utf-8")
                footage_id = re.search(r'<Sm2MpFolder DbId="([^"]+)"', footage).group(1)
                sound_id = re.search(r'<Sm2MpFolder DbId="([^"]+)"', sound).group(1)
                master_id = re.search(r'<Sm2MpFolder DbId="([^"]+)"', media_pool).group(1)
                self.assertIn("<Name>Footage</Name>", footage)
                self.assertIn(f"<MpFolder>{footage_id}</MpFolder>", sound)
                self.assertIn(f"<MpFolder>{master_id}</MpFolder>", footage)
                self.assertIn(f"<MpFolder>{footage_id}</MpFolder>", footage)
                self.assertIn(f"<MpFolder>{sound_id}</MpFolder>", sound)

    def test_preserves_empty_timelines_alongside_populated_timelines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps({
                "timelines": [
                    {
                        "timeline_name": "Empty sequence",
                        "frame_rate": "24",
                        "width": 1920,
                        "height": 1080,
                        "clips": [],
                    },
                    {
                        "timeline_name": "Main",
                        "frame_rate": "24",
                        "width": 1920,
                        "height": 1080,
                        "clips": [{
                            "path": "/offline/main.mov",
                            "name": "main.mov",
                            "media_type": 1,
                            "track_index": 1,
                            "start_frame": 0,
                            "end_frame": 24,
                            "record_frame": 0,
                        }],
                    },
                ],
                "media_folders": [],
            }), encoding="utf-8")

            output = create_drp_from_manifest(manifest, folder / "project.drp")
            inspection = inspect_drp_archive(output)
            with ZipFile(output) as archive:
                master = archive.read("MediaPool/Master/MpFolder.xml").decode("utf-8")

            self.assertEqual(inspection.timeline_count, 2)
            self.assertEqual(inspection.video_clip_count, 1)
            self.assertEqual(master.count("<Sm2MpTimelineClip"), 2)

    def test_preserves_duplicate_media_items_in_separate_bins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps({
                "timelines": [{
                    "timeline_name": "Main",
                    "frame_rate": "24",
                    "width": 1920,
                    "height": 1080,
                    "clips": [{
                        "path": "/offline/shared.mov",
                        "name": "shared.mov",
                        "media_type": 1,
                        "track_index": 1,
                        "start_frame": 0,
                        "end_frame": 24,
                        "record_frame": 0,
                    }],
                }],
                "media_folders": [
                    {"name": "Bin A", "media": [{"name": "shared.mov", "path": "/offline/shared.mov"}], "folders": []},
                    {"name": "Bin B", "media": [{"name": "shared.mov", "path": "/offline/shared.mov"}], "folders": []},
                ],
            }), encoding="utf-8")

            output = create_drp_from_manifest(manifest, folder / "project.drp")
            inspection = inspect_drp_archive(output)

            self.assertEqual(inspection.media_item_count, 2)
            self.assertEqual(inspection.unresolved_media_references, 0)

    def test_does_not_overwrite_an_existing_drp(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            manifest = folder / "timelines.json"
            manifest.write_text(json.dumps({"timelines": [{
                "timeline_name": "One", "frame_rate": "24", "width": 1920, "height": 1080,
                "clips": [{"path": "/offline/a.mp4", "name": "a.mp4", "media_type": 1, "track_index": 1, "start_frame": 0, "end_frame": 10, "record_frame": 0}],
            }]}), encoding="utf-8")
            requested = folder / "project.drp"
            requested.write_bytes(b"preserve this file")

            created = create_drp_from_manifest(manifest, requested)

            self.assertEqual(requested.read_bytes(), b"preserve this file")
            self.assertEqual(created.name, "project (2).drp")
            inspect_drp_archive(created)


if __name__ == "__main__":
    unittest.main()
