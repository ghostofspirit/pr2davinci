from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


class ResolveTransferError(RuntimeError):
    pass


class ResolveProjectSwitchRequired(ResolveTransferError):
    def __init__(self, project_name: str):
        self.project_name = project_name
        super().__init__(project_name)


def temporary_interchange_directory() -> tempfile.TemporaryDirectory:
    """Create handoff files in app-private cache, never in a portal-backed folder."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pr2davinci" / "interchange"
    cache.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="transfer-", dir=cache)


@dataclass(frozen=True)
class ResolveInstallation:
    launch_command: tuple[str, ...]
    python: Path


def _host_file_exists(path: Path) -> bool:
    if path.is_file():
        return True
    if not os.environ.get("FLATPAK_ID"):
        return False
    try:
        result = subprocess.run(
            ["flatpak-spawn", "--host", "test", "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _installation_candidates(path: Path) -> list[Path]:
    path = path.expanduser()
    candidates = [path]
    if _host_file_exists(path):
        candidates.extend([path.parent, path.parent.parent])
    app_index = next((i for i, part in enumerate(path.parts) if part.endswith(".app")), None)
    if app_index is not None:
        candidates.append(Path(*path.parts[: app_index + 1]))
    return list(dict.fromkeys(candidates))


def installation_from_path(path_text: str | Path) -> ResolveInstallation | None:
    """Resolve an installation folder, app bundle, or executable to its API runtime."""
    path = Path(path_text).expanduser()
    for candidate in _installation_candidates(path):
        if sys.platform == "darwin":
            app = candidate if candidate.suffix == ".app" else None
            contents = app / "Contents" if app else candidate
            resolve_python = contents / "Applications" / "ResolvePython"
            executable = contents / "MacOS" / "Resolve"
            launch = ("open", "-a", str(app)) if app else (str(executable),)
        elif os.name == "nt":
            root = candidate.parent if candidate.is_file() else candidate
            resolve_python = root / "ResolvePython" / "ResolvePython.exe"
            executable = root / "Resolve.exe"
            launch = (str(executable),)
        else:
            root = candidate.parent if candidate.name == "bin" else candidate
            resolve_python = root / "bin" / "ResolvePython"
            executable = root / "bin" / "resolve"
            launch = (str(executable),)
        if _host_file_exists(resolve_python) and (
            _host_file_exists(executable) or (sys.platform == "darwin" and launch[0] == "open")
        ):
            return ResolveInstallation(launch, resolve_python)
    return None


def find_resolve_installation() -> ResolveInstallation | None:
    if sys.platform == "darwin":
        paths = [Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")]
    elif os.name == "nt":
        paths = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Blackmagic Design" / "DaVinci Resolve",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Blackmagic Design" / "DaVinci Resolve",
        ]
    else:
        paths = [Path("/opt/resolve")]
    return next((installation for path in paths if (installation := installation_from_path(path))), None)


def _worker_path() -> Path:
    return Path(__file__).resolve().parent / "resolve_api_worker.py"


def _available_drp_path(path: Path) -> Path:
    """Keep existing exports safe while making retries require no renaming."""
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def _worker_command(installation: ResolveInstallation, args: list[str]) -> list[str]:
    worker = _worker_path()
    if os.environ.get("FLATPAK_ID"):
        host_worker = Path.home() / ".cache" / "pr2davinci" / "resolve_api_worker.py"
        host_worker.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(worker, host_worker)
        return ["flatpak-spawn", "--host", str(installation.python), str(host_worker), *args]
    return [str(installation.python), str(worker), *args]


def _launch_resolve(installation: ResolveInstallation) -> None:
    command = list(installation.launch_command)
    if os.environ.get("FLATPAK_ID"):
        command = ["flatpak-spawn", "--host", *command]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run_worker(installation: ResolveInstallation, args: list[str], timeout: float = 12) -> dict:
    command = _worker_command(installation, args)
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise ResolveTransferError(f"Не найден интерпретатор ResolvePython или flatpak-spawn: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise ResolveTransferError("Resolve не ответил на запрос автоматизации вовремя.") from error
    lines = [
        line.removeprefix("PR2DAVINCI_RESULT=")
        for line in result.stdout.splitlines()
        if line.startswith("PR2DAVINCI_RESULT=")
    ]
    if not lines:
        details = result.stderr.strip() or f"ResolvePython завершился с кодом {result.returncode}."
        raise ResolveTransferError(details)
    try:
        response = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ResolveTransferError(result.stderr.strip() or "Не удалось прочитать ответ Resolve.") from error
    return response


def transfer_xml_to_resolve(
    xml_path: Path,
    drp_path: Path,
    installation: ResolveInstallation,
    on_log=None,
    allow_project_switch: bool = False,
) -> Path:
    """Import an interchange timeline and export it as a DRP via Resolve Studio."""
    return _transfer_file_to_resolve(
        xml_path, drp_path, installation, "--xml", on_log, allow_project_switch
    )


def transfer_manifest_to_resolve(
    manifest_path: Path,
    drp_path: Path,
    installation: ResolveInstallation,
    on_log=None,
    allow_project_switch: bool = False,
) -> Path:
    """Assemble a Premiere sequence with Resolve's native scripting API."""
    return _transfer_file_to_resolve(
        manifest_path, drp_path, installation, "--manifest", on_log, allow_project_switch
    )


