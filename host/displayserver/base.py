# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Abstraction over a Linux display server's virtual-monitor + capture
capabilities, so `streaming/` doesn't need to know whether it's talking to
X11 or (later) Wayland.
"""

from abc import ABC, abstractmethod

import numpy as np

from host.config import DisplayConfig


class DisplayServer(ABC):
    """Owns creation/teardown of the virtual display and frame capture."""

    @abstractmethod
    def create_virtual_display(self, config: DisplayConfig) -> None:
        """Create and activate the virtual output described by `config`."""

    # True if `capture_frame_bgra` works. A display server whose native format is
    # BGRA (X11) can hand frames over without the channel-reorder copy that
    # `capture_frame` needs, which is a large part of the per-frame cost at 60 fps.
    supports_bgra_capture = False

    @abstractmethod
    def capture_frame(self) -> np.ndarray:
        """Return the latest frame of the virtual display as an RGB array."""

    def capture_frame_bgra(self) -> np.ndarray:
        """Optional fast path: the frame as a C-contiguous (height, width, 4)
        uint8 BGRA array. Only valid when `supports_bgra_capture` is True."""
        raise NotImplementedError

    @abstractmethod
    def destroy_virtual_display(self) -> None:
        """Tear down the virtual output, restoring prior display state."""
