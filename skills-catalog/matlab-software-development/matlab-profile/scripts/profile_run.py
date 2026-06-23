#!/usr/bin/env python
"""Allocate and record MATLAB profile runs in profile_runs/index.json.

Records the start and end of a profiling run with deterministic catalog bookkeeping:

  record start <slug>     allocate the next <slug>_NNN run directory and print it
  record stop  <run_dir>  write that run's index entry and advance `last`

`start` runs before the MATLAB profiling fragment; it only creates the run
directory. `stop` runs after; it copies settings and wall time out of the run's
profile.json into the index. Reads of index.json / last stay agent-direct; this
tool owns only the writes.

Usage:
    profile_run.py record start <slug> [--runs-dir DIR]
    profile_run.py record stop <run_dir> --target T --label L --concern C
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

INDEX_NAME = "index.json"
LAST_NAME = "last"


def fail(message):
    """Print an error to stderr and exit non-zero."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def load_index(runs_dir):
    """Return the catalog entries as a list, or [] if the index is absent or empty."""
    index_path = runs_dir / INDEX_NAME
    if not index_path.is_file():
        return []
    text = index_path.read_text().strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        fail(f"{index_path} is not valid JSON: {e}")
    if isinstance(data, list):
        return data
    # Anything else is an unsupported or old-format catalog. Exit cleanly with
    # guidance rather than letting a later access raise; deleting the catalog
    # starts fresh.
    fail(f"{index_path} is not a list of run entries (unsupported or old-format "
         f"catalog). Delete {runs_dir} and rerun to start a fresh catalog.")


def write_index_atomic(runs_dir, entries):
    """Write entries to index.json via a temp file + atomic rename."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(runs_dir), prefix=".index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
        os.replace(tmp, str(runs_dir / INDEX_NAME))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parse_seq(name, slug):
    """Return the integer sequence in `<slug>_<NNN>`, or None if name is not one."""
    m = re.fullmatch(re.escape(slug) + r"_(\d+)", name)
    return int(m.group(1)) if m else None


def next_id(runs_dir, slug):
    """Allocate the next `<slug>_NNN` id, resolving the index and filesystem together."""
    seqs = []
    for entry in load_index(runs_dir):
        seq = parse_seq(str(entry.get("id", "")), slug)
        if seq is not None:
            seqs.append(seq)
    if runs_dir.is_dir():
        for child in runs_dir.iterdir():
            if child.is_dir():
                seq = parse_seq(child.name, slug)
                if seq is not None:
                    seqs.append(seq)
    seq = max(seqs) + 1 if seqs else 1
    # Defensive: never reuse a directory even if the index and filesystem drifted.
    while (runs_dir / f"{slug}_{seq:03d}").exists():
        seq += 1
    return f"{slug}_{seq:03d}"


def ensure_gitignore(runs_dir):
    """Keep the run catalog out of git; it is regenerable working data.

    Write `<runs_dir>/.gitignore` containing `*` so the whole catalog is ignored in
    whatever project the skill runs in. Idempotent; never overwrites an existing file.
    """
    gitignore = runs_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")


def cmd_start(args):
    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    ensure_gitignore(runs_dir)
    run_id = next_id(runs_dir, args.slug)
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    # Sole stdout line: the run directory, for the agent to use as RUN_DIR and
    # pass back to `record stop`.
    print(run_dir)


def cmd_stop(args):
    run_dir = Path(args.run_dir)
    runs_dir = run_dir.parent
    run_id = run_dir.name

    profile_path = run_dir / "profile.json"
    if not profile_path.is_file():
        fail(f"{profile_path} not found; run the profiler before recording stop")
    try:
        profile_json = json.loads(profile_path.read_text())
    except json.JSONDecodeError as e:
        fail(f"{profile_path} is not valid JSON: {e}")

    settings = profile_json.get("Settings")
    wall_time = profile_json.get("WallTime")
    if settings is None:
        print(f"warning: {profile_path} has no Settings; wrote null", file=sys.stderr)
    if wall_time is None:
        print(f"warning: {profile_path} has no WallTime; wrote null", file=sys.stderr)

    entry = {
        "id": run_id,
        "target": args.target,
        "label": args.label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "settings": settings,
        "concern": args.concern,
        "wall_time": wall_time,
    }

    # Replace any existing entry for this id so re-running stop is idempotent.
    entries = [e for e in load_index(runs_dir) if e.get("id") != run_id]
    entries.append(entry)
    write_index_atomic(runs_dir, entries)

    (runs_dir / LAST_NAME).write_text(run_id + "\n")
    print(run_id)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="bookend a profiling run")
    actions = record.add_subparsers(dest="action", required=True)

    start = actions.add_parser("start", help="allocate and create the run directory")
    start.add_argument("slug", help="run slug; the id becomes <slug>_NNN")
    start.add_argument(
        "--runs-dir", default="profile_runs", help="catalog directory (default: profile_runs)"
    )
    start.set_defaults(func=cmd_start)

    stop = actions.add_parser("stop", help="write the index entry for a finished run")
    stop.add_argument("run_dir", help="run directory printed by 'record start'")
    stop.add_argument("--target", required=True, help="what was profiled")
    stop.add_argument("--label", required=True, help="short human-readable label")
    stop.add_argument("--concern", required=True, help="time | memory | parallel | ...")
    stop.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
