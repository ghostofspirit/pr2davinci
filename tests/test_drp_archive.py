import tempfile
import unittest
import zipfile
from pathlib import Path

from premiere_to_resolve.drp_archive import DrpArchiveError, inspect_drp_archive
from premiere_to_resolve.offline_media import repoint_drp_media


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

    def test_repoints_proxy_paths_in_media_pool_blob_and_timeline_xml(self):
        proxy = Path(self.temp.name) / "media" / "proxy-001.mp4"
        target = Path(self.temp.name) / "footage" / "Кадр.mp4"

        def varint(value):
            result = bytearray()
            while value > 0x7F:
                result.append((value & 0x7F) | 0x80)
                value >>= 7
            result.append(value)
            return bytes(result)

        payload = b"\x0a" + varint(len(str(proxy.parent).encode())) + str(proxy.parent).encode()
        payload += b"\x12" + varint(len(proxy.name.encode())) + proxy.name.encode()
        blob = b"\x00\x00\x00\x00" + len(payload).to_bytes(4, "big") + payload
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("project.xml", "<Project/>")
            archive.writestr(
                "MediaPool/Master/MpFolder.xml",
                f'<Sm2MpFolder><Sm2MpVideoClip><Name>{proxy.name}</Name><MediaClip>{blob.hex()}</MediaClip></Sm2MpVideoClip></Sm2MpFolder>',
            )
            archive.writestr(
                "SeqContainer/timeline.xml",
                f"<Sm2SequenceContainer><MediaFilePath>{proxy}</MediaFilePath></Sm2SequenceContainer>",
            )

        changed = repoint_drp_media(self.path, {str(proxy): str(target)})

        self.assertGreater(changed[str(proxy)], 0)
        with zipfile.ZipFile(self.path) as archive:
            media_xml = archive.read("MediaPool/Master/MpFolder.xml").decode()
            timeline_xml = archive.read("SeqContainer/timeline.xml").decode()
        self.assertIn(target.name, media_xml)
        self.assertIn(str(target), timeline_xml)
        found = bytes.fromhex(media_xml.split("<MediaClip>", 1)[1].split("</MediaClip>", 1)[0])
        self.assertIn(str(target.parent).encode(), found)
        self.assertIn(target.name.encode(), found)


if __name__ == "__main__":
    unittest.main()
