"""B1: restoring a plan's mtime and size retained a cached verdict for different bytes."""

import os

import pytest

from forge.policy.semantic.supervisor import plan_fingerprint

pytestmark = pytest.mark.regression


def test_equal_size_plan_replacement_changes_identity(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("allow A\n")
    before = plan.stat()
    original = plan_fingerprint(str(plan), None)
    plan.write_text("allow B\n")
    os.utime(plan, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert plan_fingerprint(str(plan), None) != original
