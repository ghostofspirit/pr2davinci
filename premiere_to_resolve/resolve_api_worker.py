from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


def _emit(payload: dict, status: int = 0) -> int:
    print("PR2DAVINCI_RESULT=" + json.dumps(payload))
    return status


def _connect():
    try:
        import DaVinciResolveScript as dvr_script
    except Exception as error:
        return None, f"Resolve scripting API недоступен: {error}"
    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        return None, "Resolve Studio не отвечает на внешние scripting-запросы."
    return resolve, None


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w .()-]+", "_", value, flags=re.UNICODE).strip(" .")
    return (cleaned or "Premiere Transfer")[:100]


class ResolveProjectOpenError(RuntimeError):
    def __init__(self, project_name: str):
        self.project_name = project_name
        super().__init__(f"В Resolve открыт проект «{project_name}».")


def _timeline_item_count(timeline) -> int:
    total = 0
    for track_type in ("video", "audio"):
        for index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            total += len(timeline.GetItemListInTrack(track_type, index) or [])
    return total


def export_timeline(resolve, xml_path: Path, drp_path: Path, allow_project_switch: bool = False) -> None:
    manager = resolve.GetProjectManager()
    current = manager.GetCurrentProject()
    restore_project_name = None
    if current is not None:
        current_name = current.GetName() if hasattr(current, "GetName") else "(unknown)"
        if not allow_project_switch:
            raise ResolveProjectOpenError(current_name)
        restore_project_name = current_name
        if not manager.SaveProject():
            raise RuntimeError(f"Не удалось сохранить открытый проект Resolve «{current_name}».")
        if not manager.CloseProject(current):
            raise RuntimeError(f"Не удалось временно закрыть проект Resolve «{current_name}».")

    base_name = _safe_name(drp_path.stem)
    project = None
    project_name = None
    exported = False
    try:
        for suffix in range(1, 100):
            project_name = base_name if suffix == 1 else f"{base_name} ({suffix})"
            project = manager.CreateProject(project_name)
            if project is not None:
                break
        if project is None:
            raise RuntimeError("Не удалось создать временный проект Resolve.")
        timeline = project.GetMediaPool().ImportTimelineFromFile(str(xml_path))
        if timeline is None:
            raise RuntimeError("Resolve не смог импортировать XML-таймлайн.")
        if _timeline_item_count(timeline) == 0:
            raise RuntimeError(
                "Resolve создал таймлайн, но не импортировал ни одного клипа. "
                "DRP не сохранён: проверьте XML и повторите передачу."
            )
        if not manager.SaveProject():
            raise RuntimeError("Resolve не смог сохранить промежуточный проект.")
        if not manager.ExportProject(project_name, str(drp_path), False):
            raise RuntimeError("Resolve не смог экспортировать проект в DRP.")
        exported = True
    finally:
        if project is not None and not exported:
            manager.CloseProject(project)
            manager.DeleteProject(project_name)
        if restore_project_name is not None and not exported and not manager.LoadProject(restore_project_name):
            raise RuntimeError(f"Не удалось повторно открыть проект Resolve «{restore_project_name}» после неудачной передачи.")
    if not exported:
        raise RuntimeError("Экспорт DRP не завершился.")


