"""Synthetic animated frame source — no real capture at all.

Useful for validating the encode/transport/decode/render pipeline
independently of the host's actual screen-capture capability, which is
blocked on this machine's Wayland session for the same underlying reason
`x11.py`'s virtual display is (see `passthrough.py`'s docstring): Xwayland
doesn't expose composited desktop content to X11 clients.
"""

import time

import numpy as np

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer


class TestPatternDisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._config: DisplayConfig | None = None
        self._start_time = 0.0

    def create_virtual_display(self, config: DisplayConfig) -> None:
        self._config = config
        self._start_time = time.monotonic()

    def capture_frame(self) -> np.ndarray:
        if self._config is None:
            raise RuntimeError("Display not created; call create_virtual_display() first.")

        width, height = self._config.width, self._config.height
        t = time.monotonic() - self._start_time

        x = np.linspace(0, 1, width, dtype=np.float32)
        y = np.linspace(0, 1, height, dtype=np.float32)
        xv, yv = np.meshgrid(x, y)

        red = np.sin(2 * np.pi * (xv + t * 0.1)) * 0.5 + 0.5
        green = np.sin(2 * np.pi * (yv + t * 0.15)) * 0.5 + 0.5
        blue = np.sin(2 * np.pi * (xv + yv + t * 0.2)) * 0.5 + 0.5

        frame = np.stack([red, green, blue], axis=-1)
        return (frame * 255).astype(np.uint8)

    def destroy_virtual_display(self) -> None:
        self._config = None
