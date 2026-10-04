"""Common interface for establishing the socket/channel that WebRTC
signaling rides over, regardless of whether it's Wi-Fi or a USB tunnel.
"""

from abc import ABC, abstractmethod


class Transport(ABC):
    # True when this transport's connection should carry the whole session
    # (video as binary frames + control messages) instead of just the WebRTC
    # SDP handshake — see "Wired stream" in protocol/PROTOCOL.md. Only
    # transports that expose `send_message`/`receive_message` may set it.
    supports_wired_stream = False

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this transport currently has a reachable iPad."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection used for WebRTC signaling."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the underlying connection."""

    @abstractmethod
    async def send_signal(self, message: dict) -> None:
        """Send one JSON signaling message (SDP offer/answer) to the iPad."""

    @abstractmethod
    async def receive_signal(self) -> dict:
        """Block for the next JSON signaling message from the iPad."""
