"""Runtime configuration for the host server."""

import os
from dataclasses import dataclass


@dataclass
class DisplayConfig:
    # iPad Air 11" (M3), in LOGICAL POINTS — deliberately not its 2360x1640
    # physical pixels. It's a 2x retina panel, X11 renders UI at ~96 DPI, and
    # X11 offers no per-output scaling (KDE's "Global scale" is global, so
    # raising it would distort the built-in screen too). Driving the virtual
    # display at physical resolution therefore renders every toolbar and glyph
    # at half its intended physical size; at point resolution the iPad
    # upscales 2x and it lands correctly.
    #
    # Override via VIEWDOCK_DISPLAY_WIDTH/HEIGHT for a different device, using
    # that device's point resolution. Note `cvt` rounds width to a multiple of
    # 8 (1180 -> 1184), a 0.3% aspect difference that isn't visible.
    width: int = 1180
    height: int = 820
    refresh_hz: int = 60


@dataclass
class HostConfig:
    display: DisplayConfig
    prefer_usb: bool = True

    @classmethod
    def default(cls) -> "HostConfig":
        # Env var overrides, e.g. for a smaller test display, or matching a
        # specific iPad model's native resolution instead of the iPad Pro
        # default above.
        display = DisplayConfig(
            width=int(os.environ.get("VIEWDOCK_DISPLAY_WIDTH", DisplayConfig.width)),
            height=int(os.environ.get("VIEWDOCK_DISPLAY_HEIGHT", DisplayConfig.height)),
            refresh_hz=int(os.environ.get("VIEWDOCK_DISPLAY_REFRESH_HZ", DisplayConfig.refresh_hz)),
        )
        return cls(display=display)
