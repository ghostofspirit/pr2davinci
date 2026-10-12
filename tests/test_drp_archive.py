import tempfile
import unittest
import zipfile
from pathlib import Path

from premiere_to_resolve.drp_archive import DrpArchiveError, inspect_drp_archive


def write_project(path: Path, sequence: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.xml", "<Project/>")
        archive.writestr(
            "MediaPool/Master/MpFolder.xml",
            '<Sm2MpFolder><Sm2MpVideoClip DbId="media-1"/></Sm2MpFolder>',
        )
        archive.writestr("SeqContainer/timeline-1.xml", sequence)


class DrpArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "project.drp"

    def tearDown(self):
        self.temp.cleanup()

    def test_inspects_populated_timeline_and_resolved_media(self):
        write_project(
            self.path,
            """<Sm2SequenceContainer>
              <VideoTrackVec><Element><Sm2TiTrack><Items><Element>
                <Sm2TiVideoClip><MediaRef>media-1</MediaRef></Sm2TiVideoClip>
              </Element></Items></Sm2TiTrack></Element></VideoTrackVec>
              <AudioTrackVec><Element><Sm2TiTrack><Items><Element>
                <Sm2TiAudioClip><MediaRef>media-1</MediaRef></Sm2TiAudioClip>
              </Element></Items></Sm2TiTrack></Element></AudioTrackVec>
            </Sm2SequenceContainer>""",
        )

        result = inspect_drp_archive(self.path)

        self.assertEqual(result.timeline_count, 1)
        self.assertEqual(result.video_clip_count, 1)
        self.assertEqual(result.audio_clip_count, 1)
        self.assertEqual(result.clip_count, 2)
        self.assertEqual(result.media_item_count, 1)
        self.assertEqual(result.unresolved_media_references, 0)

    def test_rejects_empty_timeline(self):
        write_project(self.path, "<Sm2SequenceContainer/>")
        with self.assertRaisesRegex(DrpArchiveError, "таймлайн без клипов"):
            inspect_drp_archive(self.path)

    def test_reports_unresolved_media_reference(self):
        write_project(
            self.path,
            "<Sm2SequenceContainer><Sm2TiVideoClip><MediaRef>missing</MediaRef></Sm2TiVideoClip></Sm2SequenceContainer>",
        )
        result = inspect_drp_archive(self.path)
        self.assertEqual(result.unresolved_media_references, 1)

    def test_rejects_non_drp_file(self):
        self.path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(DrpArchiveError, "Не удалось прочитать DRP"):
            inspect_drp_archive(self.path)


if __name__ == "__main__":
    unittest.main()
