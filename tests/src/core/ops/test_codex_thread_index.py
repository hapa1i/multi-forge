"""Contracts for shared Codex thread-to-index synchronization."""

from __future__ import annotations

from unittest.mock import patch

from forge.core.ops import codex_interactive, codex_session
from forge.core.ops.codex_thread_index import sync_codex_thread_to_index

_THREAD_ID = "019f0b65-b51c-7683-99c7-bb48107f7b83"


def test_both_codex_ops_import_shared_writer_without_legacy_copy() -> None:
    for module in (codex_interactive, codex_session):
        assert module.sync_codex_thread_to_index is sync_codex_thread_to_index
        assert "_sync_codex_thread_to_index" not in vars(module)


def test_no_thread_does_not_open_the_index() -> None:
    with patch("forge.core.ops.codex_thread_index.IndexStore") as store_type:
        sync_codex_thread_to_index("impl", None, "/repo")

    store_type.assert_not_called()


def test_thread_and_scope_are_delegated_unchanged() -> None:
    with patch("forge.core.ops.codex_thread_index.IndexStore") as store_type:
        sync_codex_thread_to_index("impl", _THREAD_ID, "/repo")

    store_type.assert_called_once_with()
    store_type.return_value.update_codex_thread.assert_called_once_with("impl", _THREAD_ID, "/repo")
