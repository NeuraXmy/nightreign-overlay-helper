"""The build gate supplies a freshly published helper, never an installed old one."""

import os
import sys
from pathlib import Path

import pytest
from scripts.check_p2p_startup import check


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("NROH_TEST_NATIVE_HELPER"),
    reason="Run the published Windows helper gate with NROH_TEST_NATIVE_HELPER.",
)
def test_published_detached_entry_points_and_pipe_mode():
    check(Path(os.environ["NROH_TEST_NATIVE_HELPER"]))
