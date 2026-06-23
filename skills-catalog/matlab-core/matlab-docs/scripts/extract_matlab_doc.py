#!/usr/bin/env python
"""Extract clean text from a MATLAB documentation page.

Resolves a function name, HTML file path, or mathworks.com URL to documentation
and prints LLM-friendly Markdown to stdout.  Abstracts local-vs-remote sources.

Resolution chain:
  1. HTTP(S) URL (e.g. mathworks.com page) -- curl-fetched directly
  2. Local HTML (documentation Add-On or MATLAB install help)
  3. Name -> URL: the local referenceapi catalog, else MathWorks's doc-search
     API for products absent from the catalog, else a matlab/ref guess
  4. Remote: curl the resolved URL, pinned to the installed release

Usage:
    extract_matlab_doc.py profile
    extract_matlab_doc.py lsqnonlin
    extract_matlab_doc.py /path/to/some_page.html
    extract_matlab_doc.py https://www.mathworks.com/help/.../foo.html
"""

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path


# --- Path discovery -----------------------------------------------------------

# Local documentation lives at the platform's default MATLAB locations. Each
# list holds the macOS, Windows, and Linux candidates; only the running
# platform's paths exist, so globbing them all and keeping the newest release
# resolves the right install without a platform switch. '*'/'R*' match any
# installed release.

# Help roots that contain matlab/ref/<fn>.html: the user documentation Add-On
# and the MATLAB install's own bundled help.
_HELP_ROOT_PATTERNS = [
    os.path.expanduser("~/Documents/MATLAB/SupportPackages/*/help"),
    os.path.expanduser(
        "~/Library/Application Support/MathWorks/MATLAB/SupportPackages/*/help"
    ),
    "C:/ProgramData/MATLAB/SupportPackages/*/help",
    "/usr/local/MATLAB/SupportPackages/*/help",
    "/Applications/MATLAB_R*.app/help",
    "C:/Program Files/MATLAB/R*/help",
    "/usr/local/MATLAB/R*/help",
]

# referenceapi catalog inside the MATLAB install (resolves toolbox-specific
# hrefs such as optim/ug/lsqnonlin.html).
_REFERENCEAPI_PATTERNS = [
    "/Applications/MATLAB_R*.app/help/docCatalog/referenceapi",
    "C:/Program Files/MATLAB/R*/help/docCatalog/referenceapi",
    "/usr/local/MATLAB/R*/help/docCatalog/referenceapi",
]


def _release_key(path: str) -> tuple:
    """Sort key ordering a path by its MATLAB release (newest first)."""
    m = re.search(r"R(20\d{2})([ab])", path)
    return (int(m.group(1)), m.group(2)) if m else (0, "")


def _newest_first(paths) -> list:
    """Existing paths, de-duplicated, ordered newest release first."""
    return sorted(set(paths), key=lambda p: (_release_key(p), p), reverse=True)


def _find_help_roots() -> list:
    """All existing local help roots, newest release first."""
    matches = []
    for pattern in _HELP_ROOT_PATTERNS:
        matches.extend(glob.glob(pattern))
    return _newest_first(matches)


def _find_referenceapi_dir() -> str | None:
    """Return the newest install's referenceapi directory, or None."""
    matches = []
    for pattern in _REFERENCEAPI_PATTERNS:
        matches.extend(glob.glob(pattern))
    candidates = _newest_first(matches)
    return candidates[0] if candidates else None


def _name_matches(entity_name: str, query: str) -> bool:
    """Match a query against a referenceapi entity name.

    Handles two cases the entity-name field alone doesn't cover:
    case differences (entries are mixed-case like
    `compiler.runtime.createDockerImage`, queries arrive lowercased),
    and bare names (`createDockerImage` should resolve the namespaced
    entry). For a namespaced query, only exact matches are accepted.
    """
    en = entity_name.lower()
    q = query.lower()
    if en == q:
        return True
    if "." not in q and en.endswith("." + q):
        return True
    return False


def _referenceapi_matches(fn_name: str) -> list:
    """Return (help_location, href) pairs for referenceapi entries matching
    fn_name, best match first.

    A bare name can collide across products -- e.g. base MATLAB `fft`
    (matlab/ref/fft.html) and the Financial Instruments Toolbox method
    `finpricer.fft` (fininst/finpricer.fft.html). Rank exact-name matches ahead
    of namespaced ones, and base MATLAB (matlab/...) ahead of toolbox locations,
    so the page a bare name most likely means wins.
    """
    api_dir = _find_referenceapi_dir()
    if not api_dir:
        return []

    q = fn_name.lower()
    ranked = []
    for order, json_file in enumerate(
        sorted(glob.glob(os.path.join(api_dir, "*.json")))
    ):
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        help_location = data.get("helpLocation", "")
        for item in data.get("refItems", []):
            href = item.get("href", "")
            if not href:
                continue
            names = [e.get("name", "") for e in item.get("refentity", [])]
            if not any(_name_matches(name, q) for name in names):
                continue
            is_exact = any(name.lower() == q for name in names)
            is_base = f"{help_location}/{href}".startswith("matlab/")
            rank = (0 if is_exact else 1, 0 if is_base else 1, order)
            ranked.append((rank, help_location, href))

    ranked.sort(key=lambda r: r[0])
    return [(help_location, href) for _, help_location, href in ranked]


