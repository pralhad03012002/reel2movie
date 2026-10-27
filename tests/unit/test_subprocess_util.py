"""Tests for `reel2movie._subprocess_util.run_cancelable`.

This is the foundational, fixed-contract cancelable-subprocess helper that
`reel2movie._claude_cli.run_claude_cli`, `reel2movie.visual.frame_sampler`,
and the `reel2movie.audio` subpackage all build on. Real subprocesses (the
current Python interpreter, via `sys.executable -c <script>`) are used
here rather than mocks -- there is no meaningful way to prove "the OS
process was genuinely killed, not just abandoned" without a real process
to check on.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from reel2movie._subprocess_util import SubprocessCancelled, run_cancelable


def _is_process_alive(pid: int) -> bool:
    """True if `pid` still exists (POSIX `kill(pid, 0)` existence check,
    sends no actual signal)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, but we're not allowed to signal it -- still alive.
        return True
    return True


def _pid_writing_sleep_script(pid_file: Path, sleep_seconds: float) -> str:
    """A one-liner that records its own PID to `pid_file`, then sleeps.

    Lets a test confirm (via the recorded PID) that the real OS process
    was actually terminated, not merely that `run_cancelable` returned or
    raised.
    """
    return (
        "import os, time\n"
        f"open(r'{pid_file}', 'w').write(str(os.getpid()))\n"
        f"time.sleep({sleep_seconds})\n"
    )


class TestNormalCompletion:
    def test_fast_command_returns_completed_process_with_correct_shape(self) -> None:
        result = run_cancelable(
            [sys.executable, "-c", "print('hello world')"], timeout_seconds=10
        )

        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0
        assert result.stdout.strip() == "hello world"

    def test_captures_stdout_and_stderr_separately(self) -> None:
        script = "import sys; print('on stdout'); print('on stderr', file=sys.stderr)"
        result = run_cancelable([sys.executable, "-c", script], timeout_seconds=10)

        assert result.stdout.strip() == "on stdout"
        assert result.stderr.strip() == "on stderr"

    def test_nonzero_exit_code_is_reflected_not_raised(self) -> None:
        result = run_cancelable(
            [sys.executable, "-c", "import sys; sys.exit(7)"], timeout_seconds=10
        )

        assert result.returncode == 7

    def test_large_output_does_not_deadlock_the_poll_loop(self) -> None:
        """Regression test: a child writing more than one OS pipe buffer's
        worth of combined stdout/stderr before exiting must still complete
        promptly.

        `Popen.wait(timeout=...)` (unlike `Popen.communicate(timeout=...)`)
        never reads the pipes, so a poll loop built on bare `wait()` calls
        deadlocks here: the child blocks on `write()` once the ~64KB pipe
        buffer fills, and `wait()` just keeps timing out even though the
        process would otherwise finish almost instantly -- it only gets
        unstuck once the outer `timeout_seconds` budget elapses and the
        process is killed. A fast, well under `timeout_seconds` completion
        here proves the implementation actively drains the pipes while
        polling, not just waits on them.
        """
        script = "import sys; sys.stdout.write('x' * 200_000); sys.stdout.flush()"

        start = time.monotonic()
        result = run_cancelable(
            [sys.executable, "-c", script],
            timeout_seconds=10,
            poll_interval_seconds=0.2,
        )
        elapsed = time.monotonic() - start

        assert result.returncode == 0
        assert len(result.stdout) == 200_000
        assert elapsed < 3.0, (
            f"took {elapsed:.2f}s -- looks like the poll loop deadlocked "
            "on a full pipe buffer instead of draining it"
        )

    def test_cancel_event_none_behaves_like_subprocess_run(self) -> None:
        """`cancel_event=None` is documented as a fully backward-compatible
        stand-in for a plain `subprocess.run(..., timeout=...)` call."""
        args = [sys.executable, "-c", "print('same result')"]

        expected = subprocess.run(args, capture_output=True, text=True, timeout=10)
        actual = run_cancelable(args, timeout_seconds=10, cancel_event=None)

        assert actual.returncode == expected.returncode
        assert actual.stdout == expected.stdout
        assert actual.stderr == expected.stderr


class TestCancellation:
    def test_cancel_event_kills_the_real_process_within_roughly_one_poll_interval(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "pid.txt"
        script = _pid_writing_sleep_script(pid_file, sleep_seconds=30)
        cancel_event = threading.Event()

        def _trigger_cancel_shortly_after_start() -> None:
            time.sleep(0.5)
            cancel_event.set()

        threading.Thread(target=_trigger_cancel_shortly_after_start).start()

        start = time.monotonic()
        with pytest.raises(SubprocessCancelled):
            run_cancelable(
                [sys.executable, "-c", script],
                timeout_seconds=30,
                cancel_event=cancel_event,
                poll_interval_seconds=0.1,
            )
        elapsed = time.monotonic() - start

        # Cancelled roughly one poll interval after the 0.5s trigger, not
        # anywhere near the 30s timeout_seconds budget.
        assert elapsed < 3.0

        # The real OS process must actually be gone -- not just that
        # run_cancelable returned/raised.
        assert pid_file.exists(), "subprocess never started / never wrote its PID"
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2.0
        while _is_process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _is_process_alive(pid), f"process {pid} was not actually killed"

    def test_cancel_event_already_set_before_a_slow_command_cancels_promptly(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "pid.txt"
        script = _pid_writing_sleep_script(pid_file, sleep_seconds=30)
        cancel_event = threading.Event()
        cancel_event.set()

        start = time.monotonic()
        with pytest.raises(SubprocessCancelled):
            run_cancelable(
                [sys.executable, "-c", script],
                timeout_seconds=30,
                cancel_event=cancel_event,
                poll_interval_seconds=0.1,
            )
        elapsed = time.monotonic() - start

        assert elapsed < 2.0

    def test_cancel_event_never_set_lets_a_fast_command_complete_normally(self) -> None:
        cancel_event = threading.Event()

        result = run_cancelable(
            [sys.executable, "-c", "print('not cancelled')"],
            timeout_seconds=10,
            cancel_event=cancel_event,
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "not cancelled"


class TestTimeout:
    def test_exceeding_timeout_raises_timeout_expired_and_kills_the_process(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "pid.txt"
        script = _pid_writing_sleep_script(pid_file, sleep_seconds=30)

        start = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            run_cancelable(
                [sys.executable, "-c", script],
                timeout_seconds=0.5,
                poll_interval_seconds=0.1,
            )
        elapsed = time.monotonic() - start

        # Should time out close to the requested budget, not the full 30s
        # the script asked to sleep for.
        assert elapsed < 3.0

        assert pid_file.exists(), "subprocess never started / never wrote its PID"
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2.0
        while _is_process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _is_process_alive(pid), f"process {pid} was not actually killed"

    def test_timeout_expired_exception_carries_args_and_timeout(self) -> None:
        args = [sys.executable, "-c", "import time; time.sleep(30)"]
        with pytest.raises(subprocess.TimeoutExpired) as excinfo:
            run_cancelable(args, timeout_seconds=0.3, poll_interval_seconds=0.1)

        assert excinfo.value.cmd == args
        assert excinfo.value.timeout == 0.3
