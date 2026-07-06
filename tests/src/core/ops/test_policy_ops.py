from pathlib import Path


def test_policy_ops_is_ui_free() -> None:
    text = Path("src/forge/core/ops/policy.py").read_text(encoding="utf-8")

    assert "click" not in text
    assert "rich" not in text
    assert "sys.exit" not in text
    assert "print(" not in text
