"""Common interface for establishing the socket/channel that WebRTC
signaling rides over, regardless of whether it's Wi-Fi or a USB tunnel.
"""

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this transport currently has a reachable iPad."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection used for WebRTC signaling."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the underlying connection."""
