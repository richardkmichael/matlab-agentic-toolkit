---
name: matlab-profile
description: >
  Investigate MATLAB performance problems: time hotspots, memory consumption,
  parallelism, call patterns. Configures the profiler, runs code under
  instrumentation, analyzes results across multiple passes, and reports
  findings with automatic before/after comparison. Use this skill when the
  user says "profile", "matlab profile", "why is this slow", "memory usage",
  "hotspot", "performance", "where is time going", "bottleneck", or invokes
  /matlab-profile. Also use when the user asks to optimize MATLAB code and
  you need to measure before changing.
argument-hint: "[target] [file.m]"
allowed-tools: Bash(matlab *) Bash(python *) Bash(mkdir *) Read Write Glob Grep
license: "MathWorks BSD-3-Clause"
metadata:
  version: "1.0"
---

# MATLAB Performance Investigation

Investigate performance problems in the user's MATLAB code. The profiler is a
diagnostic tool; choose the right options and passes based on what you are
trying to learn. Iterate to build a complete picture, then report findings.
Do the investigation; the user decides what to change.

Read `${CLAUDE_SKILL_DIR}/references/PROFILER_REFERENCE.md` at the start of
every investigation for profiler options, output struct schema, and
interpretation rules.

## Tools

All scripts are in `${CLAUDE_SKILL_DIR}/scripts/`. Invoke them directly; they
are executable.

Analysis (take `profile.json`):
- `rank_functions.py <profile.json> [--top N] [--by time|memory|calls] [--filter SUBSTR]`
- `line_breakdown.py <profile.json> [<function>] [--top N] [--lines M] [--by time|memory]`
- `compare_runs.py <before.json> <after.json> [--top N] [--by time|memory]`

MATLAB-side helpers. Call them from the profiler driver script (Phase 2) or a
single-line `matlab -batch "run('...')"`; a pasted multi-line `-batch` body
fails. The helpers:
- `export_profile_json.m`: function
  `export_profile_json(info, status, wallTime, outPath)`, serialises
  `profile('info')` to JSON, embedding the `profile('status')` settings under
  `Settings` and the wall time under `WallTime`.
- `history_query.m`: function `events = history_query(profileMatPath[, fnNames])`,
  flattens FunctionHistory for call-pattern analysis.

Catalog (writes `profile_runs/index.json` + `last`):
- `profile_run.py record start <slug>`: allocate the next `<slug>_NNN`, create
  `profile_runs/<slug>_NNN/`, and print the run directory. Resolves the sequence
  against both the index and existing run dirs; never overwrites.
- `profile_run.py record stop <run_dir> --target T --label L --concern C`: read
  `<run_dir>/profile.json` for settings and wall time, append (or replace) the
  index entry, and advance `last`.

Reads of `index.json`/`last` stay agent-direct (parse the JSON yourself); only
the writes go through `profile_run.py`.

`profile.json` shape (the names the analysis scripts read, and what to use when
hand-querying it): top-level `Functions` (array), plus `Settings`, `WallTime`,
`ClockPrecision`, `ClockSpeed`, `NumFunctions`. Each `Functions` entry has
`FunctionName`, `FileName`, `Type`, `NumCalls`, `TotalTime`, `PartialData`, and
`ExecutedLines` (`[{line, hits, time}]`, gaining `allocated`/`freed`/`peak` under
`-memory on`); with `-memory on` the entry also carries `PeakMem`,
`AllocatedMemory`, `FreedMemory`. These are the exporter's JSON names; the live
`profile('info')` struct instead uses `FunctionTable` and
`TotalMemAllocated`/`TotalMemFreed` (see `references/PROFILER_REFERENCE.md`).

## Constraints

- Do NOT apply changes to the user's code; the user decides what to change and
  applies it. Profiling, reporting findings, and recommending changes are all in
  scope, including writing scratch benchmarks (`bench_<name>.m`) to back a
  recommendation. Keep instrumentation and alternatives in scratch files or
  copies, and revert anything you add to the user's files.
- Do NOT hardcode project-specific function names or fixture paths.
- Do NOT fabricate profiler options. If unsure whether an option exists, probe
  with `profile('status')` first.

## Run management

All profile artefacts go in a working directory:

```
profile_runs/
├── .gitignore          ← `*`; record start drops it so git ignores the catalog
├── index.json
├── last                ← text file containing the most recent run ID
├── Foo_001/
│   ├── run_profile.m   ← profiler driver: setup, <USER_CODE>, export
│   ├── profile.json
│   ├── profile.mat
│   └── profile_html/
└── Foo_002/
    └── ...
```