def _resolve_local_path(fn_name: str) -> str | None:
    """Try to find the local HTML file for a function.

    First checks matlab/ref/<fn>.html under each help root (covers most core
    functions). If not found, searches the referenceapi JSON files for the
    correct href (toolbox functions live at different paths, e.g.,
    optim/ug/lsqnonlin.html) and resolves it against the help roots.
    """
    help_roots = _find_help_roots()
    if not help_roots:
        return None

    # Direct path for core MATLAB functions
    for root in help_roots:
        direct = os.path.join(root, "matlab", "ref", f"{fn_name}.html")
        if os.path.isfile(direct):
            return direct

    # Search referenceapi for the correct href -- toolbox functions and class
    # methods live at other paths (e.g. optim/ug/lsqnonlin.html), best first.
    for help_location, href in _referenceapi_matches(fn_name):
        for root in help_roots:
            full_path = os.path.join(root, help_location, href)
            if os.path.isfile(full_path):
                return full_path
    return None


# --- HTML extraction ----------------------------------------------------------

def _extract_doc_content(raw_html: str) -> str:
    """Extract the documentation section and convert to clean text."""
    # Target the doc_center_content container (both local and remote pages).
    # Anchor on the stable id, not the tag: attributes (e.g. xmlns) can precede
    # the id, and the container is a <section> today but could become a <div>.
    match = re.search(
        r'<(\w+)\b[^>]*\bid="doc_center_content"[^>]*>(.*)',
        raw_html,
        re.DOTALL,
    )
    if match:
        tag = match.group(1)
        content = match.group(2)
        # Find the matching closing tag at the right nesting level
        depth = 1
        pos = 0
        while depth > 0 and pos < len(content):
            open_match = re.search(rf"<{tag}[\s>]", content[pos:])
            close_match = re.search(rf"</{tag}>", content[pos:])
            if close_match is None:
                break
            if open_match and open_match.start() < close_match.start():
                depth += 1
                pos += open_match.end()
            else:
                depth -= 1
                if depth == 0:
                    content = content[: pos + close_match.start()]
                pos += close_match.end()
    else:
        # Fallback: try <main>
        main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, re.DOTALL)
        content = main_match.group(1) if main_match else raw_html

    # Strip script and style blocks
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)

    # Convert headings to markdown
    content = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", content, flags=re.DOTALL)
    content = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", content, flags=re.DOTALL)
    content = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", content, flags=re.DOTALL)

    # Convert code tags to backticks
    content = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", content, flags=re.DOTALL)

    # Convert <pre> blocks to fenced code
    content = re.sub(
        r"<pre[^>]*>(.*?)</pre>",
        lambda m: "\n```\n" + re.sub(r"<[^>]+>", "", m.group(1)) + "\n```\n",
        content,
        flags=re.DOTALL,
    )

    # Convert list items
    content = re.sub(r"<li[^>]*>", "\n- ", content)

    # Convert table rows to pipe-delimited (basic)
    content = re.sub(r"<tr[^>]*>", "\n| ", content)
    content = re.sub(r"<t[hd][^>]*>", " | ", content)
    content = re.sub(r"</t[hd]>", "", content)
    content = re.sub(r"</tr>", " |", content)

    # Convert <p> to paragraph breaks
    content = re.sub(r"<p[^>]*>", "\n\n", content)

    # Convert <br> to newlines
    content = re.sub(r"<br\s*/?>", "\n", content)

    # Strip all remaining HTML tags
    content = re.sub(r"<[^>]+>", " ", content)

    # Decode HTML entities
    content = html.unescape(content)

    # Collapse whitespace within lines, preserve paragraph structure
    lines = content.split("\n")
    cleaned = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned.append(line)
    content = "\n".join(cleaned)

    # Collapse excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


# --- Remote fetch -------------------------------------------------------------

_MATHWORKS_BASE = "https://www.mathworks.com/help"


# MathWorks serves a styled "page not found" body (often with a 404, though
# curl still exits 0) when a doc URL is missing. The phrase below is the
# visible text on that page; treat it as a failed fetch so the caller surfaces
# a not-found instead of the error page.
_NOT_FOUND_SENTINEL = "The page you were looking for does not exist"


