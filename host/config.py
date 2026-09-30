"""Runtime configuration for the host server."""

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
        return cls(display=DisplayConfig())
