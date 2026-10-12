import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock

from premiere_to_resolve.resolve_api_worker import (
    ResolveProjectOpenError,
    export_manifest,
    export_timeline,
)
from premiere_to_resolve.resolve_transfer import installation_from_path, temporary_interchange_directory


class ResolveWorkerTests(unittest.TestCase):
    def test_interchange_files_live_in_cache_not_the_selected_output_folder(self):
        with tempfile.TemporaryDirectory() as cache:
            with unittest.mock.patch.dict("os.environ", {"XDG_CACHE_HOME": cache}):
                with temporary_interchange_directory() as directory:
                    temp_path = Path(directory)
                    self.assertTrue(temp_path.is_relative_to(Path(cache)))
                    self.assertEqual(temp_path.parent.name, "interchange")
                    self.assertTrue(temp_path.is_dir())
                self.assertFalse(temp_path.exists())

    def test_finds_linux_resolve_python_from_install_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "resolve"
            executable = root / "bin" / "resolve"
            python = root / "bin" / "ResolvePython"
            executable.parent.mkdir(parents=True)
            executable.touch()
            python.touch()

            installation = installation_from_path(root)

            self.assertIsNotNone(installation)
            self.assertEqual(installation.python, python)
            self.assertEqual(installation.launch_command, (str(executable),))

    def test_refuses_to_switch_an_open_resolve_project(self):
        project = Mock()
        project.GetName.return_value = "Current cut"
        manager = Mock()
        manager.GetCurrentProject.return_value = project
        resolve = Mock()
        resolve.GetProjectManager.return_value = manager

        with self.assertRaisesRegex(ResolveProjectOpenError, "Current cut") as raised:
            export_timeline(resolve, Path("timeline.xml"), Path("output.drp"))

        self.assertEqual(raised.exception.project_name, "Current cut")
        manager.CreateProject.assert_not_called()

    def test_saves_and_closes_open_project_then_leaves_successful_transfer_open(self):
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / "timeline.xml"
            drp_path = Path(directory) / "edit.drp"
            xml_path.write_text("<xmeml/>")

            current = Mock()
            current.GetName.return_value = "Current cut"
            timeline = Mock()
            timeline.GetTrackCount.side_effect = lambda _kind: 1
            timeline.GetItemListInTrack.return_value = [object()]
            media_pool = Mock()
            media_pool.ImportTimelineFromFile.return_value = timeline
            project = Mock()
            project.GetMediaPool.return_value = media_pool
            manager = Mock()
            manager.GetCurrentProject.return_value = current
            manager.SaveProject.return_value = True
            manager.CreateProject.return_value = project
            manager.ExportProject.side_effect = lambda _name, path, _stills: Path(path).write_bytes(b"DRP") > 0
            manager.LoadProject.return_value = True
            resolve = Mock()
            resolve.GetProjectManager.return_value = manager

            export_timeline(resolve, xml_path, drp_path, allow_project_switch=True)

            manager.SaveProject.assert_has_calls([unittest.mock.call(), unittest.mock.call()])
            manager.CloseProject.assert_called_once_with(current)
            manager.DeleteProject.assert_not_called()
            manager.LoadProject.assert_not_called()
            self.assertEqual(drp_path.read_bytes(), b"DRP")

    def test_imports_exports_and_leaves_the_transferred_project_open(self):
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / "timeline.xml"
            drp_path = Path(directory) / "edit.drp"
            xml_path.write_text("<xmeml/>")

            timeline = Mock()
            timeline.GetTrackCount.side_effect = lambda _kind: 1
            timeline.GetItemListInTrack.return_value = [object()]
            media_pool = Mock()
            media_pool.ImportTimelineFromFile.return_value = timeline
            project = Mock()
            project.GetMediaPool.return_value = media_pool
            manager = Mock()
            manager.GetCurrentProject.return_value = None
            manager.CreateProject.return_value = project
            manager.SaveProject.return_value = True
            manager.ExportProject.side_effect = lambda _name, path, _stills: Path(path).write_bytes(b"DRP") > 0
            manager.CloseProject.return_value = True
            manager.DeleteProject.return_value = True
            resolve = Mock()
            resolve.GetProjectManager.return_value = manager

            export_timeline(resolve, xml_path, drp_path)

            media_pool.ImportTimelineFromFile.assert_called_once_with(str(xml_path))
            manager.ExportProject.assert_called_once_with("edit", str(drp_path), False)
            manager.CloseProject.assert_not_called()
            manager.DeleteProject.assert_not_called()
            self.assertEqual(drp_path.read_bytes(), b"DRP")

    def test_cleans_up_after_import_failure(self):
        project = Mock()
        project.GetMediaPool.return_value.ImportTimelineFromFile.return_value = None
        current = Mock()
        current.GetName.return_value = "Current cut"
        manager = Mock()
        manager.GetCurrentProject.return_value = current
        manager.SaveProject.return_value = True
        manager.CreateProject.return_value = project
        manager.CloseProject.return_value = True
        manager.LoadProject.return_value = True
        resolve = Mock()
        resolve.GetProjectManager.return_value = manager

        with self.assertRaisesRegex(RuntimeError, "не смог импортировать"):
            export_timeline(resolve, Path("timeline.xml"), Path("edit.drp"), allow_project_switch=True)

        manager.CloseProject.assert_has_calls([unittest.mock.call(current), unittest.mock.call(project)])
        manager.DeleteProject.assert_called_once_with("edit")
        manager.LoadProject.assert_called_once_with("Current cut")

    def test_rejects_empty_import_instead_of_exporting_a_blank_timeline(self):
        timeline = Mock()
        timeline.GetTrackCount.return_value = 1
        timeline.GetItemListInTrack.return_value = []
        project = Mock()
        project.GetMediaPool.return_value.ImportTimelineFromFile.return_value = timeline
        manager = Mock()
        manager.GetCurrentProject.return_value = None
        manager.CreateProject.return_value = project
        manager.CloseProject.return_value = True
        manager.DeleteProject.return_value = True
        resolve = Mock()
        resolve.GetProjectManager.return_value = manager

        with self.assertRaisesRegex(RuntimeError, "не импортировал ни одного клипа"):
            export_timeline(resolve, Path("timeline.xml"), Path("edit.drp"))

        manager.ExportProject.assert_not_called()
        manager.DeleteProject.assert_called_once_with("edit")

    def test_assembles_manifest_clips_through_resolve_api_and_exports_drp(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            media_path = folder / "source.mov"
            media_path.touch()
            manifest_path = folder / "timeline.json"
            manifest_path.write_text(json.dumps({
                "timeline_name": "Assembly",
                "frame_rate": "23.976",
                "media_paths": [str(media_path)],
                "clips": [{
                    "path": str(media_path), "start_frame": 10, "end_frame": 20,
                    "record_frame": 42, "media_type": 1, "track_index": 1,
                }],
            }))
            drp_path = folder / "edit.drp"
            item = Mock()
            item.GetClipProperty.return_value = {
                "Clip Name": media_path.name,
                "Clip Directory": str(media_path.parent),
            }
            timeline = Mock()
            timeline.GetStartFrame.return_value = 86400
            timeline.GetTrackCount.return_value = 1
            timeline.GetItemListInTrack.return_value = [object()]
            pool = Mock()
            pool.ImportMedia.return_value = [item]
            pool.CreateEmptyTimeline.return_value = timeline
            pool.AppendToTimeline.return_value = [object()]
            project = Mock()
            project.GetMediaPool.return_value = pool
            manager = Mock()
            manager.GetCurrentProject.return_value = None
            manager.CreateProject.return_value = project
            manager.SaveProject.return_value = True
            manager.ExportProject.side_effect = lambda _name, path, _stills: Path(path).write_bytes(b"DRP") > 0
            resolve = Mock()
            resolve.GetProjectManager.return_value = manager

            warnings = export_manifest(resolve, manifest_path, drp_path)

            self.assertEqual(warnings, [])
            project.SetSetting.assert_called_once_with("timelineFrameRate", "23.976")
            pool.ImportMedia.assert_called_once_with([str(media_path)])
            pool.CreateEmptyTimeline.assert_called_once_with("Assembly")
            placement = pool.AppendToTimeline.call_args.args[0][0]
            self.assertEqual(placement["mediaPoolItem"], item)
            self.assertEqual(placement["recordFrame"], 86442)
            manager.ExportProject.assert_called_once_with("edit", str(drp_path), False)
            self.assertEqual(drp_path.read_bytes(), b"DRP")


if __name__ == "__main__":
    unittest.main()
