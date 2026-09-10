"""Take a census of a database, or compare two censuses.

Read-only. Nothing in this script writes to a database, so it is safe to point
at production.

    # Before the migration, against the source (uses DATABASE_URL):
    python -m scripts.db_inventory snapshot --out before.json

    # After, against the target:
    python -m scripts.db_inventory snapshot \
        --url "mysql+asyncmy://user:pass@host/db" --out after.json

    # Then:
    python -m scripts.db_inventory compare before.json after.json

``compare`` exits 1 when the two disagree, so it can gate a cutover script.

``--url`` is accepted so the target can be checked without editing the running
application's environment. It is read from the argument and never echoed —
neither the report nor any error message contains it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.inventory import collect, compare


async def _snapshot(url: str) -> dict:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await collect(session)
    finally:
        await engine.dispose()


def _run_snapshot(args: argparse.Namespace) -> int:
    url = args.url or get_settings().database_url
    try:
        report = asyncio.run(_snapshot(url))
    except Exception as exc:  # noqa: BLE001 - the message may quote the DSN
        # Deliberately not `raise`: a driver's connection error embeds the host,
        # the user and sometimes the password, and this output gets pasted into
        # tickets. The class name is enough to tell a bad DSN from a bad query.
        print(f"error: could not read the database ({type(exc).__name__})", file=sys.stderr)
        return 2

    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(serialized, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(serialized)

    print(f"\n{sum(report['tables'].values())} rows across {len(report['tables'])} tables")
    return 0


def _run_compare(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))

    problems = compare(before, after)
    if not problems:
        print("OK — the two databases hold the same data.")
        return 0

    print(f"{len(problems)} problem(s) found:\n", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="Census one database.")
    snapshot.add_argument("--url", help="Override DATABASE_URL (never logged).")
    snapshot.add_argument("--out", help="Write JSON here instead of stdout.")
    snapshot.set_defaults(func=_run_snapshot)

    comparison = sub.add_parser("compare", help="Diff two censuses.")
    comparison.add_argument("before")
    comparison.add_argument("after")
    comparison.set_defaults(func=_run_compare)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