### Index entry format

```json
{
  "id": "Foo_001",
  "target": "Foo.m",
  "label": "initial time profile",
  "timestamp": "2026-04-16T16:23:00",
  "settings": {
    "DetailLevel": "builtin",
    "Timer": "performance",
    "HistoryTracking": "timestamp",
    "HistorySize": 20000000
  },
  "concern": "time",
  "wall_time": 12.345
}
```

`settings` is a copy of the run's profiler settings, written by
`profile_run.py record stop` (never by hand) from that run's `profile.json`
`Settings`. The two share one shape, so the tool copies it verbatim
instead of reformatting. Duplicated here for run comparison without
opening each `profile.json`; `profile.json` is the source of truth.

### Rules

1. At invocation start, load `index.json` if it exists and read `last` to
   find the baseline for comparison. These are agent-direct reads: parse the
   JSON yourself; only writes go through `profile_run.py`.
2. Derive the run slug per "Run ID naming" below: a name that captures what
   distinguishes this run. Do not append the sequence number yourself.
3. Allocate the run directory: `profile_run.py record start <slug>`. It
   resolves the next sequence against both the index and existing
   `profile_runs/<slug>_*` directories, creates the directory (never
   overwriting), and prints the path. Capture that path as `RUN_DIR`.
4. Derive a short human-readable label from the user's prompt.
5. Run the profiler fragment (Phase 2), writing artefacts into `RUN_DIR`.
6. Record the run: `profile_run.py record stop <RUN_DIR> --target <target>
   --label <label> --concern <concern>`. It reads settings and wall time from
   `<RUN_DIR>/profile.json`, writes the index entry, and advances `last`. Do
   not edit `index.json` or `last` by hand.
7. To start fresh without comparison, the user deletes `last`. To compare
   against a specific older run, the user edits `last` or says so explicitly.

#### Run ID naming

The run ID should identify what makes this run distinct, not just the
top-level entry point. If the user repeatedly profiles the same entry point
with different inputs, naming by entry point gives `runSimulation_001`,
`runSimulation_002`, ... (uninformative). Name by what varies.

Rules:

- If the user invokes with a specific function or file target (e.g.,
  `/matlab-profile function foo in Bar.m`): use the function/file as the
  slug (`foo_001`).
- If the user profiles an entry point with a specific dataset or fixture
  (e.g., "profile the analysis on sampleData.mat", "profile with the large
  input set"): use the dataset/fixture as the slug (`sampleData_001`,
  `largeInput_001`), not the entry point.
- If the user describes a mode or scenario ("profile in GPU mode",
  "profile with memory tracking"): use the mode/scenario (`gpu_001`,
  `memtrack_001`).
- If nothing clearly varies and the user just wants to profile the main
  entry point: fall back to the entry point name.

When multiple things vary (dataset AND mode), combine: `sampleData_gpu_001`.
Err toward informative over short. If unsure what's distinctive, ask the
user briefly before naming: "I'll name this run `<id>`. Does that fit
how you'll distinguish it from other runs?"

## Phase 1: Understand the concern and plan the investigation

The user's prompt tells you what to investigate. Arguments are in `$ARGUMENTS`. Common forms:

- `/matlab-profile function foo_bar in Foo.m`: profile a specific function.
  Read the file, find the function, wrap a call to it under the profiler.
  Ask for representative inputs if you cannot infer them.
- `/matlab-profile lines 100-200 in Bar.m`: profile a specific code region.
  Extract the lines, wrap them with necessary setup.
- `/matlab-profile Foo.m`: profile a script or main function.
- `/matlab-profile svd(rand(500))`: profile a standalone expression.
- `/matlab-profile` (no arguments): ask the user what to investigate.

If the invocation specifies the target, proceed directly. Ask only when you
genuinely need more information.

Identify the concern from the user's prompt and choose profiler settings:

| Concern                        | Profiler settings                              | Analysis focus                           |
|--------------------------------|------------------------------------------------|------------------------------------------|
| "slow", "time", "hotspot"      | -detail builtin, -historysize 2e7              | TotalTime ranking, per-line timing       |
| "memory", "allocation", "leak" | -detail builtin, -historysize 2e7, -memory on  | Allocated/peak per function and per line |
| "parallel", "CPU utilization"  | Two runs: -timer performance then -timer cpu   | Compare wall-clock vs CPU time           |
| "call pattern", "why called"   | -detail builtin, -historysize 2e7, -timestamp  | FunctionHistory entry/exit trace         |
| General "profile this"         | -detail builtin, -historysize 2e7              | Broad first pass; follow what stands out |

