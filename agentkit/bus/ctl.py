"""CLI lifecycle management for bus participants.

Provides start/stop/status/restart/log commands with PID file management.
Can be used as a standalone CLI or mixed into adapter scripts.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class ProcessCtl:
    """Manages a participant process lifecycle via PID files."""

    def __init__(self, name: str, script: str | Path, workdir: str | Path | None = None,
                 python: str | Path | None = None, logfile: str | Path | None = None,
                 pidfile: str | Path | None = None):
        self.name = name
        self.script = Path(script).resolve()
        self.workdir = Path(workdir).resolve() if workdir else self.script.parent
        self.python = Path(python) if python else self._find_python()
        self.logfile = Path(logfile) if logfile else self.workdir / f"{name}.log"
        self.pidfile = Path(pidfile) if pidfile else self.workdir / f"{name}.pid"

    def _find_python(self) -> Path:
        """Find the venv python in the workdir."""
        venv_python = self.workdir / ".venv" / "bin" / "python3"
        if venv_python.exists():
            return venv_python
        return Path(sys.executable)

    def get_pid(self) -> int | None:
        """Read PID from file, return None if not found or stale."""
        if not self.pidfile.exists():
            return None
        try:
            pid = int(self.pidfile.read_text().strip())
            os.kill(pid, 0)  # check if alive
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            self.pidfile.unlink(missing_ok=True)
            return None

    def is_running(self) -> bool:
        return self.get_pid() is not None

    def start(self) -> int:
        """Start the process in background. Returns PID."""
        pid = self.get_pid()
        if pid:
            print(f"Already running (pid {pid})")
            return pid

        with open(self.logfile, "a") as log:
            proc = subprocess.Popen(
                [str(self.python), str(self.script)],
                cwd=str(self.workdir),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )

        self.pidfile.write_text(str(proc.pid))
        print(f"Started {self.name} (pid {proc.pid}) — log: {self.logfile}")
        return proc.pid

    def stop(self) -> bool:
        """Stop the process. Returns True if was running."""
        pid = self.get_pid()
        if not pid:
            print("Not running")
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 5s for graceful shutdown
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        self.pidfile.unlink(missing_ok=True)
        print(f"Stopped {self.name}")
        return True

    def restart(self) -> int:
        """Stop then start."""
        self.stop()
        time.sleep(1)
        return self.start()

    def status(self) -> None:
        """Print status."""
        pid = self.get_pid()
        if pid:
            print(f"Running (pid {pid})")
        else:
            print("Not running")

    def log(self, follow: bool = False, lines: int = 20) -> None:
        """Show log output."""
        if not self.logfile.exists():
            print("No log file")
            return

        if follow:
            os.execvp("tail", ["tail", "-f", str(self.logfile)])
        else:
            os.execvp("tail", ["tail", f"-{lines}", str(self.logfile)])


def run_ctl(name: str, script: str | Path, **kwargs) -> None:
    """Parse sys.argv and run the appropriate command. Drop-in for adapter-ctl scripts."""
    ctl = ProcessCtl(name=name, script=script, **kwargs)

    args = sys.argv[1:]
    cmd = args[0] if args else "status"

    if cmd == "start":
        ctl.start()
    elif cmd == "stop":
        ctl.stop()
    elif cmd == "restart":
        ctl.restart()
    elif cmd == "status":
        ctl.status()
    elif cmd == "log":
        follow = "-f" in args
        ctl.log(follow=follow)
    else:
        print(f"Usage: {sys.argv[0]} {{start|stop|restart|status|log [-f]}}")
        sys.exit(1)
