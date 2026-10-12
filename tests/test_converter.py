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
    convert_project,
    list_sequence_entries,
    list_sequences,
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

    def test_builds_direct_resolve_manifest_for_native_sequence(self):
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
            write_resolve_manifest(self.source, self.output, 0)

        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest["timeline_name"], "Main")
        self.assertEqual(manifest["frame_rate"], "23.976")
        self.assertEqual(manifest["media_paths"], [str(media_file.resolve())])
        self.assertEqual(manifest["clips"][0]["start_frame"], 25)
        self.assertEqual(manifest["clips"][0]["end_frame"], 75)
        self.assertEqual(manifest["clips"][0]["record_frame"], 100)

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

