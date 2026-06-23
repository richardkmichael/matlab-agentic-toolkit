#!/usr/bin/env python
"""Deterministic unit tests for extract_matlab_doc.py.

These test the script's resolution and fetch LOGIC without a model, a MATLAB
install, or network access: the local catalog, the doc-search tier, and the
curl fetch are stubbed, so the tests assert the engineering (tier ordering,
release pinning, not-found detection, status-aware fetch) in isolation.

Run standalone:  python test_extract_matlab_doc.py
Or with pytest:  pytest test_extract_matlab_doc.py
"""

import contextlib
import importlib.util
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "extract_matlab_doc", os.path.join(_here, "extract_matlab_doc.py")
)
emd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emd)

BASE = "https://www.mathworks.com/help"


@contextlib.contextmanager
def patch(**attrs):
    """Temporarily set attributes on the module under test, then restore them."""
    saved = {k: getattr(emd, k) for k in attrs}
    for k, v in attrs.items():
        setattr(emd, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(emd, k, v)


@contextlib.contextmanager
def fake_curl(stdout, returncode=0):
    """Stub subprocess.run so curl returns a canned (stdout, exit) pair."""
    class _Proc:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout

    orig = emd.subprocess.run
    emd.subprocess.run = lambda *a, **k: _Proc()
    try:
        yield
    finally:
        emd.subprocess.run = orig


def _boom(*a, **k):
    raise AssertionError("should not be called")


# --- _installed_release ------------------------------------------------------

def test_installed_release_parses_token():
    api = "/Applications/MATLAB_R2025b.app/help/docCatalog/referenceapi"
    with patch(_find_referenceapi_dir=lambda: api):
        assert emd._installed_release() == "R2025b"


def test_installed_release_none_without_install():
    with patch(_find_referenceapi_dir=lambda: None):
        assert emd._installed_release() is None


# --- _name_matches -----------------------------------------------------------

def test_name_matches():
    assert emd._name_matches("interp1", "interp1")
    assert emd._name_matches("double.interp1", "interp1")    # bare matches namespaced
    assert not emd._name_matches("interp1", "interp2")
    assert not emd._name_matches("xinterp1", "interp1")       # not a dotted suffix
    assert not emd._name_matches("a.b.interp1", "b.interp1")  # namespaced query, non-exact


# --- _remote_url_candidates: tier ordering + release pinning -----------------

def test_candidates_catalog_hit_pins_and_skips_search():
    with patch(
        _referenceapi_matches=lambda fn: [("matlab", "ref/double.interp1.html")],
        _installed_release=lambda: "R2025b",
        _typeahead_path=_boom,            # must not be queried on a catalog hit
    ):
        assert emd._remote_url_candidates("interp1") == [
            f"{BASE}/releases/R2025b/matlab/ref/double.interp1.html",
            f"{BASE}/matlab/ref/double.interp1.html",
        ]


def test_candidates_search_tier_on_catalog_miss():
    with patch(
        _referenceapi_matches=lambda fn: [],
        _typeahead_path=lambda fn: "control/ref/dynamicsystem.bode.html",
        _installed_release=lambda: "R2025b",
    ):
        assert emd._remote_url_candidates("bode") == [
            f"{BASE}/releases/R2025b/control/ref/dynamicsystem.bode.html",
            f"{BASE}/control/ref/dynamicsystem.bode.html",
        ]


def test_candidates_naive_fallback_when_search_empty():
    with patch(
        _referenceapi_matches=lambda fn: [],
        _typeahead_path=lambda fn: None,
        _installed_release=lambda: "R2025b",
    ):
        assert emd._remote_url_candidates("zzz") == [
            f"{BASE}/releases/R2025b/matlab/ref/zzz.html",
            f"{BASE}/matlab/ref/zzz.html",
        ]


def test_candidates_unversioned_only_without_install():
    with patch(
        _referenceapi_matches=lambda fn: [("matlab", "ref/x.html")],
        _installed_release=lambda: None,
        _typeahead_path=_boom,
    ):
        assert emd._remote_url_candidates("x") == [f"{BASE}/matlab/ref/x.html"]


# --- _typeahead_path: parsing ------------------------------------------------

def _typeahead_json(title, path, type_="doc"):
    return json.dumps({"pages": [{"suggestions": [
        {"type": type_, "title": ["", title, ""], "path": path}]}]})


def test_typeahead_extracts_exact_title_doc():
    body = _typeahead_json("bode", "control/ref/dynamicsystem.bode.html")
    with fake_curl(body + "\n200"):
        assert emd._typeahead_path("bode") == "control/ref/dynamicsystem.bode.html"


def test_typeahead_none_on_title_mismatch():
    body = _typeahead_json("bodemag", "control/ref/bodemag.html")
    with fake_curl(body + "\n200"):
        assert emd._typeahead_path("bode") is None


def test_typeahead_none_on_non_200():
    body = _typeahead_json("bode", "control/ref/dynamicsystem.bode.html")
    with fake_curl(body + "\n404"):
        assert emd._typeahead_path("bode") is None


# --- _curl_fetch: status-aware + not-found detection -------------------------

def test_curl_fetch_returns_body_on_200():
    body = "x" * 2000
    with fake_curl(body + "\n200"):
        assert emd._curl_fetch("http://x") == body


def test_curl_fetch_none_on_404():
    body = "x" * 2000
    with fake_curl(body + "\n404"):
        assert emd._curl_fetch("http://x") is None


def test_curl_fetch_none_on_not_found_sentinel():
    body = "x" * 2000 + emd._NOT_FOUND_SENTINEL
    with fake_curl(body + "\n200"):
        assert emd._curl_fetch("http://x") is None


def test_curl_fetch_none_on_tiny_body():
    with fake_curl("tiny\n200"):
        assert emd._curl_fetch("http://x") is None


# --- standalone runner -------------------------------------------------------

def _run_all():
    tests = sorted(k for k in globals() if k.startswith("test_"))
    passed = failed = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"  PASS {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
