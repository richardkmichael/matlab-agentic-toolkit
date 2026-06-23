#!/usr/bin/env python
"""Rank MATLAB profile functions by inclusive time.

Prints a table of the top-N functions sorted by TotalTime (inclusive), with
call count and per-call microseconds. Reads a profile.json produced by the
MATLAB-side export in scripts/export_profile_json.m.

Usage:
    rank_functions.py <profile.json> [--top N] [--by time|memory|calls] [--filter SUBSTR]
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_json", help="Path to profile.json")
    parser.add_argument("--top", type=int, default=15, help="How many to show (default 15)")
    parser.add_argument(
        "--by",
        choices=["time", "memory", "calls"],
        default="time",
        help="Sort key (default time)",
    )
    parser.add_argument(
        "--filter",
        metavar="SUBSTR",
        help="Keep only functions whose name contains any comma-separated "
        "substring (case-insensitive)",
    )
    args = parser.parse_args()

    with open(args.profile_json) as f:
        data = json.load(f)
    fns = data["Functions"]

    if args.filter:
        tokens = [t.strip().lower() for t in args.filter.split(",") if t.strip()]
        fns = [f for f in fns if any(t in f["FunctionName"].lower() for t in tokens)]
        if not fns:
            print(f"No functions match filter: {args.filter}", file=sys.stderr)
            sys.exit(1)

    if args.by in ("time", "calls"):
        time_first = args.by == "time"
        sort_field = "TotalTime" if time_first else "NumCalls"
        fns = sorted(fns, key=lambda f: -f[sort_field])
        if time_first:
            print(f"{'time(s)':>10}  {'calls':>9}  {'us/call':>12}  function")
        else:
            print(f"{'calls':>9}  {'time(s)':>10}  {'us/call':>12}  function")
        for fn in fns[: args.top]:
            c = int(fn["NumCalls"])
            us_per_call = 1e6 * fn["TotalTime"] / c if c else 0
            time_cell = f"{fn['TotalTime']:>10.3f}"
            calls_cell = f"{c:>9d}"
            lead = f"{time_cell}  {calls_cell}" if time_first else f"{calls_cell}  {time_cell}"
            print(f"{lead}  {us_per_call:>12.2f}  {fn['FunctionName']}")
    elif args.by == "memory":
        # Test field presence, not truthiness: a function that allocated nothing
        # has PeakMem == 0 but still carries memory data. A -memory on profile
        # carries all three memory fields together or none (see
        # references/PROFILER_REFERENCE.md); read alloc/freed with .get anyway so
        # a malformed or hand-edited profile cannot raise.
        mem_fns = [f for f in fns if "PeakMem" in f]
        if not mem_fns:
            print("No memory data in profile (run with -memory on)", file=sys.stderr)
            sys.exit(1)
        mem_fns = sorted(mem_fns, key=lambda f: -f.get("PeakMem", 0))
        print(f"{'peak(MB)':>10}  {'alloc(MB)':>10}  {'freed(MB)':>10}  function")
        for fn in mem_fns[: args.top]:
            print(
                f"{fn.get('PeakMem', 0)/1e6:>10.1f}  "
                f"{fn.get('AllocatedMemory', 0)/1e6:>10.1f}  "
                f"{fn.get('FreedMemory', 0)/1e6:>10.1f}  {fn['FunctionName']}"
            )


if __name__ == "__main__":
    main()
