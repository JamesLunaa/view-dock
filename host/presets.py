"""Device-resolution preset list shared by `host/ui/` and `host/gui/`, so the
curses UI and the Qt tray offer the exact same choices instead of drifting.
"""

from dataclasses import dataclass

from host.config import ANDROID_PRESETS, IPAD_PRESETS, DisplayConfig

CUSTOM_LABEL = "Custom (VIEWDOCK_DISPLAY_* env vars)"


@dataclass(frozen=True)
class Preset:
    label: str
    display: DisplayConfig | None  # None = CUSTOM_LABEL: HostConfig.default()


def build_presets() -> list[Preset]:
    presets = [
        Preset(f"{name} ({w}x{h})", DisplayConfig(width=w, height=h))
        for name, (w, h) in {**IPAD_PRESETS, **ANDROID_PRESETS}.items()
    ]
    presets.append(Preset(CUSTOM_LABEL, None))
    return presets
