import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from premiere_to_resolve.resolve_transfer import (
    ResolveInstallation,
    transfer_xml_to_resolve,
)


class ResolveTransferTests(unittest.TestCase):
    def test_existing_drp_is_preserved_and_retry_uses_next_name(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            xml_path = folder / "timeline.xml"
            xml_path.write_text("<xmeml/>")
            requested = folder / "edit.drp"
            requested.write_bytes(b"keep this export")
            (folder / "edit (2).drp").write_bytes(b"also keep this export")

            def run_worker(_installation, args, **_kwargs):
                if args == ["--check"]:
                    return {"connected": True}
                output = Path(args[args.index("--drp") + 1])
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr("project.xml", "<Project/>")
                    archive.writestr(
                        "MediaPool/Master/MpFolder.xml",
                        '<Sm2MpFolder><Sm2MpVideoClip DbId="media-1"/></Sm2MpFolder>',
                    )
                    archive.writestr(
                        "SeqContainer/timeline.xml",
                        "<Sm2SequenceContainer><Sm2TiVideoClip><MediaRef>media-1</MediaRef></Sm2TiVideoClip></Sm2SequenceContainer>",
                    )
                return {"ok": True}

            with patch("premiere_to_resolve.resolve_transfer._run_worker", side_effect=run_worker), \
                 patch.dict("os.environ", {"FLATPAK_ID": "com.test.App", "XDG_CACHE_HOME": str(folder / "cache")}):
                result = transfer_xml_to_resolve(
                    xml_path,
                    requested,
                    ResolveInstallation(("resolve",), Path("ResolvePython")),
                )

            self.assertEqual(result, folder / "edit (3).drp")
            self.assertEqual(requested.read_bytes(), b"keep this export")
            self.assertEqual((folder / "edit (2).drp").read_bytes(), b"also keep this export")
            with zipfile.ZipFile(result) as archive:
                self.assertIn("SeqContainer/timeline.xml", archive.namelist())

    def test_rejects_success_response_with_empty_drp_and_preserves_existing_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            xml_path = folder / "timeline.xml"
            xml_path.write_text("<xmeml/>")
            requested = folder / "edit.drp"
            requested.write_bytes(b"existing file")

            def run_worker(_installation, args, **_kwargs):
                if args == ["--check"]:
                    return {"connected": True}
                output = Path(args[args.index("--drp") + 1])
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr("project.xml", "<Project/>")
                    archive.writestr("MediaPool/Master/MpFolder.xml", "<Sm2MpFolder/>")
                    archive.writestr("SeqContainer/timeline.xml", "<Sm2SequenceContainer/>")
                return {"ok": True}

            with patch("premiere_to_resolve.resolve_transfer._run_worker", side_effect=run_worker):
                with self.assertRaisesRegex(RuntimeError, "таймлайн без клипов"):
                    transfer_xml_to_resolve(
                        xml_path,
                        requested,
                        ResolveInstallation(("resolve",), Path("ResolvePython")),
                    )

            self.assertEqual(requested.read_bytes(), b"existing file")


if __name__ == "__main__":
    unittest.main()
