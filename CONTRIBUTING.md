# Contributing

Contributions, ideas, and feedback are welcome. If you're tackling one of the
known limitations in the README or something adjacent, open an issue first
to compare notes — some of these (touch-as-a-real-touchscreen especially)
have real design tradeoffs worth discussing before diving into an
implementation.

## Dev setup

Follow the host setup steps in the [README](README.md#1-host-setup-on-the-arch-linux-machine)
to get a working `.venv` with `host/requirements.txt` installed. For the
iPad app, see [`ipad/README.md`](ipad/README.md).

## Running tests

The host test suite is pure Python and mocks out hardware (uinput, X11,
subprocess calls), so it runs headless without an actual display or iPad
connected:

```sh
source .venv/bin/activate
python -m pytest host/tests
```

CI (`.github/workflows/tests.yml`) runs this same suite on every push and
pull request.

There's no automated test suite for the iPad app yet — changes there should
be verified by building and running on a physical device (WebRTC/video
doesn't work in the Simulator).

## Protocol changes

`protocol/` is the contract between `host/` and `ipad/`. If you change
`protocol/schema/*.json` or `protocol/messages.py`, update both
implementations in the same PR rather than letting them drift — see
[`protocol/PROTOCOL.md`](protocol/PROTOCOL.md).

## Pull requests

Keep PRs focused on one change. Fill out the PR template — in particular,
note whether you verified the change on real hardware, since the test suite
doesn't cover the capture/streaming/input pipeline end-to-end.
