"""X11 implementation of DisplayServer.

Virtual output is created via `xrandr` (dummy output / `--addmode`); frames
are captured via `mss`. This is the phase 1 implementation referenced in
CLAUDE.md.
"""

import numpy as np

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer


class X11DisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._output_name: str | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        # TODO: shell out to `xrandr` to add a mode matching `config` and
        # enable it as a new output (dummy driver or `--addmode` on an
        # existing connector), record self._output_name.
        raise NotImplementedError

    def capture_frame(self) -> np.ndarray:
        # TODO: use `mss` scoped to self._output_name's geometry and return
        # an RGB numpy array for the encoder in streaming/.
        raise NotImplementedError

    def destroy_virtual_display(self) -> None:
        # TODO: shell out to `xrandr` to disable/remove the mode added in
        # create_virtual_display.
        raise NotImplementedError
