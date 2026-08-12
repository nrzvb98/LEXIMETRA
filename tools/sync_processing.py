"""Sync the HALA processing pipeline from its upstream repo into this one.

The pipeline lives in a separate repo (``Hala_Processing``) where it is
developed and validated against the notebook. This app vendors a copy at
``src/hala_rt/processing/`` so the app builds — and packages — from a single
checkout.

The copy is *generated*, never hand-edited. Upstream's package is itself named
``hala_rt``, which collides with this app's package, so every self-reference is
rewritten to ``hala_rt.processing`` on the way in. Because that rewrite is
deterministic, drift can be detected by re-running it and comparing:

    python tools/sync_processing.py            # check for drift (exit 1 if any)
    python tools/sync_processing.py --apply    # re-vendor from upstream

Upstream is located via ``--upstream``, then ``$HALA_PROCESSING_DIR``, then a
sibling ``Hala_Processing`` checkout.

Changes to the pipeline belong upstream: edit there, validate with upstream's
``regression_check.py`` (which has the full 2.1 GB reference set), commit, then
``--apply`` here and run ``tests/test_processing_regression.py``.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = APP_ROOT / "src" / "hala_rt" / "processing"
UPSTREAM_PACKAGE = "hala_rt"
VERSION_FILE = "VERSION"

# Upstream's package name is `hala_rt`; here it is `hala_rt.processing`. Match
# the bare token only, so `hala_rt_something` and `_hala_output.csv` are left
# alone, and skip anything already rewritten (makes the transform idempotent).
_RENAME = re.compile(r"\bhala_rt\b(?!\.processing)")


def rewrite(text: str) -> str:
    """Apply the vendoring transform to one module's source."""
    return _RENAME.sub("hala_rt.processing", text)


def find_upstream(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("HALA_PROCESSING_DIR"):
        candidates.append(Path(os.environ["HALA_PROCESSING_DIR"]))
    candidates.append(APP_ROOT.parent.parent / "Hala_Processing")

    for candidate in candidates:
        if (candidate / UPSTREAM_PACKAGE / "pipeline.py").is_file():
            return candidate.resolve()

    tried = "\n".join(f"  - {c}" for c in candidates)
    raise SystemExit(
        "Could not find the Hala_Processing checkout. Tried:\n"
        f"{tried}\n\nPass --upstream PATH or set HALA_PROCESSING_DIR."
    )


def upstream_commit(upstream: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "--short", "HEAD"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def upstream_dirty(upstream: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(upstream), "status", "--porcelain"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return bool(result.stdout.strip())


def source_modules(upstream: Path) -> list[Path]:
    return sorted((upstream / UPSTREAM_PACKAGE).glob("*.py"))


def source_templates(upstream: Path) -> list[Path]:
    return sorted((upstream / UPSTREAM_PACKAGE / "templates").glob("*.wav"))


def check(upstream: Path) -> int:
    problems = []

    expected_names = {p.name for p in source_modules(upstream)}
    actual_names = {p.name for p in VENDOR_DIR.glob("*.py")}
    for extra in sorted(actual_names - expected_names):
        problems.append(f"{extra}: present here but not upstream")
    for missing in sorted(expected_names - actual_names):
        problems.append(f"{missing}: upstream module not vendored")

    for source in source_modules(upstream):
        target = VENDOR_DIR / source.name
        if not target.is_file():
            continue
        expected = rewrite(source.read_text())
        actual = target.read_text()
        if expected != actual:
            diff = "\n".join(
                difflib.unified_diff(
                    expected.splitlines(), actual.splitlines(),
                    fromfile=f"upstream (rewritten)/{source.name}",
                    tofile=f"vendored/{source.name}",
                    lineterm="",
                )
            )
            problems.append(f"{source.name}: differs from upstream\n{diff}")

    for source in source_templates(upstream):
        target = VENDOR_DIR / "templates" / source.name
        if not target.is_file():
            problems.append(f"templates/{source.name}: not vendored")
        elif source.read_bytes() != target.read_bytes():
            problems.append(f"templates/{source.name}: differs from upstream")

    if problems:
        print("Vendored pipeline has drifted from upstream:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nThe vendored copy is generated. Make the change upstream, then "
            "re-run with --apply."
        )
        return 1

    print(f"Vendored pipeline matches upstream at {upstream}.")
    return 0


def apply(upstream: Path) -> int:
    if upstream_dirty(upstream):
        print(
            f"Warning: {upstream} has uncommitted changes. The VERSION stamp "
            "will name a commit that does not describe what was copied.",
            file=sys.stderr,
        )

    templates_dir = VENDOR_DIR / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    for stale in VENDOR_DIR.glob("*.py"):
        stale.unlink()

    count = 0
    for source in source_modules(upstream):
        (VENDOR_DIR / source.name).write_text(rewrite(source.read_text()))
        count += 1
    for source in source_templates(upstream):
        shutil.copy2(source, templates_dir / source.name)

    version = "unknown"
    init = VENDOR_DIR / "__init__.py"
    if init.is_file():
        match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text())
        if match:
            version = match.group(1)

    (VENDOR_DIR / VERSION_FILE).write_text(
        "\n".join(
            [
                "# Generated by tools/sync_processing.py -- do not edit.",
                "# The pipeline sources here are vendored; change them upstream.",
                f"pipeline_version: {version}",
                f"upstream_repo: {upstream}",
                f"upstream_commit: {upstream_commit(upstream)}",
                f"vendored_on: {date.today().isoformat()}",
                "",
            ]
        )
    )

    print(f"Vendored {count} modules + {len(source_templates(upstream))} templates from {upstream}")
    print(f"Wrote {VENDOR_DIR / VERSION_FILE}")
    print("\nNow run: python -m pytest tests/test_processing_regression.py")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="Re-vendor from upstream (default: check for drift only)")
    parser.add_argument("--upstream", help="Path to the Hala_Processing checkout")
    args = parser.parse_args(argv)

    upstream = find_upstream(args.upstream)
    return apply(upstream) if args.apply else check(upstream)


if __name__ == "__main__":
    sys.exit(main())
