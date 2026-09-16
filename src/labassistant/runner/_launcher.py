"""Entry point executed *inside* the sandbox subprocess. Never imported by the main app.

It installs a Python audit hook before pytest imports the submission. Audit hooks
cannot be removed once added, so the submission cannot switch this guard off from
Python code. This is a guard against accidental or casual misuse, not a security
boundary: native code (e.g. via ctypes) could bypass it. A container is the real fix.
"""

import os
import resource
import sys

BLOCKED_EVENTS = (
    "socket.__new__",
    "socket.connect",
    "socket.bind",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "os.kill",
    "os.killpg",
    "ctypes.",
)


def _guard(event: str, args: tuple) -> None:
    if event.startswith(BLOCKED_EVENTS):
        raise PermissionError(f"'{event}' is not allowed in the sandbox")


def _apply_resource_limits() -> None:
    """Best effort: some limits are not supported on every OS (e.g. parts of macOS)."""
    limits = (
        (resource.RLIMIT_CPU, os.environ.get("LABASSISTANT_CPU_SECONDS")),
        (resource.RLIMIT_FSIZE, os.environ.get("LABASSISTANT_MAX_FILE_BYTES")),
    )
    for limit, value in limits:
        if value:
            try:
                resource.setrlimit(limit, (int(value), int(value)))
            except (ValueError, OSError):
                pass


def main() -> int:
    # Set limits here rather than via subprocess's preexec_fn, which is unsafe
    # when the parent process has threads (as the FastAPI server will).
    _apply_resource_limits()
    import pytest  # imported before the hook so pytest's own start-up is unaffected

    sys.addaudithook(_guard)
    return int(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
