"""KDE tray applet + window for the host.

Reuses the exact same `host/runner.py` `HostRunner` and `host/presets.py`
preset list the TUI (`host/ui/`) does — this is meant to be a thin shell
around the same lifecycle, not a reimplementation of it. See TODO/TODO.md's
"host UI" section for why a TUI shipped first (no GUI toolkit was installed
to build/verify one) and this is the planned upgrade now that PySide6 is.

`host/gui/window.py` owns the actual controls (resolution, start/stop, log);
this module owns the one `HostRunner`/background loop thread and the tray
icon, and is the single place that drives start/stop/preset logic — the
window only renders state and emits signals for this to act on.

Run with `python -m host.gui`.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from host.async_loop_thread import AsyncLoopThread
from host.config import HostConfig
from host.displayserver.x11 import X11DisplayServer
from host.gui.window import HostWindow
from host.presets import Preset, build_presets
from host.runner import HostRunner, State, StatusEvent

logger = logging.getLogger(__name__)

_ICON_PATH = str(pathlib.Path(__file__).resolve().parent / "assets" / "icon.png")

# One dot color per state, used for both the tray icon and the window's
# status dot.
_STATE_COLORS = {
    State.IDLE: QColor("#9e9e9e"),
    State.STARTING: QColor("#f5c518"),
    State.WAITING: QColor("#f5c518"),
    State.CONNECTED: QColor("#43a047"),
    State.STOPPING: QColor("#f5c518"),
    State.ERROR: QColor("#e53935"),
}


def _dot_icon(color: QColor) -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    margin = 6
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pixmap)


class _StatusBridge(QObject):
    """Qt auto-connections marshal a cross-thread signal emission onto the
    receiving QObject's own thread automatically — this is what lets
    HostRunner's on_status callback (called from AsyncLoopThread's thread)
    update tray/window UI safely without a manually-polled queue like the
    TUI uses.
    """

    status_changed = Signal(object)
    crashed = Signal(object)
    # Logging handlers (_WindowLogHandler, _TrayLogHandler) run on whatever
    # thread emits the log record — almost always AsyncLoopThread's, not
    # Qt's GUI thread. Touching a QWidget/QSystemTrayIcon directly from
    # there is undefined behavior in Qt; it mostly "worked" during testing
    # until it corrupted QTextEngine's internal state badly enough to abort
    # the whole process. These two signals, like status_changed/crashed
    # above, marshal the actual widget-touching onto the GUI thread via a
    # queued connection instead.
    log_for_window = Signal(str)
    log_for_tray = Signal(str, int)  # message, levelno


class TrayApp:
    def __init__(self) -> None:
        self._presets = build_presets()
        self._selected: Preset = self._presets[0]
        self._state = State.IDLE
        self._detail = ""
        self._runner: HostRunner | None = None
        self._loop_thread = AsyncLoopThread()
        self._quitting = False

        self._bridge = _StatusBridge()
        self._bridge.status_changed.connect(self._handle_status, Qt.ConnectionType.QueuedConnection)
        self._bridge.crashed.connect(self._handle_crash, Qt.ConnectionType.QueuedConnection)

        self._window = HostWindow(self._presets, icon_path=_ICON_PATH)
        self._window.start_requested.connect(self._start)
        self._window.stop_requested.connect(self._stop)
        self._window.preset_selected.connect(self._select_preset)
        self._window.quit_requested.connect(self._quit)
        self._window.show()

        self._tray = QSystemTrayIcon(_dot_icon(_STATE_COLORS[State.IDLE]))
        self._tray.setToolTip("view-dock: idle")
        self._tray.activated.connect(self._on_tray_activated)

        self._menu = QMenu()
        self._status_action = QAction("idle")
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
        self._menu.addSeparator()

        show_window_action = QAction("Show window")
        show_window_action.triggered.connect(self._show_window)
        self._menu.addAction(show_window_action)
        self._menu.addSeparator()

        self._resolution_menu = QMenu("Resolution")
        self._preset_group = QActionGroup(self._resolution_menu)
        self._preset_group.setExclusive(True)
        for preset in self._presets:
            action = QAction(preset.label)
            action.setCheckable(True)
            action.setChecked(preset is self._selected)
            action.triggered.connect(lambda _checked, p=preset: self._select_preset(p))
            self._preset_group.addAction(action)
            self._resolution_menu.addAction(action)
        self._menu.addMenu(self._resolution_menu)
        self._menu.addSeparator()

        self._start_action = QAction("Start")
        self._start_action.triggered.connect(self._start)
        self._menu.addAction(self._start_action)

        self._stop_action = QAction("Stop")
        self._stop_action.triggered.connect(self._stop)
        self._stop_action.setEnabled(False)
        self._menu.addAction(self._stop_action)

        self._menu.addSeparator()
        quit_action = QAction("Quit")
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.show()

        self._bridge.log_for_window.connect(self._window.append_log, Qt.ConnectionType.QueuedConnection)
        self._bridge.log_for_tray.connect(self._show_log_notification, Qt.ConnectionType.QueuedConnection)
        logging.getLogger().addHandler(_TrayLogHandler(self._bridge))
        logging.getLogger().addHandler(_WindowLogHandler(self._bridge))
        logging.getLogger().setLevel(logging.INFO)

    # -- lifecycle -----------------------------------------------------

    def start_background_loop(self) -> None:
        self._loop_thread.start()

    def _on_status(self, event: StatusEvent) -> None:
        # Called from the loop thread; Signal emission marshals it to Qt's.
        self._bridge.status_changed.emit(event)

    def _on_crash(self, exc: BaseException) -> None:
        logger.error("Host session crashed: %s", exc, exc_info=exc)
        self._bridge.crashed.emit(exc)

    def _handle_status(self, event: StatusEvent) -> None:
        self._state = event.state
        self._detail = event.detail
        self._refresh()
        if self._quitting and event.state is State.IDLE:
            self._finish_quit()

    def _handle_crash(self, exc: BaseException) -> None:
        self._runner = None
        self._state = State.ERROR
        self._detail = str(exc)
        self._refresh()
        self._tray.showMessage("view-dock host crashed", str(exc), QSystemTrayIcon.MessageIcon.Critical)
        # A crash mid-quit (e.g. during cleanup) would otherwise never reach
        # the IDLE check in _handle_status(), leaving _finish_quit() stuck
        # waiting for a state transition that's never coming.
        if self._quitting:
            self._finish_quit()

    def _refresh(self) -> None:
        label = self._state.value + (f": {self._detail}" if self._detail else "")
        self._tray.setToolTip(f"view-dock: {label}")
        self._tray.setIcon(_dot_icon(_STATE_COLORS[self._state]))
        self._status_action.setText(label)
        self._window.apply_status(self._state, self._detail, _STATE_COLORS[self._state])

        editable = self._state in (State.IDLE, State.ERROR)
        self._resolution_menu.setEnabled(editable)
        self._start_action.setEnabled(editable)
        self._stop_action.setEnabled(not editable)

    # -- window/tray glue --------------------------------------------------

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self._window.isVisible():
            self._window.hide()
        else:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    # -- actions ---------------------------------------------------------

    def _select_preset(self, preset: Preset) -> None:
        self._selected = preset

    def _start(self) -> None:
        if self._state not in (State.IDLE, State.ERROR):
            return

        display_config = self._selected.display if self._selected.display is not None else HostConfig.default().display

        if X11DisplayServer.find_available_output() is None:
            candidates = X11DisplayServer.list_disconnected_outputs()
            hint = f" Candidates: {', '.join(candidates)}." if candidates else ""
            self._tray.showMessage(
                "No spare output",
                f"Run scripts/force-connector.sh <connector> first (see host/README.md).{hint}",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        self._runner = HostRunner(display_config, on_status=self._on_status)
        self._state = State.STARTING
        self._detail = self._selected.label
        self._refresh()
        self._loop_thread.submit(self._runner.run(), on_error=self._on_crash)

    def _stop(self) -> None:
        if self._runner is None:
            return
        self._loop_thread.call_soon(self._runner.request_stop)

    def _quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        if self._runner is None:
            self._finish_quit()
            return
        # Stopping the loop thread immediately after requesting the runner
        # stop (the original approach) raced its cleanup: request_stop()
        # only sets an asyncio.Event — the runner's actual teardown
        # (destroying the virtual display, disconnecting the transport, e.g.
        # terminating iproxy) runs afterward as a consequence, and needs the
        # loop to keep running for that to happen. Stopping the loop in the
        # same breath could cut it off mid-cleanup, the same way a `kill
        # -TERM` on the whole process did earlier. Waiting for the IDLE
        # status (see _handle_status/_handle_crash) instead means the loop
        # only actually stops once cleanup has genuinely finished.
        self._loop_thread.call_soon(self._runner.request_stop)

    def _finish_quit(self) -> None:
        self._loop_thread.stop()
        QApplication.instance().quit()

    def _show_log_notification(self, message: str, levelno: int) -> None:
        icon = QSystemTrayIcon.MessageIcon.Critical if levelno >= logging.ERROR else QSystemTrayIcon.MessageIcon.Warning
        self._tray.showMessage("view-dock host", message, icon)


class _TrayLogHandler(logging.Handler):
    """Surfaces WARNING+ log records as tray balloon notifications — these
    matter even when the window is hidden/minimized to tray, which the
    window's own log view (see _WindowLogHandler) can't help with then.

    emit() runs on whatever thread produced the log record (almost always
    AsyncLoopThread's, not Qt's GUI thread) — it only formats and emits a
    Qt signal, which is thread-safe; the actual showMessage() call happens
    in TrayApp._show_log_notification(), invoked via a queued connection on
    the GUI thread. See _StatusBridge's comment for why this separation
    matters (directly calling a QSystemTrayIcon/QWidget method here crashed
    the process).
    """

    def __init__(self, bridge: _StatusBridge) -> None:
        super().__init__(level=logging.WARNING)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        self._bridge.log_for_tray.emit(self.format(record), record.levelno)

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class _WindowLogHandler(logging.Handler):
    """Feeds every INFO+ log record into the window's log view — the full
    stream, same as the TUI's log pane, now that there's a window with room
    for it (the tray-only build only had WARNING+ balloon notifications).

    Same thread-safety note as _TrayLogHandler: emit() only formats and
    signals, never touches the QPlainTextEdit directly.
    """

    def __init__(self, bridge: _StatusBridge) -> None:
        super().__init__(level=logging.INFO)
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._bridge.log_for_window.emit(self.format(record))


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(_ICON_PATH))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray available on this desktop.", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=os.environ.get("VIEWDOCK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    tray_app = TrayApp()
    tray_app.start_background_loop()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
