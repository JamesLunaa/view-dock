"""Composites the X11 pointer into captured frames.

`mss` (XGetImage underneath) returns framebuffer contents only — the pointer
is drawn by the X server as a separate overlay (hardware cursor plane or
software sprite) and never lands in a plain capture. Without this the iPad
shows no cursor at all, so there's no way to see where you're pointing on
the virtual display.

XFixes' GetCursorImage returns the pointer bitmap, its root-relative
position and its hotspot in a single round trip (~0.3 ms on this host, so
~2% of a 60 Hz frame budget).
"""

import logging

import numpy as np
from Xlib import display as xdisplay

logger = logging.getLogger(__name__)


class X11CursorCompositor:
    def __init__(self) -> None:
        self._display = xdisplay.Display()
        self._root = self._display.screen().root
        # XFixes requires a version handshake before any other request on the
        # connection. Skipping it makes the server reject later calls with an
        # error whose code collides with RandR's numbering, which python-xlib
        # then mis-decodes into a bogus BadRRCrtcError — a confusing failure
        # worth not rediscovering.
        self._display.xfixes_query_version()
        self._cached_serial: int | None = None
        self._cached_rgba: np.ndarray | None = None

    def close(self) -> None:
        self._display.close()

    def composite(self, frame: np.ndarray, monitor: dict[str, int]) -> None:
        """Draw the pointer into `frame` in place.

        `monitor` is the captured region in root coordinates — the same dict
        shape `mss` takes, so the caller can pass what it already has.
        """
        cursor = self._display.xfixes_get_cursor_image(self._root)

        # Top-left of the cursor bitmap, in frame coordinates.
        left = cursor.x - cursor.xhot - monitor["left"]
        top = cursor.y - cursor.yhot - monitor["top"]

        height, width = frame.shape[:2]
        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(left + cursor.width, width), min(top + cursor.height, height)
        if x0 >= x1 or y0 >= y1:
            return  # Pointer is on another monitor, or clipped fully offscreen.

        patch = self._decode(cursor)[y0 - top : y1 - top, x0 - left : x1 - left]
        alpha = patch[:, :, 3:4].astype(np.uint16)
        target = frame[y0:y1, x0:x1].astype(np.uint16)
        # XFixes cursor pixels are premultiplied ARGB, so the source term is
        # already scaled by alpha — only the destination needs attenuating.
        blended = patch[:, :, :3] + (target * (255 - alpha)) // 255
        frame[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)

    def _decode(self, cursor) -> np.ndarray:
        """Unpack the cursor's ARGB words into an RGBA array, memoized on the
        server's cursor serial so a stationary pointer costs nothing to redraw.
        """
        if cursor.cursor_serial == self._cached_serial and self._cached_rgba is not None:
            return self._cached_rgba

        packed = np.fromiter(
            cursor.cursor_image, dtype=np.uint32, count=cursor.width * cursor.height
        ).reshape(cursor.height, cursor.width)

        rgba = np.empty((cursor.height, cursor.width, 4), dtype=np.uint8)
        rgba[:, :, 0] = (packed >> 16) & 0xFF
        rgba[:, :, 1] = (packed >> 8) & 0xFF
        rgba[:, :, 2] = packed & 0xFF
        rgba[:, :, 3] = (packed >> 24) & 0xFF

        self._cached_serial = cursor.cursor_serial
        self._cached_rgba = rgba
        return rgba
