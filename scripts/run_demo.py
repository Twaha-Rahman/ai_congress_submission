"""One-command rehearsal: clean reset, seed, and the three demo stories.

    .venv/bin/python scripts/run_demo.py --mode replay
    .venv/bin/python scripts/run_demo.py --mode cached
    .venv/bin/python scripts/run_demo.py --mode live

The local stack is started when needed.  Docker Compose users should run
``make down`` first because reset refuses to delete databases held by live services.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import load_dotenv  # noqa: E402
from scripts import stack  # noqa: E402


class RehearsalError(RuntimeError):
    pass


def run(script: str, *args: str, env: dict[str, str] | None = None) -> None:
    command = [sys.executable, str(ROOT / "scripts" / script), *args]
    print(f"\n$ {' '.join(Path(part).name if part.startswith('/') else part for part in command[1:])}")
    completed = subprocess.run(command, cwd=ROOT, env=env)
    if completed.returncode != 0:
        raise RehearsalError(f"{script} exited with status {completed.returncode}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("replay", "cached", "live"), default="replay")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--skip-demo2", action="store_true")
    parser.add_argument("--skip-demo3", action="store_true")
    args = parser.parse_args(argv[1:])

    load_dotenv()
    if args.mode == "live":
        model = os.environ.get("LLM_MODEL") or os.environ.get("DHAKA_LLM_MODEL")
        key = os.environ.get("LLM_API_KEY") or os.environ.get("DHAKA_LLM_API_KEY")
        if not model or not key:
            print(
                "live demo prerequisite missing: set LLM_MODEL and LLM_API_KEY (OpenRouter) "
                "in .env. No replay fallback is performed.",
                file=sys.stderr,
            )
            return 2

    if not (ROOT / ".venv" / "bin" / "python").exists():
        print("project virtualenv missing; run `make setup`", file=sys.stderr)
        return 2
    if not (ROOT / ".env").exists() or not (ROOT / "runtime" / "trusted_keys.json").exists():
        print("local configuration missing; running idempotent setup first")
        run("setup.py")

    # Stop local processes so reset can safely remove SQLite files.  A Compose stack
    # is not managed here; the reset script will refuse and ask for `make down`.
    stack.down()
    if not args.no_reset:
        run("reset_demo.py", "--yes")

    environment = os.environ.copy()
    environment["DEMO_EXTRACTION_MODE"] = "replay" if args.mode == "live" else args.mode

    if args.mode == "cached":
        run("build_cache.py")

    run("seed.py", "--mode", environment["DEMO_EXTRACTION_MODE"])
    run("demo1_catch.py", "--mode", args.mode)
    if not args.skip_demo2:
        run("demo2_trace.py")
    if not args.skip_demo3:
        run("demo3_border.py")

    print("\n" + "=" * 78)
    print(f"REHEARSAL COMPLETE ({args.mode})")
    print("=" * 78)
    print("full JSON evidence: evidence/")
    print("local services remain running; stop them with `make local-down`")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except RehearsalError as exc:
        print(f"rehearsal error: {exc}", file=sys.stderr)
        raise SystemExit(1)