When the concern is unclear, start with a broad time pass. Anomalies in the
first pass (wall ≫ CPU, unexpectedly high call counts) suggest what to probe
next.

Ask about expected runtime. Confirm before launching anything over 120 seconds.

### Handling short workloads

On a fast target the profiler and the clock answer different questions, and
conflating them is what distorts the numbers. The profiler tells you WHERE the
time goes; for a sub-second target its per-call overhead dominates the absolute
timing (observed: ~5x inflation for tiny ops), though it still preserves relative
ordering within one profile. So profile for attribution, and time with `timeit`.

For attribution, wrap the target in a reps loop so the profiler collects enough
samples (note the reps count):

```matlab
for rep = 1:10
    <USER_CODE>;
end
```

For the headline timing, use `timeit` (or `gputimeit` for GPU code) instead of
the profiler or a hand-rolled `tic`/`toc` loop. `timeit` warms up the target,
calls it as many times as needed, and returns the median, exactly the
warmup-and-averaging the reps loop only approximates:

```matlab
t = timeit(@() <USER_CODE>);        % seconds, median over many runs
% GPU: gputimeit(@() <USER_CODE>), also handles wait(gpuDevice) sync
```

## Phase 2: Run the profiler

`RUN_DIR` is the directory printed by `profile_run.py record start <slug>`
(Run management, Rule 3). Write a profiler driver script into `RUN_DIR`, then run
it with `matlab -batch "run('<RUN_DIR>/run_profile.m')"`. Do NOT paste the
multi-line body inline into `-batch "..."`: MATLAB rejects a multi-line argument
with "No MATLAB command specified for -batch command line argument"; the
`run('<file>')` form is reliable. The driver adds paths, configures the profiler,
runs the code, calls `export_profile_json` to write the JSON, and saves the
artefacts into `RUN_DIR`. Run `profile_run.py record stop` afterward (Rule 6).

Write this to `<RUN_DIR>/run_profile.m`, substituting `${CLAUDE_SKILL_DIR}`,
`<USER_CODE>`, and `<RUN_DIR>`:

```matlab
addpath(genpath('.'));
addpath('${CLAUDE_SKILL_DIR}/scripts');
profile clear;
profile('on', '-detail', 'builtin', '-historysize', 2e7);
t0 = tic;
<USER_CODE>;
walltime = toc(t0);
profile off;
info = profile('info');
status = profile('status');
fprintf('Wall time: %.3fs\n', walltime);
fprintf('FunctionTable rows: %d\n', numel(info.FunctionTable));
fprintf('FunctionHistory events: %d\n', size(info.FunctionHistory, 2));
export_profile_json(info, status, walltime, '<RUN_DIR>/profile.json');
save('<RUN_DIR>/profile.mat', 'info', 'status', '-v7.3');
profsave(info, fullfile(pwd, '<RUN_DIR>', 'profile_html'));
```

Then run it:

```shell
matlab -nodisplay -nodesktop -nosplash -batch "run('<RUN_DIR>/run_profile.m')"
```

When the pass finishes, `profsave` writes the HTML report and opens its home page
(`file0.html`) in your default browser. That auto-open is how the operator views the
report. Its final action is `web(['file:///' fullfile(dirname,'file0.html')],'-browser')`,
which launches the external browser even under `-batch`. Pass `profsave` an absolute path
via `fullfile(pwd, ...)`, not a relative `'<RUN_DIR>/profile_html'`: with a relative
`dirname` the URL parses as `/<dirname>/file0.html` and the open fails with a misleading
"file does not exist" error (the files are written either way).

For memory profiling, DO NOT append `-memory on` to a `profile('on', ...)` call. That errors with
"Only one profiler action is supported per call." Pass `-memory on` in a single call with the
other options instead; that both enables memory and starts the profiler, so no separate
`profile on` is needed:

```matlab
profile('-memory', 'on', '-detail', 'builtin', '-historysize', 2e7);
% ... user code ...
profile off;
```

The exporter captures memory fields (`PeakMem`, `TotalMemAllocated`,
`TotalMemFreed`) automatically when the struct contains them.

After the run: run `profile_run.py record stop <RUN_DIR> --target <target>
--label <label> --concern <concern>`, check FunctionHistory event count against
the historysize cap, check for errors or warnings, tell the user the run path.

## Phase 3: Analyze and iterate

Use the analysis scripts against the JSON. Examples:

