# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Runs an asyncio event loop on a background thread.

`HostRunner.run()` is a long-lived coroutine (it blocks until the session
closes or a stop is requested). Both UIs (`host/ui/` curses, `host/gui/` Qt
tray) own their main thread for input/rendering via their own toolkit's event
loop, so the runner needs a loop of its own rather than sharing either.
"""

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, Callable


class AsyncLoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any], on_error: Callable[[BaseException], None] | None = None) -> None:
        """Schedules `coro` on the loop. `run_coroutine_threadsafe` otherwise
        drops an exception on the floor unless its Future is retrieved — a
        crash inside the coroutine would then look like a silent hang to
        whatever's driving a UI from this thread, since nothing is awaiting
        this Future. `on_error`, if given, is called (from the loop thread)
        with the exception when that happens.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_error is not None:

            def _check(f: "asyncio.Future[Any]") -> None:
                exc = f.exception()
                if exc is not None:
                    on_error(exc)

            future.add_done_callback(_check)

    def call_soon(self, fn: Callable[..., Any], *args: Any) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)
