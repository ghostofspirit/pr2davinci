from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from premiere_to_resolve.offline_media import create_offline_proxies, proxy_path_for
except ImportError:  # ResolvePython receives this worker plus the sibling helper file.
    from offline_media import create_offline_proxies, proxy_path_for


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
        if project is not None:
            # The DRP is the deliverable. Do not leave the generated staging
            # project active (or clutter Resolve's project library) after export.
            manager.CloseProject(project)
            manager.DeleteProject(project_name)
        if restore_project_name is not None and not manager.LoadProject(restore_project_name):
            raise RuntimeError(f"Не удалось повторно открыть проект Resolve «{restore_project_name}» после неудачной передачи.")
    if not exported:
        raise RuntimeError("Экспорт DRP не завершился.")


def export_manifest(
    resolve,
    manifest_path: Path,
    drp_path: Path,
    allow_project_switch: bool = False,
    proxy_dir: Path | None = None,
) -> list[str]:
    """Build every project sequence as a timeline in one Resolve project."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        media_paths = manifest["media_paths"]
        timelines = manifest.get("timelines") or [{
            "timeline_name": manifest["timeline_name"],
            "frame_rate": manifest["frame_rate"],
            "clips": manifest["clips"],
        }]
        timelines = [{
            "timeline_name": str(timeline["timeline_name"]),
            "frame_rate": str(timeline["frame_rate"]),
            "width": int(timeline.get("width", 1920)),
            "height": int(timeline.get("height", 1080)),
            "clips": timeline["clips"],
        } for timeline in timelines]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Не удалось прочитать описание секвенций: {error}") from error
    all_clips = [clip for timeline in timelines for clip in timeline["clips"]]
    if not timelines or not all_clips or not media_paths:
        raise RuntimeError("В проекте нет секвенций с клипами для сборки DRP.")
    frame_rate = timelines[0]["frame_rate"]

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
    proxies_by_source: dict[str, str] = {}
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
        if proxy_dir is not None:
            max_source_frame = max(int(clip["end_frame"]) for clip in all_clips)
            proxies_by_source = create_offline_proxies(
                [str(path) for path in media_paths], proxy_dir, max_source_frame, frame_rate
            )
            import_paths = list(proxies_by_source.values())
        else:
            import_paths = [str(path) for path in media_paths]
        imported = pool.ImportMedia(import_paths) or []
        media_by_path: dict[str, object] = {}
        for item in imported:
            properties = item.GetClipProperty() or {}
            clip_name = properties.get("Clip Name", "")
            clip_directory = properties.get("Clip Directory", "")
            if clip_name and clip_directory:
                media_by_path[os.path.normcase(os.path.realpath(os.path.join(clip_directory, clip_name)))] = item

        total_appended = 0
        unavailable = 0
        for timeline_spec in timelines:
            timeline_name = timeline_spec["timeline_name"]
            clips = timeline_spec["clips"]
            timeline = pool.CreateEmptyTimeline(timeline_name)
            if timeline is None:
                raise RuntimeError(f"Resolve не смог создать секвенцию «{timeline_name}».")
            timeline_settings = {
                "timelineFrameRate": timeline_spec["frame_rate"],
                "timelineResolutionWidth": str(timeline_spec["width"]),
                "timelineResolutionHeight": str(timeline_spec["height"]),
            }
            if hasattr(timeline, "SetSettings"):
                settings_ok = timeline.SetSettings(timeline_settings)
            else:
                settings_ok = all(
                    timeline.SetSetting(key, value)
                    for key, value in timeline_settings.items()
                )
            if not settings_ok:
                raise RuntimeError(f"Resolve не принял настройки секвенции «{timeline_name}».")

            # Resolve starts timelines at 01:00:00:00; Premiere positions are relative to frame 0.
            timeline_start_frame = int(timeline.GetStartFrame() or 0)
            for media_type, track_type in ((1, "video"), (2, "audio")):
                required = max((int(clip["track_index"]) for clip in clips if int(clip["media_type"]) == media_type), default=0)
                while int(timeline.GetTrackCount(track_type) or 0) < required:
                    if not timeline.AddTrack(track_type):
                        raise RuntimeError(f"Resolve не смог создать дорожку {track_type} {required} в «{timeline_name}».")

            placements = []
            for clip in clips:
                source_path = str(clip["path"])
                import_path = proxies_by_source.get(source_path, source_path)
                key = os.path.normcase(os.path.realpath(import_path))
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
            if placements:
                appended = pool.AppendToTimeline(placements) or []
                if len(appended) != len(placements) or _timeline_item_count(timeline) == 0:
                    raise RuntimeError(
                        f"Resolve добавил не все клипы в секвенцию «{timeline_name}»: "
                        f"{len(appended)} из {len(placements)}. DRP не сохранён."
                    )
                total_appended += len(appended)
        if total_appended == 0:
            raise RuntimeError("Resolve не добавил клипы ни в одну секвенцию.")
        if unavailable:
            raise RuntimeError(f"Resolve не нашёл медиа для {unavailable} клипов; DRP не сохранён.")
        if proxies_by_source:
            warnings.append(
                f"Созданы офлайн-ссылки для {len(proxies_by_source)} исходников; клипы можно relink в Resolve."
            )
        if not manager.SaveProject():
            raise RuntimeError("Resolve не смог сохранить собранный проект.")
        if not manager.ExportProject(project_name, str(drp_path), False):
            raise RuntimeError("Resolve не смог экспортировать проект в DRP.")
        exported = True
    finally:
        if project is not None:
            manager.CloseProject(project)
            manager.DeleteProject(project_name)
        if restore_project_name is not None and not manager.LoadProject(restore_project_name):
            raise RuntimeError(f"Не удалось повторно открыть проект Resolve «{restore_project_name}» после создания DRP.")
    if not exported:
        raise RuntimeError("Экспорт DRP не завершился.")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--xml", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--drp", type=Path)
    parser.add_argument("--proxy-dir", type=Path)
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
            warnings = export_manifest(
                resolve, args.manifest, args.drp, args.switch_open_project, args.proxy_dir
            )
            media_mappings = []
            if args.proxy_dir is not None:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                media_mappings = [
                    {"from": str(proxy_path_for(source, args.proxy_dir)), "to": str(source)}
                    for source in dict.fromkeys(manifest["media_paths"])
                ]
            return _emit({"ok": True, "warnings": warnings, "media_mappings": media_mappings})
        else:
            export_timeline(resolve, args.xml, args.drp, args.switch_open_project)
        return _emit({"ok": True})
    except ResolveProjectOpenError as error:
        return _emit({"ok": False, "requires_confirmation": True, "project_name": error.project_name}, 1)
    except Exception as error:
        return _emit({"ok": False, "error": str(error)}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