def _transfer_file_to_resolve(
    payload_path: Path,
    drp_path: Path,
    installation: ResolveInstallation,
    input_flag: str,
    on_log,
    allow_project_switch: bool,
) -> Path:
    drp_path = _available_drp_path(drp_path)
    staging_directory: Path | None = None
    worker_drp_path = drp_path
    check = _run_worker(installation, ["--check"])
    if not check.get("connected"):
        if on_log:
            on_log("log_launch_resolve", {})
        try:
            _launch_resolve(installation)
        except OSError as error:
            raise ResolveTransferError(f"Не удалось запустить DaVinci Resolve: {error}") from error
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            time.sleep(2)
            check = _run_worker(installation, ["--check"])
            if check.get("connected"):
                break
        else:
            raise ResolveTransferError(
                "Не удалось подключиться к Resolve Studio. Проверьте, что это Studio-версия, "
                "а в Preferences → System → General разрешено внешнее scripting (Local)."
            )
    if on_log:
        on_log("log_transfer_resolve", {})
    if os.environ.get("FLATPAK_ID"):
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pr2davinci" / "exports"
        cache.mkdir(parents=True, exist_ok=True)
        staging_directory = Path(tempfile.mkdtemp(prefix="export-", dir=cache))
        worker_drp_path = staging_directory / drp_path.name
    args = [input_flag, str(payload_path), "--drp", str(worker_drp_path)]
    if allow_project_switch:
        args.append("--switch-open-project")
    try:
        result = _run_worker(installation, args, timeout=180)
    except Exception:
        if staging_directory is not None and not worker_drp_path.exists():
            shutil.rmtree(staging_directory)
        raise
    if result.get("requires_confirmation"):
        if staging_directory is not None:
            shutil.rmtree(staging_directory)
        raise ResolveProjectSwitchRequired(result.get("project_name") or "Resolve")
    if not result.get("ok"):
        if staging_directory is not None:
            shutil.rmtree(staging_directory)
        raise ResolveTransferError(result.get("error", "Resolve не смог экспортировать проект в DRP."))
    if on_log:
        for warning in result.get("warnings", []):
            on_log("log_warning", {"warning": warning})
    if not worker_drp_path.is_file():
        if staging_directory is not None:
            shutil.rmtree(staging_directory)
        raise ResolveTransferError("Resolve сообщил об успехе, но DRP-файл не появился.")
    if staging_directory is not None:
        try:
            shutil.copy2(worker_drp_path, drp_path)
        except OSError as error:
            raise ResolveTransferError(
                f"Resolve создал DRP, но не удалось скопировать его в выбранную папку: {error}. "
                f"Временная копия сохранена: {worker_drp_path}"
            ) from error
        shutil.rmtree(staging_directory)
    if not drp_path.is_file():
        raise ResolveTransferError("DRP был создан, но не появился в выбранной папке.")
    return drp_path
