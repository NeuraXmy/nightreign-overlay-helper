from __future__ import annotations

import os
from pathlib import Path
import sys

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from src.logger import error, info, warning
from .models import JsonLineBuffer, P2PPeer, P2PStatus, parse_helper_message


HELPER_FILENAME = "NightreignP2PHelper.exe"


def restart_delay_ms(attempt: int) -> int:
    """Return the capped exponential delay for a consecutive helper failure."""
    return min(30_000, 1000 * (2 ** min(max(attempt - 1, 0), 5)))


def resolve_helper_path() -> Path:
    override = os.getenv("NIGHTREIGN_P2P_HELPER_PATH")
    if override:
        return Path(override)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "bin" / HELPER_FILENAME

    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "bin" / HELPER_FILENAME,
        project_root / "native" / "NightreignP2PHelper" / "bin" / "Debug"
        / "net8.0-windows" / "win-x64" / HELPER_FILENAME,
        project_root / "native" / "NightreignP2PHelper" / "bin" / "Release"
        / "net8.0-windows" / "win-x64" / "publish" / HELPER_FILENAME,
    ]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


class P2PService(QObject):
    status_changed = pyqtSignal(object)
    peers_changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.enabled = True
        self.status = P2PStatus("disabled", "联机信息已关闭")
        self.peers: list[P2PPeer] = []
        self._line_buffer = JsonLineBuffer()
        self._stopping = False
        self._restart_attempt = 0

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.started.connect(self._on_started)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        self.restart_timer = QTimer(self)
        self.restart_timer.setSingleShot(True)
        self.restart_timer.timeout.connect(self.start)

    def start(self):
        if self._stopping or not self.enabled:
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return

        helper_path = resolve_helper_path()
        if not helper_path.is_file():
            self._set_status("helper_missing", f"未找到联机组件：{helper_path}")
            return

        args = ["--etw"]
        self._line_buffer = JsonLineBuffer()
        self.process.setProgram(str(helper_path))
        self.process.setArguments(args)
        self.process.setWorkingDirectory(str(helper_path.parent))
        info(f"Starting P2P helper: {helper_path} {' '.join(args)}")
        self.process.start()

    def stop(self):
        self._stopping = True
        self.restart_timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write(b"shutdown\n")
            self.process.waitForBytesWritten(250)
            if not self.process.waitForFinished(2000):
                self.process.terminate()
                if not self.process.waitForFinished(1000):
                    self.process.kill()
                    self.process.waitForFinished(1000)
        self._clear_peers()

    def set_enabled(self, enabled: bool):
        if self.enabled == enabled:
            return
        self.enabled = enabled
        if enabled:
            self._stopping = False
            self._restart_attempt = 0
            self.start()
        else:
            self.restart_timer.stop()
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self.process.write(b"shutdown\n")
                if not self.process.waitForFinished(1500):
                    self.process.terminate()
            self._clear_peers()
            self._set_status("disabled", "联机信息已关闭")

    def _on_started(self):
        self._set_status("helper_started", "联机组件已启动")

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus):
        info(f"P2P helper exited with code {exit_code}")
        self._clear_peers()
        if self._stopping or not self.enabled:
            return
        self._set_status("helper_restarting", "联机组件正在重新启动")
        self._schedule_restart()

    def _on_process_error(self, process_error: QProcess.ProcessError):
        if self._stopping:
            return
        warning(f"P2P helper process error: {process_error.name}")
        self._set_status("helper_error", f"联机组件错误：{process_error.name}")
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._schedule_restart()

    def _schedule_restart(self):
        if self.restart_timer.isActive() or self._stopping or not self.enabled:
            return
        self._restart_attempt += 1
        self.restart_timer.start(restart_delay_ms(self._restart_attempt))

    def _read_stdout(self):
        chunk = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in self._line_buffer.feed(chunk):
            try:
                message_type, value = parse_helper_message(line)
                if message_type == "status":
                    incoming: P2PStatus = value
                    self._set_status(incoming.state, incoming.message, incoming.etw_state)
                else:
                    # A snapshot proves that SteamAPI initialization and one complete
                    # polling cycle succeeded, so the previous crash streak is over.
                    self._restart_attempt = 0
                    self._set_peers(value)
            except Exception as exc:
                warning(f"Ignored invalid P2P helper message: {exc}; line={line[:500]!r}")

    def _read_stderr(self):
        message = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if message:
            error(f"P2P helper: {message}", print_trace=False)

    def _set_status(self, state: str, message: str, etw_state: str | None = None):
        status = P2PStatus(
            state,
            message,
            len(self.peers),
            self.status.etw_state if etw_state is None else etw_state,
        )
        if status == self.status:
            return
        self.status = status
        self.status_changed.emit(status)

    def _set_peers(self, peers: list[P2PPeer]):
        old_order = {peer.steam_id: index for index, peer in enumerate(self.peers)}
        peers.sort(key=lambda peer: (old_order.get(peer.steam_id, len(old_order)), peer.steam_id))
        changed = peers != self.peers
        self.peers = peers
        if changed:
            self.peers_changed.emit(list(peers))
        self._set_status(self.status.state, self.status.message)

    def _clear_peers(self):
        if self.peers:
            self.peers = []
            self.peers_changed.emit([])
        self._set_status(self.status.state, self.status.message)
