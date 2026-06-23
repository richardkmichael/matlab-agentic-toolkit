---
name: matlab-docs
description: >
  Look up MATLAB / MathWorks docs by function name, mathworks.com URL,
  or local help-HTML path. Resolves a function name to the correct doc
  page, checks MATLAB's locally installed docs first (offline, matched to
  the user's release), and returns the complete page as clean markdown.
  Triggers on "matlab docs", "mathworks docs", a pasted mathworks.com docs
  URL, a question about what arguments or options a function accepts, or
  any time you need to consult MATLAB documentation.
allowed-tools: Bash(*/extract_matlab_doc.py:*) Read
argument-hint: "[target]"
license: "MathWorks BSD-3-Clause"
metadata:
  version: "1.0"
---

# MATLAB Documentation Lookup

Resolve a function name, mathworks.com URL, or local help-HTML path to
clean documentation text.

## Why this skill exists

You give it a function name and it finds the right page; you do not need to know
the URL, which is not guessable from the name (interp1 is at
`ref/double.interp1.html`, not `ref/interp1.html`). The script reads MATLAB's own
documentation index, the `referenceapi` catalog inside the install, to map the
name to its canonical path, ranking exact and base-MATLAB matches so a bare name
resolves to the page it most likely means. It then serves the local HTML if
installed, or fetches the page from mathworks.com if it is not.

The online path is the common case, not a rare fallback. Recent MATLAB installs
the catalog locally but leaves the rendered pages on the web (web documentation
mode), so the catalog is exactly what supplies the URL for pages that exist only
online. The fetched URL is pinned to the installed release, with the latest
release as a fallback.

For a function from a toolbox the user has not installed, absent from the local
catalog, the script asks MathWorks's doc search for the canonical path, so it
still resolves the page. If that search comes up empty it falls back to a
name-based guess, and failing that reports not-found rather than a wrong page.

## Usage

```bash
${CLAUDE_SKILL_DIR}/scripts/extract_matlab_doc.py <target>
```

`<target>` is one of:

- A function name. Bare (`profile`, `lsqnonlin`) or namespaced
  (`compiler.runtime.createDockerImage`). Case-insensitive.
- A mathworks.com URL, with or without an `#anchor` fragment.
- A path to a local `.html` file.

The script writes markdown-flavoured text to stdout (`#` headings,
fenced code blocks for syntax and examples). Exit status is non-zero
with a stderr message if the function cannot be resolved.

## When to use this skill

Reach for it whenever you need to know what a MATLAB function does,
what arguments or name-value pairs it accepts, or whether a better
alternative exists. Common situations:

- An unfamiliar function appears in a profile hotspot list and you
  need to decide whether it is the cause of slowness or merely
  incidental.
- Someone else's MATLAB code uses a function you do not have memorized
  and you want the spec before suggesting changes.
- The user pastes a mathworks.com URL and asks about it.
- You are about to recommend an alternative (e.g.
  `griddedInterpolant` instead of repeated `interp1`) and want to
  confirm the alternative actually has the option you are about to
  cite.

When the user gives you a function name, just run the script with the
name. When they give you a URL, run the script with the URL. There is
no need to download the page yourself first.

## When not to use this skill

- When you already have the function spec in your head and the user
  is not going to act on the recommendation. Don't burn a tool call
  to confirm something obvious.
- When the question is about MATLAB language semantics, not a specific
  function (e.g. "how does broadcasting work in MATLAB?") -- those are
  better answered from training knowledge or by directing the user to
  the relevant Mathworks user guide page (and if you do that, you can
  pass the user-guide URL to this skill).
- When the user has asked you not to consult docs.

## When the script can't resolve a target

The script writes a clear message to stderr (e.g.
`Could not find documentation for: foo`) and exits non-zero. The
correct response is to retry with a different target through the
same script, never to bypass it.

Things to try, in order:

- A different spelling: `lsqnonlin` vs `lsqNonlin`, etc. (the script
  is case-insensitive but exact-token).
- A more- or less-namespaced form: `createDockerImage` vs
  `compiler.runtime.createDockerImage`.
- A topic URL on `mathworks.com` (e.g. an "Install and Configure ..."
  page) instead of a function name.
- A direct path to a local help HTML file under
  `~/Documents/MATLAB/SupportPackages/<release>/help/` or under the
  MATLAB application bundle, if you can identify one. The script
  accepts an absolute file path as a target.

If none of those resolve, accept that the doc isn't easily findable
and say so to the user. The script's not-found result is information,
not a prompt to circumvent it.

## Constraints

- Do not modify the script for project-specific function names or
  paths. The locality of `~/Documents/MATLAB` is a user-environment
  fact, not a project convention.
- Prefer this skill over fetching MATLAB docs yourself. Once it returns a
  not-found message, do not fall back to:
  - `WebFetch` or raw `curl` against `mathworks.com`. The script already
    resolves the name to the correct doc URL (not guessable from the name),
    pins it to the installed release, serves local HTML when present, detects
    the not-found page, and extracts clean text. Fetching the page yourself
    skips that resolution and hands you unparsed HTML for a URL you would have
    to know already.
  - `find` / `grep` / `ls` against `~/Documents/MATLAB/`, the MATLAB
    application bundle, or any other local doc store. The script
    already consults these. Searching them yourself produces
    user-visible noise (permission prompts, raw `Bash(find ...)`
    calls in the transcript) the user installed this skill to avoid.
  Each of these is a fallback that defeats the skill's purpose.
  Use the script with a different target instead.
- The script's output can be large for long doc pages. Quote the
  relevant section back to the user, do not paste the whole thing
  unless they ask.
