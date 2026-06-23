# matlab-profile

A measurement-only MATLAB profiling harness: it configures the profiler, runs code under
instrumentation, exports results to `profile.json`, and analyzes them. It does not modify user code.

## What it does

Investigates a performance question across one or more profiler passes, then reports.

- Profiles for time (function and per-line hotspots), memory (`-memory on`), call patterns, and
  parallelism (wall vs CPU time), choosing profiler options to match the concern.
- Iterates autonomously: reads each pass for signals (history-buffer overflow, unexplained line
  attribution, a wall/CPU gap) and reruns with the right settings, reporting once the picture is
  complete.
- Keeps a corpus of runs. Each is serialized to self-describing JSON (profiler settings and wall
  time), cataloged for before/after comparison, and saved as HTML for human review.
- Ships analysis scripts to rank functions, break down lines, and diff runs, plus a MATLAB helper
  for call-pattern queries.
- Writes off-profiler benchmarks (`timeit`) to compare the user's code against alternatives, so
  recommendations are measured, not asserted.

See `SKILL.md` for the workflow the agent follows.

## Supported environment

Targets MATLAB R2025 and later. The skill relies on R2025-era profiler behavior, some of it
undocumented: `-detail builtin`, the `-memory on` field names (`TotalMemAllocated` /
`TotalMemFreed`), and the profiler-status defaults recorded in `references/PROFILER_REFERENCE.md`.
It is not verified against earlier releases, where option names and defaults differ; behavior there
is unknown. This is narrower than the toolkit's general baseline; the focus is R2025+ because
that is the environment in use, and broader-release support is future work.

## Known limitations

Memory measurement depends entirely on the profiler's `-memory on` mode (`PeakMem`,
`TotalMemAllocated`, `TotalMemFreed` per function), with no fallback:

- No `whos`-based workspace snapshot: no measure of total memory held by workspace variables,
  and no before/after delta around the workload.
- No OS-level resident-set-size (RSS) sampling and no Java-heap query.
- No graceful degradation: if `-memory on` is unavailable or returns no memory fields on a
  platform, the memory pass yields empty memory columns rather than detecting the gap and falling
  back.

`-memory on` is itself undocumented and may be unreliable on some platforms, so wherever it does not
work the skill has no memory story. The profiler-overhead figures in
`references/PROFILER_REFERENCE.md` were measured on Apple Silicon / R2025b and are indicative only
elsewhere.

## Possible future work

- A `whos`-based total-memory baseline and before/after delta, portable across releases and
  platforms.
- Graceful degradation: when `-memory on` returns no memory fields, fall back to the `whos` delta
  and say so.
- OS-level RSS sampling as a last-resort memory measure.
- Verification against earlier MATLAB releases, adjusting for the option and default differences.