def _curl_fetch(url: str) -> str | None:
    """Fetch a URL via curl. Returns the HTML on a 200, or None on a failed
    fetch: a transport error, a non-200 status (e.g. a 404 for a missing page),
    or MathWorks's styled not-found body served with a 200."""
    cmd = ["curl", "-sSL", "--max-time", "20", "-w", "\n%{http_code}", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    body, _, status = result.stdout.rpartition("\n")
    if status.strip() != "200":
        return None
    if len(body) <= 1000 or _NOT_FOUND_SENTINEL in body:
        return None
    return body


def _installed_release() -> str | None:
    """Release token (e.g. 'R2025b') of the install whose catalog resolves the
    path, or None when no install is found. Read from the referenceapi directory
    the hrefs come from, so the pinned URL matches the release that produced it.
    """
    api_dir = _find_referenceapi_dir()
    if not api_dir:
        return None
    m = re.search(r"R20\d{2}[ab]", api_dir)
    return m.group(0) if m else None


_TYPEAHEAD_URL = (
    "https://services.mathworks.com/typeahead/grouped"
    "?resources=latestdoc&site_domain=www&site_language=en"
    "&result_count=10&format=doc&q="
)


def _typeahead_path(fn_name: str) -> str | None:
    """Resolve a name to its canonical /help/ path via MathWorks's doc-search
    typeahead service, or None.

    Covers functions documented online but absent from the local catalog (a
    toolbox the user has not installed). Returns the path of the first 'doc'
    suggestion whose title equals the name, case-insensitive. This is an
    undocumented MathWorks endpoint; the caller falls back to a name-based guess
    on any failure, so a change there degrades gracefully.
    """
    cmd = ["curl", "-sS", "--max-time", "15", "-w", "\n%{http_code}",
           _TYPEAHEAD_URL + urllib.parse.quote(fn_name)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    body, _, status = result.stdout.rpartition("\n")
    if status.strip() != "200":
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    q = fn_name.lower()
    for page in data.get("pages", []):
        for item in page.get("suggestions", []):
            title = "".join(item.get("title", []))
            if item.get("type") == "doc" and title.lower() == q and item.get("path"):
                return item["path"]
    return None


def _remote_url_candidates(fn_name: str) -> list:
    """MathWorks doc URLs to try for a function, best first.

    Resolves the path from the local referenceapi catalog (installed products);
    if the catalog has no entry (e.g. an uninstalled toolbox), asks MathWorks's
    doc search for the canonical path; failing that, guesses the core matlab/ref
    location. Pins each URL to the installed release with the unversioned (latest)
    URL as a fallback in case mathworks.com does not serve that release's page.
    """
    path = None
    for help_location, href in _referenceapi_matches(fn_name):
        if help_location:
            path = f"{help_location}/{href}"
            break
    if path is None:
        path = _typeahead_path(fn_name) or f"matlab/ref/{fn_name}.html"

    release = _installed_release()
    urls = []
    if release:
        urls.append(f"{_MATHWORKS_BASE}/releases/{release}/{path}")
    urls.append(f"{_MATHWORKS_BASE}/{path}")
    return urls


def _fetch_remote(fn_name: str) -> str | None:
    """Fetch documentation from mathworks.com, trying the release-pinned URL
    first and the unversioned (latest) URL if that page is missing."""
    for url in _remote_url_candidates(fn_name):
        raw = _curl_fetch(url)
        if raw:
            return raw
    return None


def _function_name_from_help_url(url: str) -> str | None:
    """Return the page base name from a mathworks.com help URL (e.g. 'interp1'
    from .../matlab/ref/interp1.html), or None if it is not such a URL.

    Used to recover from a 404 on a bare ref URL: some functions are documented
    at a different path (interp1 lives at double.interp1.html), which the name
    resolver knows even though the bare URL does not exist.
    """
    if "mathworks.com/help/" not in url:
        return None
    last = url.rstrip("/").rsplit("/", 1)[-1]
    if not last.endswith(".html"):
        return None
    return last[: -len(".html")] or None


# --- Main ---------------------------------------------------------------------

def extract_doc(target: str) -> str | None:
    """Extract documentation for a function name, file path, or HTTP(S) URL.

    Returns clean text or None if the function could not be found.
    """
    # If target is an HTTP(S) URL, fetch and clean it directly. Strip any
    # fragment first.
    if target.startswith(("http://", "https://")):
        url = target.split("#", 1)[0]
        raw = _curl_fetch(url)
        if raw:
            return _extract_doc_content(raw)
        # A bare mathworks.com ref URL can 404 when the function is documented
        # at a different path (e.g. interp1 -> double.interp1.html). Recover by
        # re-resolving the page's function name through the normal name path.
        name = _function_name_from_help_url(url)
        return extract_doc(name) if name else None

    # If target looks like a file path, read it directly
    if os.path.isfile(target):
        with open(target) as f:
            return _extract_doc_content(f.read())

    fn_name = target.lower()

    # Try local HTML first
    local_path = _resolve_local_path(fn_name)
    if local_path:
        with open(local_path) as f:
            return _extract_doc_content(f.read())

    # Try remote
    raw = _fetch_remote(fn_name)
    if raw:
        return _extract_doc_content(raw)

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Extract clean text from MATLAB documentation pages."
    )
    parser.add_argument(
        "target",
        help="Function name (e.g., 'profile', 'lsqnonlin') or path to HTML file",
    )
    args = parser.parse_args()

    text = extract_doc(args.target)
    if text is None:
        print(f"Could not find documentation for: {args.target}", file=sys.stderr)
        sys.exit(1)

    print(text)


if __name__ == "__main__":
    main()
