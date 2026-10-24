"""Shared, cancelable subprocess-running helper.

This is foundational plumbing for the planned parallel-race architecture
(caption/comment/visual/audio candidate extraction all running
concurrently, with the losers genuinely killed once a winner is found).
It is a FIXED CONTRACT: the audio-transcription subpackage (built in
parallel by a different agent) codes directly against `run_cancelable`'s
name and signature, so neither may change without coordinating.

`run_cancelable()` is a drop-in replacement for::

    subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds)

that additionally supports being told to abort early via a
`threading.Event`, with real OS-level process termination (not merely
abandoning the wait while the child keeps running). `cancel_event=None`
means "behave exactly like `subprocess.run` with the given timeout" --
every existing caller migrating from `subprocess.run` to this helper gets
that as a safe default.

Implementation note: this never issues one blocking `communicate(timeout=
...)` call. It instead polls (`proc.wait(timeout=poll_interval_seconds)`
in a loop) so that, in between polls, it can also check `cancel_event` and
the overall elapsed-time budget. Only once the process has actually exited
normally does it call `proc.communicate()`, to drain any output still
sitting in the pipes.
"""

from __future__ import annotations

import subprocess
import threading
import time

# How long to wait, after sending SIGTERM, before escalating to SIGKILL --
# applies both on cancellation and on timeout. Long enough for a
# well-behaved process (ffmpeg, the `claude` CLI) to notice the signal and
# exit cleanly; short enough that cancellation/timeout handling itself
# never hangs for long.
_TERMINATE_GRACE_SECONDS = 2.0


class SubprocessCancelled(Exception):
    """Raised when cancel_event fires while a subprocess call is in flight."""


def _terminate_then_kill(
    proc: subprocess.Popen, grace_seconds: float = _TERMINATE_GRACE_SECONDS
) -> None:
    """Escalate `proc.terminate()` -> (grace period) -> `proc.kill()`.

    Always waits for the process to actually exit before returning, so the
    caller never leaves a zombie/orphaned process behind.
    """
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_cancelable(
    args: list[str],
    *,
    timeout_seconds: float,
    cancel_event: "threading.Event | None" = None,
    poll_interval_seconds: float = 0.2,
    **popen_kwargs,
) -> subprocess.CompletedProcess:
    """Run `args` via `subprocess.Popen`, pollable and cancelable.

    Polls at `poll_interval_seconds` intervals for whichever of these
    happens first:

    - normal completion -- drains stdout/stderr via `proc.communicate()`
      and returns a `subprocess.CompletedProcess(args, returncode, stdout,
      stderr)`, the same shape `subprocess.run` returns.
    - `cancel_event` becoming set (only checked when `cancel_event is not
      None`) -- terminates the process (see `_terminate_then_kill`) and
      raises `SubprocessCancelled`.
    - `timeout_seconds` being exceeded -- terminates the process and
      raises `subprocess.TimeoutExpired(args, timeout_seconds)`, matching
      `subprocess.run`'s own timeout contract.

    In both the cancel and timeout cases the subprocess is actually killed
    (terminate, grace period, then kill if still alive) before this
    function raises -- it never leaves a zombie/orphaned process behind.

    `cancel_event=None` disables cancellation entirely: this then behaves
    like `subprocess.run(args, capture_output=True, text=True,
    timeout=timeout_seconds)`, just implemented via polling internally.
    """
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **popen_kwargs
    )

    start = time.monotonic()
    while True:
        try:
            proc.wait(timeout=poll_interval_seconds)
            break  # process exited on its own
        except subprocess.TimeoutExpired:
            pass  # still running -- fall through to the cancel/timeout checks below

        if cancel_event is not None and cancel_event.is_set():
            _terminate_then_kill(proc)
            raise SubprocessCancelled(
                f"subprocess {args!r} was cancelled via cancel_event"
            )

        if time.monotonic() - start >= timeout_seconds:
            _terminate_then_kill(proc)
            raise subprocess.TimeoutExpired(args, timeout_seconds)

    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
