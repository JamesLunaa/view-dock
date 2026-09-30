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

    @abstractmethod
    def capture_frame(self) -> np.ndarray:
        """Return the latest frame of the virtual display as an RGB array."""

    @abstractmethod
    def destroy_virtual_display(self) -> None:
        """Tear down the virtual output, restoring prior display state."""
