"""Terminal UI for the host: start/stop and live connection state without
re-typing `force-connector.sh` + env vars + `python -m host.main` + watching
a scrolling log + remembering Ctrl+C-not-kill every session.

Deliberately a TUI rather than a tray applet or window (see TODO/TODO.md's
"host UI" section for the tradeoff) — no GUI toolkit is installed on this
machine, so a curses UI is what can actually be built and verified here.
A tray applet remains a reasonable future upgrade; this isn't meant to block
one, just to remove the command-line friction today.

Run with `python -m host.ui`.
"""

from __future__ import annotations

import asyncio
import curses
import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass

from host.config import IPAD_PRESETS, DisplayConfig, HostConfig
from host.displayserver.x11 import X11DisplayServer
from host.runner import HostRunner, State, StatusEvent

logger = logging.getLogger(__name__)

_LOG_LINES = 200


@dataclass(frozen=True)
class _Preset:
    label: str
    display: DisplayConfig | None  # None = "Custom (env vars)": HostConfig.default()


def _build_presets() -> list[_Preset]:
    presets = [
        _Preset(f"{name} ({w}x{h})", DisplayConfig(width=w, height=h))
        for name, (w, h) in IPAD_PRESETS.items()
    ]
    presets.append(_Preset("Custom (VIEWDOCK_DISPLAY_* env vars)", None))
    return presets


class _TuiLogHandler(logging.Handler):
    """Feeds formatted log records into a bounded deque the UI thread reads.

    Exists so warnings that today only show up in a scrolling terminal log
    (cursor overlay unavailable, layout watcher unavailable, a dropped
    schema-invalid control message) are visible without tailing a log file.
    """

    def __init__(self, lines: deque[str]) -> None:
        super().__init__()
        self._lines = lines
        self.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._lines.append(self.format(record))


class _AsyncLoopThread:
    """Runs an asyncio event loop on a background thread.

    The HostRunner's lifecycle is a long-lived coroutine (it blocks until the
    session closes or a stop is requested); curses owns the main thread for
    input/rendering, so the runner needs a loop of its own.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, on_error=None) -> None:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_error is not None:

            def _check(f) -> None:
                exc = f.exception()
                if exc is not None:
                    on_error(exc)

            future.add_done_callback(_check)

    def call_soon(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)


class HostUi:
    def __init__(self) -> None:
        self._presets = _build_presets()
        self._selected = 0
        self._state = State.IDLE
        self._detail = ""
        self._status_queue: queue.Queue[StatusEvent] = queue.Queue()
        self._log_lines: deque[str] = deque(maxlen=_LOG_LINES)
        self._loop_thread = _AsyncLoopThread()
        self._runner: HostRunner | None = None
        self._quitting = False

        logging.getLogger().addHandler(_TuiLogHandler(self._log_lines))
        logging.getLogger().setLevel(logging.INFO)

    def _on_status(self, event: StatusEvent) -> None:
        # Called from the loop thread; hand off to the curses thread.
        self._status_queue.put(event)

    def _on_crash(self, exc: BaseException) -> None:
        # Without this, an exception raised inside HostRunner.run() (e.g.
        # /dev/uinput missing) was silently dropped by
        # asyncio.run_coroutine_threadsafe — the UI just sat on its last
        # reported status forever, looking hung, and 'x'/'q' did nothing
        # because the coroutine they were trying to signal had already ended.
        logger.error("Host session crashed: %s", exc, exc_info=exc)
        self._runner = None
        self._status_queue.put(StatusEvent(State.ERROR, str(exc)))

    def _start(self) -> None:
        if self._state not in (State.IDLE, State.ERROR):
            return

        preset = self._presets[self._selected]
        display_config = preset.display if preset.display is not None else HostConfig.default().display

        if X11DisplayServer.find_available_output() is None:
            candidates = X11DisplayServer.list_disconnected_outputs()
            hint = f" Candidates: {', '.join(candidates)}." if candidates else ""
            self._log_lines.append(
                "ERROR   ui: No spare output for the virtual display. Run "
                f"scripts/force-connector.sh <connector> first (see host/README.md).{hint}"
            )
            return

        self._runner = HostRunner(display_config, on_status=self._on_status)
        self._state = State.STARTING
        self._detail = preset.label
        self._loop_thread.submit(self._runner.run(), on_error=self._on_crash)

    def _stop(self) -> None:
        if self._runner is None:
            return
        self._loop_thread.call_soon(self._runner.request_stop)

    def _request_quit(self) -> None:
        if self._state in (State.IDLE, State.ERROR):
            raise SystemExit
        self._quitting = True
        self._stop()

    def _drain_status(self) -> None:
        try:
            while True:
                event = self._status_queue.get_nowait()
                self._state = event.state
                self._detail = event.detail
                if event.state is State.IDLE and self._quitting:
                    raise SystemExit
        except queue.Empty:
            pass

    def run(self, stdscr: "curses._CursesWindow") -> None:
        curses.curs_set(0)
        stdscr.timeout(200)
        self._loop_thread.start()

        try:
            while True:
                self._drain_status()
                self._draw(stdscr)

                key = stdscr.getch()
                if key in (curses.KEY_UP, ord("k")) and self._state in (State.IDLE, State.ERROR):
                    self._selected = (self._selected - 1) % len(self._presets)
                elif key in (curses.KEY_DOWN, ord("j")) and self._state in (State.IDLE, State.ERROR):
                    self._selected = (self._selected + 1) % len(self._presets)
                elif key == ord("s"):
                    self._start()
                elif key == ord("x"):
                    self._stop()
                elif key == ord("q"):
                    self._request_quit()
        except SystemExit:
            pass
        finally:
            self._loop_thread.stop()

    def _draw(self, stdscr: "curses._CursesWindow") -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        title = "view-dock host"
        status = f"[{self._state.value}{': ' + self._detail if self._detail else ''}]"
        stdscr.addnstr(0, 0, title, width - 1)
        stdscr.addnstr(0, max(0, width - len(status) - 1), status, width - 1)
        stdscr.hline(1, 0, curses.ACS_HLINE, width)

        row = 2
        stdscr.addnstr(row, 0, "Resolution (logical points):", width - 1)
        row += 1
        editable = self._state in (State.IDLE, State.ERROR)
        for i, preset in enumerate(self._presets):
            marker = ">" if i == self._selected else " "
            stdscr.addnstr(row, 2, f"{marker} {preset.label}", width - 3)
            row += 1
        if not editable:
            stdscr.addnstr(row, 0, "(stop the session to change resolution)", width - 1)
        row += 1

        keys = "[s] start   [x] stop   [q] quit   [up/down] select"
        stdscr.addnstr(row, 0, keys, width - 1)
        row += 2

        stdscr.hline(row, 0, curses.ACS_HLINE, width)
        row += 1
        stdscr.addnstr(row, 0, "Log:", width - 1)
        row += 1
        log_capacity = max(0, height - row - 1)
        for line in list(self._log_lines)[-log_capacity:]:
            stdscr.addnstr(row, 0, line, width - 1)
            row += 1

        stdscr.refresh()


def main() -> None:
    curses.wrapper(HostUi().run)


if __name__ == "__main__":
    main()
