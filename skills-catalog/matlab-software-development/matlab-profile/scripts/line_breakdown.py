#!/usr/bin/env python
"""Show per-line breakdown for a function in a MATLAB profile.

Prints lines sorted by time (or by allocated memory with --by memory), with hit
counts and per-hit microseconds. Reads ExecutedLines from the profile.json
export. When the profile was taken with -memory on, each line also carries
allocated/freed/peak bytes, which are shown automatically. If no function name
is given, shows the breakdown for the top-N functions.

Usage:
    line_breakdown.py <profile.json> [<function>] [--top N] [--lines M] [--by time|memory]
"""

import argparse
import json
import sys


def show_function(fn, max_lines, sort_by):
    executed_lines = fn.get("ExecutedLines") or []
    if not executed_lines:
        return False
    # The exporter writes the memory columns for every line or none, so the
    # first line settles it (executed_lines is non-empty here).
    has_mem = "allocated" in executed_lines[0]
    if sort_by == "memory" and has_mem:
        lines = sorted(executed_lines, key=lambda row: -row.get("allocated", 0))
    else:
        lines = sorted(executed_lines, key=lambda row: -row["time"])
    print(f"\n{fn['FunctionName']} -- {fn['TotalTime']:.3f}s, {fn['NumCalls']} calls")
    if has_mem:
        print(f"  {'line':>6}  {'hits':>9}  {'time(s)':>10}  "
              f"{'alloc(MB)':>11}  {'freed(MB)':>11}  {'peak(MB)':>10}")
        for row in lines[:max_lines]:
            print(f"  {row['line']:>6}  {row['hits']:>9}  {row['time']:>10.3f}  "
                  f"{row.get('allocated', 0)/1e6:>11.2f}  "
                  f"{row.get('freed', 0)/1e6:>11.2f}  {row.get('peak', 0)/1e6:>10.2f}")
    else:
        print(f"  {'line':>6}  {'hits':>9}  {'time(s)':>10}  {'us/hit':>10}")
        for row in lines[:max_lines]:
            us_per_hit = 1e6 * row["time"] / row["hits"] if row["hits"] else 0
            print(f"  {row['line']:>6}  {row['hits']:>9}  {row['time']:>10.3f}  "
                  f"{us_per_hit:>10.2f}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_json", help="Path to profile.json")
    parser.add_argument("function", nargs="?", help="Function name (default: top-N functions)")
    parser.add_argument("--top", type=int, default=5,
                        help="How many functions when no name given (default 5)")
    parser.add_argument("--lines", type=int, default=10,
                        help="Lines per function to show (default 10)")
    parser.add_argument("--by", choices=["time", "memory"], default="time",
                        help="Sort lines by time (default) or by allocated memory")
    args = parser.parse_args()

    with open(args.profile_json) as f:
        data = json.load(f)
    fns = data["Functions"]

    if args.function:
        matches = [fn for fn in fns if fn["FunctionName"] == args.function]
        if not matches:
            print(f"Function not found: {args.function}", file=sys.stderr)
            print("Available functions (by time):", file=sys.stderr)
            for fn in sorted(fns, key=lambda f: -f["TotalTime"])[:10]:
                print(f"  {fn['FunctionName']}", file=sys.stderr)
            sys.exit(1)
        if not show_function(matches[0], args.lines, args.by):
            print(f"No line-level data for {args.function}", file=sys.stderr)
            sys.exit(1)
    else:
        if args.by == "memory":
            sorted_fns = sorted(fns, key=lambda f: -f.get("PeakMem", 0))
        else:
            sorted_fns = sorted(fns, key=lambda f: -f["TotalTime"])
        shown = 0
        for fn in sorted_fns:
            if show_function(fn, args.lines, args.by):
                shown += 1
                if shown >= args.top:
                    break


if __name__ == "__main__":
    main()