```shell
# Top functions by inclusive time
${CLAUDE_SKILL_DIR}/scripts/rank_functions.py profile_runs/Foo_001/profile.json --top 15

# Only functions whose name matches a substring (comma-separated, case-insensitive)
${CLAUDE_SKILL_DIR}/scripts/rank_functions.py profile_runs/Foo_001/profile.json --filter sparse,mldivide

# Per-line breakdown of the hottest function
${CLAUDE_SKILL_DIR}/scripts/line_breakdown.py profile_runs/Foo_001/profile.json

# Per-line breakdown of a specific function
${CLAUDE_SKILL_DIR}/scripts/line_breakdown.py profile_runs/Foo_001/profile.json myHotFunction

# Memory ranking by function (requires -memory on)
${CLAUDE_SKILL_DIR}/scripts/rank_functions.py profile_runs/Foo_001/profile.json --by memory

# Per-line memory: which lines allocate (requires -memory on)
${CLAUDE_SKILL_DIR}/scripts/line_breakdown.py profile_runs/Foo_001/profile.json --by memory

# Compare against baseline (time)
${CLAUDE_SKILL_DIR}/scripts/compare_runs.py profile_runs/Foo_001/profile.json \
                                            profile_runs/Foo_002/profile.json

# Compare allocation and peak between two runs (requires -memory on)
${CLAUDE_SKILL_DIR}/scripts/compare_runs.py profile_runs/Foo_001/profile.json \
                                            profile_runs/Foo_002/profile.json --by memory
```

For FunctionHistory call-pattern queries, run `history_query.m` via MATLAB:

```shell
matlab -nodisplay -nodesktop -nosplash -batch "addpath('${CLAUDE_SKILL_DIR}/scripts'); history_query('profile_runs/Foo_001/profile.mat', 'myHotFunction')"
```

Patterns to watch for:
- Functions with Type "Built-in" high in the ranking → time in LAPACK or runtime
- High NumCalls but low TotalTime → dispatch overhead, not algorithmic cost
- One or two lines dominating → pinpoint optimization targets
- ExecutedLines sum much less than TotalTime → hidden built-in cost (use -detail builtin)
- Large AllocatedMemory with small FreedMemory → potential accumulation or leak
- Wall time much larger than CPU time → I/O bound or waiting on external resources
- CPU time much larger than wall time → good BLAS parallelism

### When to look up a function

When an unfamiliar MATLAB function appears in the hotspot list, use the
`matlab-docs` skill to fetch its documentation. Use the docs to
understand what the function does, whether a better alternative
is recommended for the observed pattern (e.g., `griddedInterpolant` instead of
repeated `interp1` calls), and what options it supports.

### Benchmarking alternatives

When the hotspot is a specific MATLAB pattern, don't stop at reporting the
bottleneck; write a short off-profiler benchmark comparing the current
approach against plausible alternatives. Save as
`bench_<description>.m`. Verify outputs match before trusting
speedup numbers. This turns a report into an actionable recommendation.

Template:

```matlab
tA = timeit(@() <CURRENT>);   % median seconds, warmup handled
tB = timeit(@() <ALT1>);
tC = timeit(@() <ALT2>);
fprintf('A: %.3f ms, B: %.3f ms (%.1fx), C: %.3f ms (%.1fx)\n', ...
    tA*1e3, tB*1e3, tA/tB, tC*1e3, tA/tC);
```

Treat a speedup under 1.2x as noise rather than a win; below that, measurement
variance dominates.

### Comparing with the baseline

If `last` exists, compare automatically with `compare_runs.py` (add `--by memory`
for a memory concern, comparing allocation and peak instead of time). Report:

- Overall wall time delta (allocation and peak delta under `--by memory`)
- Functions that improved, regressed, appeared, or disappeared
- What code changed between runs, when known (the edits made since the baseline)
- Prominent flag if anything regressed

### Autonomous iteration

After each pass, examine the results for signals that demand a follow-up
pass. When a signal fires, run the next pass automatically (within the
check-in constraints below); do not stop and ask. The goal is a complete
picture by the time you report, not a ping-pong of "do you want me to
look at X?" questions.

Signals that trigger an automatic follow-up pass:

- History buffer filled → rerun with larger -historysize (same workload,
  bigger buffer).
- ExecutedLines sum significantly less than TotalTime and -detail builtin
  wasn't used → rerun with -detail builtin (same workload, more detail).
- Wall time much larger than CPU time, or CPU ≫ wall → run a parallelism
  pass (-timer cpu) to quantify what's happening.
