"""Runtime configuration for the host server."""

import os
from dataclasses import dataclass


@dataclass
class DisplayConfig:
    width: int = 2732
    height: int = 2048
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
