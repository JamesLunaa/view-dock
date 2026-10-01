"""Runtime configuration for the host server."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Every current IPAD_PRESETS entry's width/height ratio falls in ~1.33-1.52
# (standard tablet aspect ratios). A size outside this band is almost always
# a typo (swapped width/height, or a phone/monitor aspect pasted in by
# mistake) rather than a real device — and the failure mode is a hairline-to-
# severe letterbox on the iPad that otherwise looks like "the app is broken"
# with nothing in the log to explain it.
_MIN_TABLET_ASPECT = 1.2
_MAX_TABLET_ASPECT = 1.7


def _warn_on_aspect_mismatch(width: int, height: int) -> None:
    aspect = width / height
    if not (_MIN_TABLET_ASPECT <= aspect <= _MAX_TABLET_ASPECT):
        logger.warning(
            "Display size %dx%d has an unusual aspect ratio (%.3f) for a tablet "
            "(expected roughly %.1f-%.1f) — check VIEWDOCK_DISPLAY_WIDTH/HEIGHT "
            "aren't swapped or mistyped; this will letterbox on the iPad.",
            width,
            height,
            aspect,
            _MIN_TABLET_ASPECT,
            _MAX_TABLET_ASPECT,
        )


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
    # Opt-in, off (1) by default: multiplies the ACTUAL XRandR mode/capture
    # resolution (see capture_width/capture_height below) while `width`/
    # `height` above stay the device's logical point size — used for
    # display_info's orientation calc, the aspect-ratio sanity check, and the
    # preset list, none of which should change just because capture got
    # sharper. Only worth setting (via VIEWDOCK_DISPLAY_SCALE) alongside
    # `host/scripts/launch-on-virtual-display.sh`, which sets the matching
    # QT_SCALE_FACTOR/GDK_SCALE for an app launched directly onto this
    # display. Any window *dragged over* from the built-in screen does not
    # get this treatment — it keeps rendering at its origin screen's density,
    # so it will look small on a scaled virtual display; this only helps the
    # narrower case of an app opened directly here. See host/README.md.
    capture_scale: int = 1

    @property
    def capture_width(self) -> int:
        return self.width * self.capture_scale

    @property
    def capture_height(self) -> int:
        return self.height * self.capture_scale


# Logical-point (not physical-pixel) landscape resolutions for current iPad
# models, for host/ui's device picker — see DisplayConfig's docstring above
# for why points and not pixels. Source: Apple's published point resolutions
# per model; verified against hardware for the Air 11" (M3) only so far.
IPAD_PRESETS: dict[str, tuple[int, int]] = {
    "iPad Air 11\" (M2/M3)": (1180, 820),
    "iPad Air 13\" (M2/M3)": (1366, 1024),
    "iPad Pro 11\" (M4)": (1194, 834),
    "iPad Pro 13\" (M4)": (1376, 1032),
    "iPad (10th/11th gen)": (1180, 820),
    "iPad mini (6th/A17 Pro)": (1133, 744),
}


@dataclass
class HostConfig:
    display: DisplayConfig
    prefer_usb: bool = True

    @classmethod
    def default(cls) -> "HostConfig":
        # Env var overrides, e.g. for a smaller test display, or matching a
        # specific iPad model's native resolution instead of the iPad Pro
        # default above.
        width = int(os.environ.get("VIEWDOCK_DISPLAY_WIDTH", DisplayConfig.width))
        height = int(os.environ.get("VIEWDOCK_DISPLAY_HEIGHT", DisplayConfig.height))
        _warn_on_aspect_mismatch(width, height)
        capture_scale = int(os.environ.get("VIEWDOCK_DISPLAY_SCALE", DisplayConfig.capture_scale))
        if capture_scale < 1:
            raise ValueError(f"VIEWDOCK_DISPLAY_SCALE must be a positive integer, got {capture_scale}")
        display = DisplayConfig(
            width=width,
            height=height,
            refresh_hz=int(os.environ.get("VIEWDOCK_DISPLAY_REFRESH_HZ", DisplayConfig.refresh_hz)),
            capture_scale=capture_scale,
        )
        return cls(display=display)
