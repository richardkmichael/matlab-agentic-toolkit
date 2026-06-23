#!/usr/bin/env python
"""Compare two MATLAB profile runs, by function time or by allocated memory.

By default the summary line is the top-level WallTime delta (the tic/toc around
the workload), followed by a before/after table of inclusive TotalTime per
function with the delta and percentage change. With --by memory it compares
AllocatedMemory per function (in MB) and summarizes total allocation and peak;
this requires both runs to have been profiled with -memory on. Reads two
profile.json files produced by the MATLAB-side export in
scripts/export_profile_json.m.

Usage:
    compare_runs.py <before.json> <after.json> [--top N] [--by time|memory]
"""

import argparse
import json
import sys
from itertools import chain

MB = 1e6


def pct(delta, base):
    return 100 * delta / base if base > 0 else 0


def load_profile(path):
    # Return the whole profile dict so callers can read top-level fields
    # (WallTime) as well as the per-function table.
    with open(path) as f:
        return json.load(f)


def function_map(profile):
    return {fn["FunctionName"]: fn for fn in profile["Functions"]}


def change_label(before, after):
    if before > 0 and after > 0:
        return f"{pct(after - before, before):+.1f}%"
    if after > 0:
        return "new"
    if before > 0:
        return "gone"
    return ""


def compare_time(prev, curr, top):
    prev_fns = function_map(prev)
    curr_fns = function_map(curr)
    names = sorted(set(prev_fns) | set(curr_fns),
                   key=lambda n: -curr_fns.get(n, {}).get("TotalTime", 0))

    # The summary line reports the top-level WallTime (the tic/toc around the
    # workload), the one wall-clock number that is not double-counted.
    # Per-function TotalTime is inclusive, so summing the whole table multiplies
    # time by call depth. The table rows below keep inclusive TotalTime, but the
    # total must not be a sum of it.
    prev_wall = prev.get("WallTime")
    curr_wall = curr.get("WallTime")
    if prev_wall is not None and curr_wall is not None:
        delta = curr_wall - prev_wall
        print(f"Wall time: {prev_wall:.3f}s -> {curr_wall:.3f}s "
              f"(delta {delta:+.3f}s, {pct(delta, prev_wall):+.1f}%)")
    else:
        print("Wall time: unavailable (a profile predates the WallTime field)")
    print()
    print(f"{'function':<30}  {'before':>10}  {'after':>10}  {'delta':>10}  {'change':>8}")
    for name in names[:top]:
        b = prev_fns.get(name, {}).get("TotalTime", 0)
        a = curr_fns.get(name, {}).get("TotalTime", 0)
        print(f"{name:<30}  {b:>10.3f}  {a:>10.3f}  {a - b:>+10.3f}  {change_label(b, a):>8}")


def compare_memory(prev, curr, top):
    prev_fns = function_map(prev)
    curr_fns = function_map(curr)
    if not any("AllocatedMemory" in fn for fn in chain(prev_fns.values(), curr_fns.values())):
        print("No memory data in profiles (run both with -memory on)", file=sys.stderr)
        sys.exit(1)

    def alloc(d, n):
        return d.get(n, {}).get("AllocatedMemory", 0)

    names = sorted(set(prev_fns) | set(curr_fns),
                   key=lambda n: -max(alloc(prev_fns, n), alloc(curr_fns, n)))

    # AllocatedMemory is inclusive, so the outermost frame already holds the run
    # total; take the max across functions rather than summing, which would
    # multiply by call depth. PeakMem is summarised the same way. Verified
    # empirically: a thin wrapper that only calls an allocating leaf reports the
    # leaf's full allocation, not zero.
    def compare_total(field):
        prev_val = max((fn.get(field, 0) for fn in prev_fns.values()), default=0)
        curr_val = max((fn.get(field, 0) for fn in curr_fns.values()), default=0)
        delta = curr_val - prev_val
        return prev_val, curr_val, delta, pct(delta, prev_val)

    prev_alloc, curr_alloc, d_alloc, apct = compare_total("AllocatedMemory")
    prev_peak, curr_peak, d_peak, ppct = compare_total("PeakMem")
    print(f"Total allocated (inclusive): {prev_alloc / MB:.1f} MB -> {curr_alloc / MB:.1f} MB "
          f"(delta {d_alloc / MB:+.1f} MB, {apct:+.1f}%)")
    print(f"Peak (max function):         {prev_peak / MB:.1f} MB -> {curr_peak / MB:.1f} MB "
          f"(delta {d_peak / MB:+.1f} MB, {ppct:+.1f}%)")
    print()
    print(f"{'function':<30}  {'before_MB':>10}  {'after_MB':>10}  {'delta_MB':>10}  {'change':>8}")
    for name in names[:top]:
        b = alloc(prev_fns, name) / MB
        a = alloc(curr_fns, name) / MB
        print(f"{name:<30}  {b:>10.1f}  {a:>10.1f}  {a - b:>+10.1f}  {change_label(b, a):>8}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="Path to baseline profile.json")
    parser.add_argument("after", help="Path to current profile.json")
    parser.add_argument("--top", type=int, default=20, help="How many to show (default 20)")
    parser.add_argument("--by", choices=["time", "memory"], default="time",
                        help="Compare by inclusive time (default) or allocated memory")
    args = parser.parse_args()

    prev = load_profile(args.before)
    curr = load_profile(args.after)
    if args.by == "memory":
        compare_memory(prev, curr, args.top)
    else:
        compare_time(prev, curr, args.top)


if __name__ == "__main__":
    main()
