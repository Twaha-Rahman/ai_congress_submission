"""Local process supervisor for the three-service demo stack.

Used by ``make local-up`` and by the demo runner when no healthy stack is found.
Docker Compose remains the packaged deployment path (``make up``).

    .venv/bin/python scripts/stack.py up|down|status|ensure
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import load_dotenv  # noqa: E402

RUNTIME = ROOT / "runtime"
PIDS = RUNTIME / "pids"
LOGS = RUNTIME / "logs"
SERVICES = {
    "dhaka": {
        "module": "meridian.office_api.main",
        "port": 8081,
        "env": {
            "REGION": "DHAKA",
            "PORT": "8081",
            "DB_PATH": "runtime/dhaka/meridian.db",
            "SOURCE_DIR": "runtime/dhaka/sources",
            "KEY_DIR": "runtime/keys/dhaka",
        },
    },
    "frankfurt": {
        "module": "meridian.office_api.main",
        "port": 8082,
        "env": {
            "REGION": "FRANKFURT",
            "PORT": "8082",
            "DB_PATH": "runtime/frankfurt/meridian.db",
            "SOURCE_DIR": "runtime/frankfurt/sources",
            "KEY_DIR": "runtime/keys/frankfurt",
        },
    },
    "gateway": {
        "module": "meridian.gateway_api.main",
        "port": 8080,
        "env": {
            "PORT": "8080",
            "DHAKA_BASE_URL": "http://127.0.0.1:8081",
            "FRANKFURT_BASE_URL": "http://127.0.0.1:8082",
            "GATEWAY_RUNTIME_DIR": "runtime/gateway",
        },
    },
}


class StackError(RuntimeError):
    pass


def _python() -> Path:
    candidate = ROOT / ".venv" / "bin" / "python"
    if not candidate.exists():
        raise StackError("project virtualenv missing; run `make setup` first")
    return candidate


def _health(port: int, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=timeout
        ) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    return None


def _pid_file(name: str) -> Path:
    return PIDS / f"{name}.pid"


def _read_pid(name: str) -> int | None:
    path = _pid_file(name)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def status() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, spec in SERVICES.items():
        health = _health(spec["port"])
        pid = _read_pid(name)
        result[name] = {
            "port": spec["port"],
            "healthy": health is not None,
            "pid": pid if pid and _alive(pid) else None,
            "health": health,
        }
    return result


def _ensure_dirs() -> None:
    PIDS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    for name in SERVICES:
        (RUNTIME / name / "sources").mkdir(parents=True, exist_ok=True)
    for name in ("dhaka", "frankfurt"):
        (RUNTIME / "keys" / name).mkdir(parents=True, exist_ok=True)


def up(started_by_us: bool = True) -> None:
    _ensure_dirs()
    load_dotenv()
    for name, spec in SERVICES.items():
        if _health(spec["port"]) is not None:
            print(f"{name:<9} already healthy on :{spec['port']}")
            continue
        pid = _read_pid(name)
        if pid and _alive(pid):
            raise StackError(
                f"{name} process {pid} exists but :{spec['port']} is not healthy; "
                f"see {LOGS / (name + '.log')}"
            )
        env = os.environ.copy()
        env.update(spec["env"])
        log_path = LOGS / f"{name}.log"
        with open(log_path, "ab") as log:
            process = subprocess.Popen(
                [_python().__str__(), "-m", spec["module"]],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _pid_file(name).write_text(str(process.pid))
        print(f"{name:<9} starting (pid {process.pid}, :{spec['port']})")

    for name, spec in SERVICES.items():
        deadline = time.time() + 30
        while time.time() < deadline:
            if _health(spec["port"]) is not None:
                break
            pid = _read_pid(name)
            if pid and not _alive(pid):
                raise StackError(
                    f"{name} exited during startup; last log lines:\n"
                    + _tail(LOGS / f"{name}.log")
                )
            time.sleep(0.2)
        else:
            raise StackError(
                f"{name} did not become healthy on :{spec['port']}; last log lines:\n"
                + _tail(LOGS / f"{name}.log")
            )
    print("stack ready: dhaka :8081, frankfurt :8082, gateway :8080")


def _tail(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return "(no log)"
    return "\n".join(path.read_text("utf-8", errors="replace").splitlines()[-lines:])


def down() -> None:
    for name in SERVICES:
        pid = _read_pid(name)
        if pid and _alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = time.time() + 8
            while time.time() < deadline and _alive(pid):
                time.sleep(0.1)
            if _alive(pid):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except OSError:
                    pass
        try:
            _pid_file(name).unlink()
        except OSError:
            pass
        print(f"{name:<9} stopped")


def ensure() -> None:
    """Start the local stack only when a service is not already healthy."""

    states = status()
    if all(item["healthy"] for item in states.values()):
        return
    occupied = [
        name
        for name, item in states.items()
        if not item["healthy"] and _port_busy(SERVICES[name]["port"])
    ]
    if occupied:
        raise StackError(
            "port(s) already in use but not healthy: "
            + ", ".join(f"{name}:{SERVICES[name]['port']}" for name in occupied)
            + ". Stop the other stack (`make down`) or free the ports."
        )
    up()


def _port_busy(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "status"
    if action == "up":
        up()
    elif action == "down":
        down()
    elif action == "ensure":
        ensure()
    elif action == "status":
        print(json.dumps(status(), indent=2, sort_keys=True))
    else:
        print(f"unknown action {action!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except StackError as exc:
        print(f"stack error: {exc}", file=sys.stderr)
        raise SystemExit(1)
