"""KDE tray applet for the host: a StatusNotifierItem instead of a terminal.

Reuses the exact same `host/runner.py` `HostRunner` and `host/presets.py`
preset list the TUI (`host/ui/`) does — this is meant to be a thin shell
around the same lifecycle, not a reimplementation of it. See TODO/TODO.md's
"host UI" section for why a TUI shipped first (no GUI toolkit was installed
to build/verify one) and this is the planned upgrade now that PySide6 is.

Run with `python -m host.gui`.
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from host.async_loop_thread import AsyncLoopThread
from host.config import HostConfig
from host.displayserver.x11 import X11DisplayServer
from host.presets import Preset, build_presets
from host.runner import HostRunner, State, StatusEvent

logger = logging.getLogger(__name__)

# One dot color per state, used for both the tray icon and (implicitly) at a
# glance in the tooltip text — avoids needing a bundled icon asset.
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
    update tray UI safely without a manually-polled queue like the TUI uses.
    """

    status_changed = Signal(object)
    crashed = Signal(object)


class TrayApp:
    def __init__(self) -> None:
        self._presets = build_presets()
        self._selected: Preset = self._presets[0]
        self._state = State.IDLE
        self._detail = ""
        self._runner: HostRunner | None = None
        self._loop_thread = AsyncLoopThread()

        self._bridge = _StatusBridge()
        self._bridge.status_changed.connect(self._handle_status, Qt.ConnectionType.QueuedConnection)
        self._bridge.crashed.connect(self._handle_crash, Qt.ConnectionType.QueuedConnection)

        self._tray = QSystemTrayIcon(_dot_icon(_STATE_COLORS[State.IDLE]))
        self._tray.setToolTip("view-dock: idle")

        self._menu = QMenu()
        self._status_action = QAction("idle")
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
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

        logging.getLogger().addHandler(_TrayLogHandler(self._tray))
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

    def _handle_crash(self, exc: BaseException) -> None:
        self._runner = None
        self._state = State.ERROR
        self._detail = str(exc)
        self._refresh()
        self._tray.showMessage("view-dock host crashed", str(exc), QSystemTrayIcon.MessageIcon.Critical)

    def _refresh(self) -> None:
        label = self._state.value + (f": {self._detail}" if self._detail else "")
        self._tray.setToolTip(f"view-dock: {label}")
        self._tray.setIcon(_dot_icon(_STATE_COLORS[self._state]))
        self._status_action.setText(label)

        editable = self._state in (State.IDLE, State.ERROR)
        self._resolution_menu.setEnabled(editable)
        self._start_action.setEnabled(editable)
        self._stop_action.setEnabled(not editable)

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
        if self._runner is not None:
            self._loop_thread.call_soon(self._runner.request_stop)
        self._loop_thread.stop()
        QApplication.instance().quit()


class _TrayLogHandler(logging.Handler):
    """Surfaces WARNING+ log records as tray balloon notifications.

    The TUI has room for a scrolling log pane; a tray applet doesn't, so
    warnings that'd otherwise only hit the log (cursor overlay unavailable,
    layout watcher unavailable, a dropped schema-invalid control message)
    show up as notifications instead. INFO and below stay log-only — a
    notification per frame-level message would be unusable.
    """

    def __init__(self, tray: QSystemTrayIcon) -> None:
        super().__init__(level=logging.WARNING)
        self._tray = tray

    def emit(self, record: logging.LogRecord) -> None:
        icon = QSystemTrayIcon.MessageIcon.Critical if record.levelno >= logging.ERROR else QSystemTrayIcon.MessageIcon.Warning
        self._tray.showMessage("view-dock host", self.format(record), icon)

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

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