- Time profile shows a hot function with many allocation-looking built-ins
  in its ExecutedLines (zeros, ones, repmat, cat, sparse in a loop; or
  high-call-count operations on growing arrays) → run a memory pass with
  -memory on to confirm and quantify.
- One function dominates (>70% of total time) and its internal line
  attribution doesn't explain where the time goes → snapshot-and-replay
  that function in isolation for a focused profile.
- User asked about memory but only time was run → run a memory pass.
- User asked about parallelism but only wall time was measured → run a
  CPU-time pass.
- Memory pass shows large allocations in a function that's also a time
  hotspot → you already have the cross-reference; just report it.

Check in with the user before proceeding automatically when:
- The next run will take more than 120 seconds.
- You've already run 2+ follow-up passes without the picture converging
  (means the evidence is ambiguous; the user should choose).
- Multiple signals fire at once and none dominates; picking which to
  chase first is a judgment call.

Report the chained passes in one consolidated final report, not piecewise
after each one. The user wanted an answer, not a blow-by-blow.

### Deciding between autonomous follow-up and asking

After an analysis pass surfaces multiple plausible next steps, decide
whether to pick one autonomously or ask the user first.

Proceed autonomously when one direction clearly dominates:
- The first pass already answers the user's question and the follow-ups
  are nice-to-have polish
- One signal in the data points unambiguously at a single next pass
  (e.g., history buffer overflowed: just rerun with a larger buffer;
  ExecutedLines sum doesn't match TotalTime: rerun with -detail builtin)
- The user's prompt was specific enough that the follow-up direction is
  obvious (they asked about memory and you only ran a time pass; go run
  the memory pass)

Ask the user when multiple directions are roughly equally promising and
none is implied by the prompt:
- Three or more possible follow-up passes each addressing a different
  dimension (time drill-down, memory, parallelism, call-pattern)
- The data shows multiple signals (e.g., both a time hotspot AND
  unexplained wall/CPU gap; either could be worth investigating first)
- A non-trivial scoping choice (which subfunction to snapshot for replay,
  which fixture to rerun with)

How to ask: present the options as a numbered list in the report's
"Next steps" section, with a short description of what each would reveal
and roughly how long it would take. Then stop and wait for the user to
pick one (or say "none" / "all" / something else). Do not invent a
decision just to keep moving.

If the user asked "why is this slow?", don't just report time hotspots;
check whether memory pressure, poor parallelism, or excessive call counts
are contributing. Follow the evidence.

## Phase 4: Report

1. Investigation summary: what was profiled, passes run, settings, wall time,
   buffer status, run path.
2. Findings table adapted to the measurement (time, memory, or comparison).
3. Before/after comparison prominently shown if a baseline existed.
4. Per-line detail for hotspots. Read the source at those lines and explain
   what the code is doing, not just report line numbers.
5. Surprises: anything the first pass didn't predict (built-in dominance,
   unexpected call counts, wall/CPU mismatch, history overflow, regressions
   in untouched functions).
6. Diagnosis: connect findings to the user's concern. Synthesize across passes.
7. Actionable next steps. Be specific about what to investigate or change.
   Include alternatives benchmarks when you ran them. Do not make code changes.
8. The HTML report opened automatically when the pass finished. Tell the user how to
   reopen it: "Open `profile_runs/<run_id>/profile_html/file0.html` in a browser."

### Explaining the numbers to the user

Profiler figures are per function and rolled up: each one already includes the
function's callees and is summed over all its calls (see "How the per-function
numbers aggregate" in `references/PROFILER_REFERENCE.md`). Say that plainly when it
matters, and use these terms:

- Time: TotalTime is inclusive (the function plus everything it called). The run's
  wall-clock is the single WallTime figure, not the sum of the table. A function's
  own cost is its self-time (inclusive time minus time spent in its children); say
  "self-time" when that is what you mean.
- Memory, two different things. Name both: allocated (and freed) is the cumulative
  total of bytes requested (or released) over the run, so it measures memory churn;
  peak is the most memory live at one instant, so it measures how much RAM the run
  needed. Allocated can far exceed peak when memory is reused, so do not present them
  as the same quantity.
- Run totals: the outermost function holds the whole-run figure for allocation,
  freed, and peak. Report that as the total; the largest function's number is the run
  total, not just one hotspot. Never sum a column to get a total.

## Cleanup

The `profile_runs/` directory accumulates across runs. Mention its
total size periodically. When the user is done, offer to clean up, but don't
delete without asking.
