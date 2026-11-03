import tempfile
import unittest
import gzip
import json
from unittest import mock
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from premiere_to_resolve.converter import (
    ConversionError,
    SequenceEntry,
    convert_project,
    list_sequence_entries,
    list_sequences,
    preferred_drp_sequence_index,
    _manifest_project_media,
    write_resolve_manifest,
)
from premiere_to_resolve.cli import main


SOURCE = """<?xml version='1.0'?>
<Project><Sequence><Name>Assembly</Name><Duration>250</Duration><Rate><Timebase>25</Timebase><ntsc>FALSE</ntsc></Rate><Media>
<Video><Track><ClipItem><Name>Scene 01.mov</Name><Start>0</Start><End>100</End><In>25</In><Out>125</Out><File ObjectID='video-file'><PathURL>file://localhost/Volumes/Media/Scene%2001.mov</PathURL></File></ClipItem></Track></Video>
<Audio><Track><ClipItem><Name>Scene 01 audio</Name><Start>0</Start><End>100</End><In>25</In><Out>125</Out><File ObjectID='audio-file'><PathURL>file://localhost/Volumes/Media/Scene%2001.wav</PathURL></File></ClipItem></Track></Audio>
</Media></Sequence><Sequence><Name>Alt cut</Name><Rate><Timebase>24</Timebase><ntsc>FALSE</ntsc></Rate><Media/></Sequence></Project>"""


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "edit.prproj"
        self.output = Path(self.temp.name) / "edit.xml"
        self.source.write_text(SOURCE)

    def tearDown(self):
        self.temp.cleanup()

    def test_prefers_named_main_timeline_for_one_click_drp(self):
        entries = [
            SequenceEntry(0, "Исходник", "a"),
            SequenceEntry(4, "главный", "b"),
            SequenceEntry(5, "Эпизод", "c"),
        ]
        self.assertEqual(preferred_drp_sequence_index(entries), 4)
        self.assertEqual(preferred_drp_sequence_index(entries[:1]), 0)
        self.assertIsNone(preferred_drp_sequence_index([]))

    def test_lists_sequences(self):
        self.assertEqual(list_sequences(self.source), ["Assembly", "Alt cut"])

    def test_lists_only_top_level_sequences_not_nested_references(self):
        self.source.write_text(
            "<Project><Sequence><Name>Assembly</Name><Rate><Timebase>25</Timebase></Rate>"
            "<Sequence><Name>Nested reference</Name></Sequence></Sequence>"
            "<Sequence><Name>Alt cut</Name></Sequence></Project>"
        )
        entries = list_sequence_entries(self.source)
        self.assertEqual([entry.name for entry in entries], ["Assembly", "Alt cut"])
        self.assertEqual([entry.index for entry in entries], [0, 1])

    def test_selects_duplicate_sequence_name_by_index(self):
        self.source.write_text(
            "<Project><Sequence><Name>Same name</Name><Rate><Timebase>25</Timebase></Rate><Media/>"
            "</Sequence><Sequence><Name>Same name</Name><Rate><Timebase>24</Timebase></Rate><Media/>"
            "</Sequence></Project>"
        )
        convert_project(self.source, self.output, "Same name", sequence_index=1)
        self.assertEqual(ET.parse(self.output).findtext("sequence/rate/timebase"), "24")

    def test_exports_native_premiere_sequence_as_fcpxml(self):
        self.source.write_text(
            "<PremiereData><Sequence><Name>Main</Name><Node/></Sequence></PremiereData>"
        )
        sequence = SimpleNamespace(
            name="Main", sequence_id="sequence-uuid", video_tracks=[], audio_tracks=[]
        )
        project = SimpleNamespace(sequences=[sequence])
        exporter = SimpleNamespace(
            export_fcpxml=lambda _project, path, _sequence: Path(path).write_text("<fcpxml/>")
        )
        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project), \
             mock.patch.dict("sys.modules", {"py_premiere.export": exporter}):
            self.assertEqual(convert_project(self.source, self.output, "Main", sequence_index=0), "Main")
        self.assertEqual(ET.parse(self.output).getroot().tag, "fcpxml")

    def test_exports_native_premiere_sequence_as_track_based_xmeml_for_resolve(self):
        self.source.write_text("<PremiereData><Sequence><Name>Main</Name><Node/></Sequence></PremiereData>")
        media_file = Path(self.temp.name) / "scene.mov"
        media_file.touch()
        timebase = 10594584000

        class Time:
            def __init__(self, frames):
                self.frames = frames
                self.ticks = frames * timebase

            def to_frames(self, _timebase):
                return self.frames

        item = SimpleNamespace(name="Scene 01.mov", media_path=media_file, node_id="media-1")
        clip = SimpleNamespace(
            name="Scene 01.mov", start=Time(100), end=Time(150),
            in_point=Time(25), out_point=Time(75), project_item=item,
            components=[], selection_components=[], time_remapping=None,
        )
        track = SimpleNamespace(clips=[clip], transitions=[])
        sequence = SimpleNamespace(
            name="Main", sequence_id="sequence-uuid", timebase=timebase,
            end=Time(150), video_tracks=[track], audio_tracks=[track],
        )
        project = SimpleNamespace(sequences=[sequence])
        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project):
            convert_project(self.source, self.output, "Main", sequence_index=0, output_format="xmeml")

        root = ET.parse(self.output).getroot()
        self.assertEqual(root.tag, "xmeml")
        self.assertEqual(root.findtext("sequence/rate/timebase"), "24")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/start"), "100")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/duration"), "50")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/in"), "25")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/out"), "75")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/file/pathurl"), media_file.as_uri())
        self.assertIsNotNone(root.find("sequence/media/video/format"))
        self.assertIsNotNone(root.find("sequence/media/audio/outputs"))
        clip_ids = [item.get("id") for item in root.findall(".//clipitem")]
        self.assertEqual(len(clip_ids), len(set(clip_ids)))
        self.assertEqual(root.findtext("sequence/media/audio/track/clipitem/sourcetrack/mediatype"), "audio")
        self.assertIn("<!DOCTYPE xmeml>", self.output.read_text())

    def test_builds_project_manifest_without_selecting_a_sequence(self):
        self.source.write_text("<PremiereData/>")
        media_file = Path(self.temp.name) / "scene.mov"
        media_file.touch()
        timebase = 10594584000

        class Time:
            def __init__(self, frames):
                self.frames = frames

            def to_frames(self, _timebase):
                return self.frames

        item = SimpleNamespace(name="Scene 01.mov", media_path=media_file)
        clip = SimpleNamespace(
            name="Scene 01.mov", start=Time(100), end=Time(150),
            in_point=Time(25), out_point=Time(75), project_item=item,
        )
        sequence = SimpleNamespace(
            name="Main", timebase=timebase, frame_size=(1920, 1080),
            video_tracks=[SimpleNamespace(clips=[clip])], audio_tracks=[],
        )
        project = SimpleNamespace(sequences=[sequence])
        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project):
            write_resolve_manifest(self.source, self.output)

        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest["timeline_name"], "Main")
        self.assertEqual(manifest["frame_rate"], "23.976024")
        self.assertEqual(manifest["media_paths"], [str(media_file.resolve())])
        self.assertEqual(manifest["clips"][0]["start_frame"], 25)
        self.assertEqual(manifest["clips"][0]["end_frame"], 75)
        self.assertEqual(manifest["clips"][0]["record_frame"], 100)
        self.assertEqual([timeline["timeline_name"] for timeline in manifest["timelines"]], ["Main"])

    def test_project_manifest_contains_every_top_level_sequence(self):
        self.source.write_text("<PremiereData/>")
        media_file = Path(self.temp.name) / "shared.mov"
        media_file.touch()

        class Time:
            def __init__(self, frames):
                self.frames = frames

            def to_frames(self, _timebase):
                return self.frames

        def make_sequence(name, timebase, record_frame):
            item = SimpleNamespace(name="Shared.mov", media_path=media_file)
            clip = SimpleNamespace(
                name="Shared.mov", start=Time(record_frame), end=Time(record_frame + 12),
                in_point=Time(0), out_point=Time(12), project_item=item,
            )
            return SimpleNamespace(
                name=name, timebase=timebase, frame_size=(1920, 1080),
                video_tracks=[SimpleNamespace(clips=[clip])], audio_tracks=[],
            )

        project = SimpleNamespace(sequences=[
            make_sequence("Main", 10594584000, 0),
            make_sequence("Episode", 10160640000, 48),
        ])
        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project):
            write_resolve_manifest(self.source, self.output)

        manifest = json.loads(self.output.read_text())
        self.assertEqual([timeline["timeline_name"] for timeline in manifest["timelines"]], ["Main", "Episode"])
        self.assertEqual([timeline["clips"][0]["record_frame"] for timeline in manifest["timelines"]], [0, 48])
        self.assertEqual(manifest["media_paths"], [str(media_file.resolve())])

    def test_project_manifest_preserves_nested_media_bins(self):
        self.source.write_text("<PremiereData/>")
        media_file = Path(self.temp.name) / "media.mov"
        media_file.touch()

        class Time:
            def __init__(self, frames):
                self.frames = frames

            def to_frames(self, _timebase):
                return self.frames

        item = SimpleNamespace(name="media.mov", media_path=media_file, node_id="media-1")
        clip = SimpleNamespace(
            name="media.mov", start=Time(0), end=Time(24), in_point=Time(0), out_point=Time(24),
            project_item=item,
        )
        sequence = SimpleNamespace(
            name="Main", timebase=10594584000, frame_size=(1920, 1080),
            video_tracks=[SimpleNamespace(clips=[clip])], audio_tracks=[],
        )
        media = SimpleNamespace(name="media.mov", media_path=media_file, type=1, children=[])
        nested = SimpleNamespace(name="Nested", type=2, children=[media])
        folder = SimpleNamespace(name="Footage", type=2, children=[nested])
        project = SimpleNamespace(sequences=[sequence], root_item=SimpleNamespace(children=[folder]))

        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project):
            write_resolve_manifest(self.source, self.output)

        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest["media_folders"], [{
            "name": "Footage",
            "media": [],
            "folders": [{
                "name": "Nested",
                "media": [{"name": "media.mov", "path": str(media_file.resolve())}],
                "folders": [],
            }],
        }])

    def test_root_media_is_routed_by_path_only_when_not_already_in_a_bin(self):
        bin_item = SimpleNamespace(
            name="Footage", type=2, media_path=None, children=[
                SimpleNamespace(name="same.mov", type=1, media_path=Path("/mnt/Footage/same.mov"), children=[]),
            ],
        )
        duplicate = SimpleNamespace(name="same.mov", type=1, media_path=Path("/mnt/Footage/same.mov"), children=[])
        loose = SimpleNamespace(name="extra.mov", type=1, media_path=Path("/mnt/Footage/extra.mov"), children=[])
        project = SimpleNamespace(root_item=SimpleNamespace(children=[bin_item, duplicate, loose]))

        folders, root_media = _manifest_project_media(project, None)

        self.assertEqual([item["name"] for item in folders[0]["media"]], ["same.mov", "same.mov"])
        self.assertEqual([item["name"] for item in root_media], ["extra.mov"])

    def test_vertical_root_duplicate_stays_in_master(self):
        vertical = SimpleNamespace(name="Вертикальное", type=2, media_path=None, children=[
            SimpleNamespace(
                name="video_2024-06-23_12-03-58.mp4", type=1,
                media_path=Path("/mnt/project/Вертикальное/video_2024-06-23_12-03-58.mp4"), children=[],
            ),
        ])
        duplicate = SimpleNamespace(
            name="video_2024-06-23_12-03-58.mp4", type=1,
            media_path=Path("/mnt/project/Вертикальное/video_2024-06-23_12-03-58.mp4"), children=[],
        )
        project = SimpleNamespace(root_item=SimpleNamespace(children=[vertical, duplicate]))

        folders, root_media = _manifest_project_media(project, None)

        self.assertEqual([item["name"] for item in folders[0]["media"]], ["video_2024-06-23_12-03-58.mp4"])
        self.assertEqual([item["name"] for item in root_media], ["video_2024-06-23_12-03-58.mp4"])

    def test_root_media_bin_inference_ignores_unrelated_windows_volumes(self):
        footage = SimpleNamespace(name="Звуки", type=2, media_path=None, children=[
            SimpleNamespace(name="existing.mp3", type=1, media_path=Path("/mnt/project/Звуки/bell.mp3"), children=[]),
        ])
        project_disk = SimpleNamespace(
            name="bell.mp3", type=1, media_path=Path("/mnt/project/Звуки/bell.mp3"), children=[]
        )
        offline_disk = SimpleNamespace(
            name="offline.mp3", type=1, media_path=Path("/F:/Library/Звуки/offline.mp3"), children=[]
        )
        project = SimpleNamespace(root_item=SimpleNamespace(children=[footage, project_disk, offline_disk]))

        with mock.patch(
            "premiere_to_resolve.converter._media_mount_candidates",
            return_value=[Path("/mnt/project"), Path("/mnt")],
        ):
            folders, root_media = _manifest_project_media(project, Path("/mnt/project/edit.prproj"))

        self.assertEqual([item["name"] for item in folders[0]["media"]], ["existing.mp3", "bell.mp3"])
        self.assertEqual([item["name"] for item in root_media], ["offline.mp3"])

    def test_keeps_clips_without_media_in_the_offline_manifest(self):
        self.source.write_text("<PremiereData/>")

        class Time:
            def __init__(self, frames):
                self.frames = frames

            def to_frames(self, _timebase):
                return self.frames

        clip = SimpleNamespace(
            name="Adjustment Clip", start=Time(0), end=Time(24),
            in_point=Time(0), out_point=Time(24), project_item=None,
        )
        sequence = SimpleNamespace(
            name="Main", timebase=10594584000, frame_size=(1920, 1080),
            video_tracks=[SimpleNamespace(clips=[clip])], audio_tracks=[],
        )
        project = SimpleNamespace(sequences=[sequence])
        with mock.patch("premiere_to_resolve.converter._parse_native_project", return_value=project):
            write_resolve_manifest(self.source, self.output, 0)

        manifest = json.loads(self.output.read_text())
        self.assertEqual(len(manifest["clips"]), 1)
        self.assertIn("Adjustment%20Clip", manifest["clips"][0]["path"])
        self.assertTrue(Path(manifest["clips"][0]["path"]).is_absolute())

    def test_reads_gzip_compressed_premiere_project(self):
        self.source.write_bytes(gzip.compress(SOURCE.encode("utf-8")))
        self.assertEqual(list_sequences(self.source), ["Assembly", "Alt cut"])

    def test_reports_invalid_project_file(self):
        self.source.write_bytes(b"not a Premiere project")
        with self.assertRaisesRegex(ConversionError, "Not a readable Premiere XML project"):
            list_sequences(self.source)

    def test_writes_fcpxml_with_tracks_and_media(self):
        self.assertEqual(convert_project(self.source, self.output), "Assembly")
        root = ET.parse(self.output).getroot()
        self.assertEqual(root.tag, "xmeml")
        self.assertEqual(root.get("version"), "5")
        self.assertEqual(root.findtext("sequence/name"), "Assembly")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/file/pathurl"), "file://localhost/Volumes/Media/Scene%2001.mov")
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/duration"), "100")
        self.assertEqual(root.findtext("sequence/media/audio/track/clipitem/name"), "Scene 01 audio")

    def test_selects_named_sequence(self):
        self.assertEqual(convert_project(self.source, self.output, "Alt cut"), "Alt cut")
        self.assertEqual(ET.parse(self.output).findtext("sequence/rate/timebase"), "24")

    def test_missing_sequence_is_clear(self):
        with self.assertRaisesRegex(ConversionError, "Available: Assembly, Alt cut"):
            convert_project(self.source, self.output, "Missing")

    def test_cli_lists_sequences(self):
        output = StringIO()
        with redirect_stdout(output):
            with mock.patch("sys.argv", ["premiere-to-resolve", str(self.source), "--list-sequences"]):
                self.assertEqual(main(), 0)
        self.assertEqual(output.getvalue().splitlines(), ["Assembly", "Alt cut"])

