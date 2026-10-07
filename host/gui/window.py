# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Main window for the host GUI: the actual controls (resolution, start/stop,
live log) that the tray icon's right-click menu duplicates in miniature.
Launching `python -m host.gui` opens this; the tray icon stays around so the
window can be hidden without ending the session.

Kept separate from tray.py so TrayApp (which owns the one HostRunner/loop
thread) stays the single place driving start/stop/preset logic — this module
only renders state and emits signals for TrayApp to act on.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from host.netinfo import wifi_address_text
from host.presets import Preset
from host.transport.wifi import DEFAULT_PORT
from host.runner import State

_SETTINGS_ORG = "view-dock"
_SETTINGS_APP = "host-gui"
_CLOSE_BEHAVIOR_KEY = "close_behavior"
CLOSE_TO_TRAY = "tray"
CLOSE_TO_QUIT = "quit"

_LOG_MAX_BLOCKS = 2000


def _dot_pixmap(color: QColor, size: int = 16) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return pixmap


class HostWindow(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    preset_selected = Signal(object)  # Preset
    quit_requested = Signal()

    def __init__(self, presets: list[Preset], icon_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("view-dock host")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.resize(480, 420)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._presets = presets

        self._status_dot = QLabel()
        self._status_text = QLabel("idle")
        status_row = QHBoxLayout()
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_text)
        status_row.addStretch(1)

        self._address_label = QLabel(wifi_address_text(DEFAULT_PORT))
        self._address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._preset_combo = QComboBox()
        for preset in presets:
            self._preset_combo.addItem(preset.label, preset)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_index_changed)

        self._start_button = QPushButton("Start")
        self._start_button.clicked.connect(self.start_requested)
        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self.stop_requested)
        self._stop_button.setEnabled(False)

        button_row = QHBoxLayout()
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._stop_button)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._log_view.setStyleSheet("font-family: monospace;")

        self._close_to_tray_combo = QComboBox()
        self._close_to_tray_combo.addItem("Minimize to tray", CLOSE_TO_TRAY)
        self._close_to_tray_combo.addItem("Quit", CLOSE_TO_QUIT)
        current = self._settings.value(_CLOSE_BEHAVIOR_KEY, CLOSE_TO_TRAY)
        self._close_to_tray_combo.setCurrentIndex(0 if current != CLOSE_TO_QUIT else 1)
        self._close_to_tray_combo.currentIndexChanged.connect(self._on_close_behavior_changed)
        close_row = QHBoxLayout()
        close_row.addWidget(QLabel("When closing this window:"))
        close_row.addWidget(self._close_to_tray_combo)
        close_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(status_row)
        layout.addWidget(self._address_label)
        layout.addWidget(QLabel("Resolution (logical points):"))
        layout.addWidget(self._preset_combo)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self._log_view, stretch=1)
        layout.addLayout(close_row)
        self.setLayout(layout)

    # -- external API, called by TrayApp ---------------------------------

    def apply_status(self, state: State, detail: str, dot_color: QColor) -> None:
        label = state.value + (f": {detail}" if detail else "")
        self._status_dot.setPixmap(_dot_pixmap(dot_color))
        self._status_text.setText(label)
        # The network can change between sessions (docking, a new Wi-Fi), so
        # look again rather than showing whatever it was at launch.
        self._address_label.setText(wifi_address_text(DEFAULT_PORT))

        editable = state in (State.IDLE, State.ERROR)
        self._preset_combo.setEnabled(editable)
        self._start_button.setEnabled(editable)
        self._stop_button.setEnabled(not editable)

    def append_log(self, line: str) -> None:
        self._log_view.appendPlainText(line)

    def selected_preset(self) -> Preset:
        return self._preset_combo.currentData()

    # -- internal ----------------------------------------------------------

    def _on_preset_index_changed(self, _index: int) -> None:
        preset = self._preset_combo.currentData()
        if preset is not None:
            self.preset_selected.emit(preset)

    def _on_close_behavior_changed(self, _index: int) -> None:
        self._settings.setValue(_CLOSE_BEHAVIOR_KEY, self._close_to_tray_combo.currentData())

    def closeEvent(self, event: QCloseEvent) -> None:
        behavior = self._settings.value(_CLOSE_BEHAVIOR_KEY, CLOSE_TO_TRAY)
        if behavior == CLOSE_TO_QUIT:
            event.accept()
            self.quit_requested.emit()
        else:
            event.ignore()
            self.hide()
