# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Reads frames from a PipeWire screen-cast stream (what the ScreenCast portal
hands over on Wayland) as BGRA numpy arrays.

The stream is decoded by a `gst-launch-1.0` child process (GStreamer's
`pipewiresrc`) that writes raw, fixed-size frames to its stdout, so Python
only ever sees plain bytes — no GObject bindings needed in the venv. The
portal's PipeWire file descriptor is passed down to the child as-is.

Compositors send frames only when the screen changes, so a background thread
keeps the latest one and `latest_bgra()` returns it immediately; the streaming
code then repeats it at its own frame rate, as it would an unchanged X11
capture. `videoscale` pins the output to the configured size so a mid-stream
mode change on the compositor side can't change the frame shape underneath
the encoder; a size that's only a few pixels off is stretched rather than
bordered.
"""

import collections
import logging
import shutil
import subprocess
import threading

import numpy as np

logger = logging.getLogger(__name__)

_FIRST_FRAME_TIMEOUT_S = 10.0


def build_pipeline(
    fd: int, node_id: int, width: int, height: int, letterbox: bool = False, negotiate_size: bool = False
) -> list[str]:
    # With `negotiate_size` the size is asked of the compositor itself, which
    # matters on GNOME: Mutter gives a virtual monitor whatever size its
    # stream is negotiated at. (KWin's stream follows the output's mode and
    # would refuse a size it doesn't have, so there it's left open.)
    requested = [f"video/x-raw,width={width},height={height}", "!"] if negotiate_size else []
    return [
        "gst-launch-1.0",
        "-q",
        "pipewiresrc",
        f"fd={fd}",
        f"path={node_id}",
        "always-copy=true",
        "!",
        *requested,
        "videoconvert",
        "!",
        "videoscale",
        f"add-borders={'true' if letterbox else 'false'}",
        "!",
        f"video/x-raw,format=BGRx,width={width},height={height}",
        "!",
        "fdsink",
        "fd=1",
        "sync=false",
    ]


def pipewire_gstreamer_available() -> bool:
    if shutil.which("gst-launch-1.0") is None or shutil.which("gst-inspect-1.0") is None:
        return False
    result = subprocess.run(["gst-inspect-1.0", "pipewiresrc"], capture_output=True)
    return result.returncode == 0


class PipeWireFrameReader:
    def __init__(
        self, fd: int, node_id: int, width: int, height: int, letterbox: bool = False, negotiate_size: bool = False
    ) -> None:
        self._shape = (height, width, 4)
        self._frame_bytes = width * height * 4
        self._latest: np.ndarray | None = None
        self._first_frame = threading.Event()
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
        self._proc = subprocess.Popen(
            build_pipeline(fd, node_id, width, height, letterbox, negotiate_size),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(fd,),
        )
        self._reader = threading.Thread(target=self._read_frames, name="pipewire-frames", daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, name="pipewire-stderr", daemon=True).start()

    def latest_bgra(self) -> np.ndarray:
        if not self._first_frame.wait(_FIRST_FRAME_TIMEOUT_S):
            raise RuntimeError(f"No frames from the PipeWire screen-cast stream. {self._describe_exit()}")
        if not self._reader.is_alive() and self._proc.poll() is not None:
            raise RuntimeError(f"The PipeWire screen-cast stream ended. {self._describe_exit()}")
        return self._latest

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

    def _read_frames(self) -> None:
        stdout = self._proc.stdout
        while True:
            # A fresh array per frame: the consumer may still be encoding the
            # previous one, so it is never written to after being published.
            frame = np.empty(self._shape, dtype=np.uint8)
            view = memoryview(frame.reshape(-1))
            filled = 0
            while filled < self._frame_bytes:
                n = stdout.readinto(view[filled:])
                if not n:
                    return
                filled += n
            self._latest = frame
            self._first_frame.set()

    def _read_stderr(self) -> None:
        for line in self._proc.stderr:
            text = line.decode(errors="replace").rstrip()
            self._stderr_tail.append(text)
            logger.debug("gst: %s", text)

    def _describe_exit(self) -> str:
        code = self._proc.poll()
        status = "still running" if code is None else f"exit code {code}"
        tail = " | ".join(self._stderr_tail) or "no output"
        return f"(gst-launch-1.0 {status}: {tail})"
