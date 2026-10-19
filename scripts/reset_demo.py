"""Local demo reset with guard rails.

Only the configured demo tenant and paths below ``runtime/`` are ever removed.
Signing keys, trusted public keys, fixtures and exported evidence are preserved.

    .venv/bin/python scripts/reset_demo.py            # interactive confirmation
    .venv/bin/python scripts/reset_demo.py --yes      # unattended (demo runner)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import load_dotenv  # noqa: E402

DEMO_TENANT = "meridian_demo"
RUNTIME = (ROOT / "runtime").resolve()


def _inside_runtime(path: Path) -> bool:
    try:
        path.resolve().relative_to(RUNTIME)
    except ValueError:
        return False
    return True


def _targets() -> list[Path]:
    return [
        ROOT / "runtime" / "dhaka" / "meridian.db",
        ROOT / "runtime" / "dhaka" / "sources",
        ROOT / "runtime" / "frankfurt" / "meridian.db",
        ROOT / "runtime" / "frankfurt" / "sources",
        ROOT / "runtime" / "gateway" / "relay.jsonl",
    ]


def _extra_suffixes(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm")]


def main(argv: list[str]) -> int:
    load_dotenv()
    tenant = __import__("os").environ.get("TENANT_ID", DEMO_TENANT)
    if tenant != DEMO_TENANT:
        print(
            f"refusing reset: TENANT_ID is {tenant!r}, not the demo tenant {DEMO_TENANT!r}",
            file=sys.stderr,
        )
        return 1

    # A live stack holds open SQLite handles; refuse rather than corrupt a demo.
    from scripts.stack import status

    live = [name for name, item in status().items() if item["healthy"]]
    if live:
        print(
            "refusing reset while services are healthy: " + ", ".join(live) +
            "; stop the stack first (`make local-down` or `make down`)",
            file=sys.stderr,
        )
        return 1

    targets = _targets()
    for target in targets:
        if not _inside_runtime(target):
            print(f"refusing reset: {target} is outside {RUNTIME}", file=sys.stderr)
            return 1

    if "--yes" not in argv:
        if not sys.stdin.isatty():
            print("refusing reset without --yes in a non-interactive shell", file=sys.stderr)
            return 1
        print("This will delete only demo databases, source copies and relay logs:")
        for target in targets:
            print(f"  {target.relative_to(ROOT)}")
        answer = input("Type 'reset' to continue: ").strip()
        if answer != "reset":
            print("reset cancelled")
            return 1

    removed = 0
    for target in targets:
        candidates = [target, *_extra_suffixes(target)]
        for candidate in candidates:
            if candidate.is_dir():
                shutil.rmtree(candidate)
                removed += 1
            elif candidate.exists():
                candidate.unlink()
                removed += 1
    print(f"reset complete: removed {removed} demo path(s)")
    print("preserved: signing keys, trusted keys, fixtures, evidence/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
