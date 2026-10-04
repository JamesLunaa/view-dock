# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The pointer overlay must paint the same colours whichever channel order the
frame is in: the BGRA fast path (`capture_frame_bgra`) hands it BGR(A) frames.
"""

import numpy as np
import pytest

from host.displayserver.cursor import X11CursorCompositor


class _FakeCursor:
    """A 2x2 premultiplied-ARGB pointer: opaque red in one pixel, the rest transparent."""

    x, y, xhot, yhot, width, height = 3, 3, 0, 0, 2, 2
    cursor_serial = 1
    cursor_image = [0xFFFF0000, 0, 0, 0]  # ARGB: opaque red, then three transparent pixels


class _FakeDisplay:
    def xfixes_get_cursor_image(self, _root):
        return _FakeCursor()


def _compositor() -> X11CursorCompositor:
    compositor = X11CursorCompositor.__new__(X11CursorCompositor)  # no real X connection
    compositor._display = _FakeDisplay()
    compositor._root = None
    compositor._cached_serial = None
    compositor._cached_rgba = None
    return compositor


MONITOR = {"left": 0, "top": 0, "width": 8, "height": 8}


def test_rgb_frame_gets_a_red_pointer():
    frame = np.full((8, 8, 3), 50, dtype=np.uint8)
    _compositor().composite(frame, MONITOR)
    assert tuple(frame[3, 3]) == (255, 0, 0)  # R, G, B
    assert tuple(frame[0, 0]) == (50, 50, 50), "pixels outside the pointer are untouched"


@pytest.mark.parametrize("channels", [3, 4])
def test_bgr_frame_gets_the_same_red_pointer_in_bgr_order(channels):
    frame = np.full((8, 8, channels), 50, dtype=np.uint8)
    _compositor().composite(frame, MONITOR, bgr=True)
    assert tuple(frame[3, 3, :3]) == (0, 0, 255)  # B, G, R — still red
    assert tuple(frame[0, 0, :3]) == (50, 50, 50)


def test_alpha_channel_is_left_alone():
    frame = np.full((8, 8, 4), 50, dtype=np.uint8)
    frame[..., 3] = 200
    _compositor().composite(frame, MONITOR, bgr=True)
    assert frame[3, 3, 3] == 200 and frame[0, 0, 3] == 200