def export_manifest(resolve, manifest_path: Path, drp_path: Path, allow_project_switch: bool = False) -> list[str]:
    """Build a timeline from native clip placements through Resolve's API."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        clips = manifest["clips"]
        media_paths = manifest["media_paths"]
        timeline_name = str(manifest["timeline_name"])
        frame_rate = str(manifest["frame_rate"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Не удалось прочитать описание таймлайна: {error}") from error
    if not clips or not media_paths:
        raise RuntimeError("В описании секвенции нет доступных медиаклипов.")

    manager = resolve.GetProjectManager()
    current = manager.GetCurrentProject()
    restore_project_name = None
    if current is not None:
        current_name = current.GetName() if hasattr(current, "GetName") else "(unknown)"
        if not allow_project_switch:
            raise ResolveProjectOpenError(current_name)
        restore_project_name = current_name
        if not manager.SaveProject():
            raise RuntimeError(f"Не удалось сохранить открытый проект Resolve «{current_name}».")
        if not manager.CloseProject(current):
            raise RuntimeError(f"Не удалось временно закрыть проект Resolve «{current_name}».")

    project_name = _safe_name(drp_path.stem)
    project = None
    exported = False
    warnings: list[str] = []
    try:
        for suffix in range(1, 100):
            candidate = project_name if suffix == 1 else f"{project_name} ({suffix})"
            project = manager.CreateProject(candidate)
            if project is not None:
                project_name = candidate
                break
        if project is None:
            raise RuntimeError("Не удалось создать временный проект Resolve.")
        if not project.SetSetting("timelineFrameRate", frame_rate):
            raise RuntimeError(f"Resolve не принял частоту кадров секвенции {frame_rate} fps.")

        pool = project.GetMediaPool()
        imported = pool.ImportMedia(media_paths) or []
        media_by_path: dict[str, object] = {}
        for item in imported:
            properties = item.GetClipProperty() or {}
            clip_name = properties.get("Clip Name", "")
            clip_directory = properties.get("Clip Directory", "")
            if clip_name and clip_directory:
                media_by_path[os.path.normcase(os.path.realpath(os.path.join(clip_directory, clip_name)))] = item

        timeline = pool.CreateEmptyTimeline(timeline_name)
        if timeline is None:
            raise RuntimeError("Resolve не смог создать таймлайн.")
        # Resolve timelines start at 01:00:00:00 by default. AppendToTimeline
        # interprets recordFrame as an absolute timeline frame, while Premiere
        # positions in the manifest are relative to sequence start (frame 0).
        # Without this offset, clips are placed before Resolve's visible start:
        # track counters increase, but the timeline appears empty.
        timeline_start_frame = int(timeline.GetStartFrame() or 0)
        for media_type, track_type in ((1, "video"), (2, "audio")):
            required = max((int(clip["track_index"]) for clip in clips if int(clip["media_type"]) == media_type), default=0)
            while int(timeline.GetTrackCount(track_type) or 0) < required:
                if not timeline.AddTrack(track_type):
                    raise RuntimeError(f"Resolve не смог создать дорожку {track_type} {required}.")

        placements = []
        unavailable = 0
        for clip in clips:
            key = os.path.normcase(os.path.realpath(str(clip["path"])))
            media_item = media_by_path.get(key)
            if media_item is None:
                unavailable += 1
                continue
            placements.append({
                "mediaPoolItem": media_item,
                "startFrame": int(clip["start_frame"]),
                "endFrame": int(clip["end_frame"]),
                "mediaType": int(clip["media_type"]),
                "trackIndex": int(clip["track_index"]),
                "recordFrame": timeline_start_frame + int(clip["record_frame"]),
            })
        if not placements:
            raise RuntimeError("Resolve не импортировал ни одного доступного медиаклипа.")
        appended = pool.AppendToTimeline(placements) or []
        if not appended or _timeline_item_count(timeline) == 0:
            raise RuntimeError("Resolve не добавил клипы на таймлайн.")
        if unavailable:
            warnings.append(f"Resolve пропустил недоступные медиаклипы: {unavailable}.")
        if len(appended) < len(placements):
            warnings.append(f"Resolve добавил {len(appended)} из {len(placements)} клипов.")
        if not manager.SaveProject():
            raise RuntimeError("Resolve не смог сохранить собранный проект.")
        if not manager.ExportProject(project_name, str(drp_path), False):
            raise RuntimeError("Resolve не смог экспортировать проект в DRP.")
        exported = True
    finally:
        if project is not None and not exported:
            manager.CloseProject(project)
            manager.DeleteProject(project_name)
        if restore_project_name is not None and not exported and not manager.LoadProject(restore_project_name):
            raise RuntimeError(f"Не удалось повторно открыть проект Resolve «{restore_project_name}» после неудачной передачи.")
    if not exported:
        raise RuntimeError("Экспорт DRP не завершился.")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--xml", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--drp", type=Path)
    parser.add_argument("--switch-open-project", action="store_true")
    args = parser.parse_args()
    try:
        resolve, error = _connect()
        if resolve is None:
            return _emit({"connected": False, "error": error}, 2)
        if args.check:
            return _emit({"connected": True, "version": resolve.GetVersionString()})
        if args.drp is None or (args.xml is None and args.manifest is None):
            return _emit({"ok": False, "error": "Не заданы входной XML и выходной DRP."}, 2)
        if args.manifest is not None:
            warnings = export_manifest(resolve, args.manifest, args.drp, args.switch_open_project)
            return _emit({"ok": True, "warnings": warnings})
        else:
            export_timeline(resolve, args.xml, args.drp, args.switch_open_project)
        return _emit({"ok": True})
    except ResolveProjectOpenError as error:
        return _emit({"ok": False, "requires_confirmation": True, "project_name": error.project_name}, 1)
    except Exception as error:
        return _emit({"ok": False, "error": str(error)}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
