"""Make the Home Assistant test harness run natively on Windows.

Home Assistant only supports Linux, and three things stop its pytest plugin from
importing on Windows: ``homeassistant.runner`` imports ``fcntl``,
``homeassistant.util.resource`` imports ``resource``, and the plugin blocks
``socket.socket`` while asyncio's Windows proactor loop needs a loopback socket
pair for its self-pipe. This script writes three small shims into a venv's
site-packages so all of that works. The shims live in the venv, never in the
integration, and CI on Linux runs the real thing.

Usage (from the repo root, after installing requirements_test.txt into the venv):

    .venv-win/Scripts/python.exe tools/setup_windows_tests.py .venv-win
"""

from __future__ import annotations

import sys
from pathlib import Path

FCNTL = '''"""Windows shim for the POSIX fcntl module (see tools/setup_windows_tests.py)."""

LOCK_SH = 1
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def flock(fd, operation):
    return None


def lockf(fd, cmd, len=0, start=0, whence=0):
    return None


def fcntl(fd, cmd, arg=0):
    return 0
'''

RESOURCE = '''"""Windows shim for the POSIX resource module (see tools/setup_windows_tests.py)."""

RLIMIT_NOFILE = 7
RLIM_INFINITY = -1


def getrlimit(res):
    return (8192, 8192)


def setrlimit(res, limits):
    return None
'''

SITECUSTOMIZE = '''"""Windows shim: give asyncio a socketpair that bypasses pytest-socket.

pytest-homeassistant-custom-component replaces socket.socket with a guarded class
during every test. On Windows asyncio's proactor loop builds its self-pipe from a
loopback socket pair, so every test would error before it starts. Capture the real
socket class at interpreter start and use it for that one pair; everything else
stays guarded. Written by tools/setup_windows_tests.py.
"""

import socket as _socket_mod
import sys

if sys.platform == "win32":
    _RealSocket = _socket_mod.socket

    def _socketpair(family=None, type=_socket_mod.SOCK_STREAM, proto=0):
        if family is None:
            family = _socket_mod.AF_INET
        host = "127.0.0.1" if family == _socket_mod.AF_INET else "::1"
        lsock = _RealSocket(family, type, proto)
        try:
            lsock.bind((host, 0))
            lsock.listen()
            addr, port = lsock.getsockname()[:2]
            csock = _RealSocket(family, type, proto)
            try:
                csock.setblocking(False)
                try:
                    csock.connect((addr, port))
                except (BlockingIOError, InterruptedError):
                    pass
                csock.setblocking(True)
                fd, _ = lsock._accept()
                ssock = _RealSocket(family, type, proto, fileno=fd)
            except Exception:
                csock.close()
                raise
        finally:
            lsock.close()
        return ssock, csock

    _socket_mod.socketpair = _socketpair
'''


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    venv = Path(argv[1])
    site = venv / "Lib" / "site-packages"
    if not site.is_dir():
        print(f"not a Windows venv: {site} missing")
        return 1
    for name, body in (
        ("fcntl.py", FCNTL),
        ("resource.py", RESOURCE),
        ("sitecustomize.py", SITECUSTOMIZE),
    ):
        (site / name).write_text(body, encoding="utf-8")
        print(f"wrote {site / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
