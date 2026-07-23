"""Shared test setup: repo paths, bin/ on the import path, skip-if-not-built helper.

The corpus files under data/ are gitignored and regenerable, so tests that need them
skip cleanly (rather than fail) on a checkout where the build has not been run.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
EVAL = REPO / "eval"

sys.path.insert(0, str(REPO / "bin"))  # import shape_common, embed_models


def require(*paths):
    """Skip the calling test if any required artifact is missing."""
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        names = ", ".join(str(Path(m).relative_to(REPO)) for m in missing)
        pytest.skip(f"not built: {names} (run the extract/build/eval steps first)")
