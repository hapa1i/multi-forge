"""Tests for shared per-file unified-diff parsing."""

from __future__ import annotations

import os

import pytest

from forge.policy.diff import DiffParseError, split_diff_per_file


def _ordinary_chunk(path: str) -> str:
    return f"diff --git a/{path} b/{path}\n" f"--- a/{path}\n" f"+++ b/{path}\n" "@@ -0,0 +1 @@\n" "+ordinary = True\n"


def _quoted_chunk() -> str:
    return (
        'diff --git "a/src/caf\\303\\251.py" "b/src/caf\\303\\251.py"\n'
        '--- "a/src/caf\\303\\251.py"\n'
        '+++ "b/src/caf\\303\\251.py"\n'
        "@@ -0,0 +1 @@\n"
        "+quoted = True\n"
    )


def _binary_deleted_chunk(newline: str) -> str:
    return newline.join(
        [
            "diff --git a/assets/deleted.png b/assets/deleted.png",
            "deleted file mode 100644",
            "index 1111111..0000000",
            "Binary files a/assets/deleted.png and /dev/null differ",
            "",
        ]
    )


@pytest.mark.parametrize(
    ("diff", "expected_paths"),
    [
        (
            _quoted_chunk() + _ordinary_chunk("src/plain.py"),
            ["src/café.py", "src/plain.py"],
        ),
        (
            _ordinary_chunk("src/plain.py") + _quoted_chunk(),
            ["src/plain.py", "src/café.py"],
        ),
    ],
)
def test_c_quoted_header_is_an_independent_boundary_beside_unquoted_file(
    diff: str,
    expected_paths: list[str],
) -> None:
    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == expected_paths
    assert all(chunk.count("diff --git ") == 1 for _path, chunk in file_diffs)


def test_c_quoted_header_preserves_non_utf8_path_bytes() -> None:
    diff = (
        'diff --git "a/src/bad\\377.py" "b/src/bad\\377.py"\n'
        '--- "a/src/bad\\377.py"\n'
        '+++ "b/src/bad\\377.py"\n'
        "@@ -0,0 +1 @@\n"
        "+value = 1\n"
    )

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == [os.fsdecode(b"src/bad\xff.py")]


def test_headerless_diff_ignores_added_plus_lines_but_keeps_deletion_boundaries() -> None:
    diff = (
        "--- a/src/first.py\n"
        "+++ b/src/first.py\n"
        "@@ -0,0 +1,5 @@\n"
        "+safe = True\n"
        "+++ /dev/null\n"
        "+++ b/src/forged-boundary.py\n"
        "+++ note\n"
        "+violation = eval(user_input)\n"
        "--- a/src/deleted.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-deleted = True\n"
        "--- /dev/null\n"
        "+++ b/src/second.py\n"
        "@@ -0,0 +1 @@\n"
        "+second = True\n"
    )

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == ["src/first.py", "src/second.py"]
    assert "+++ /dev/null\n+++ b/src/forged-boundary.py\n+++ note\n+violation = eval(user_input)" in file_diffs[0][1]
    assert "deleted = True" not in file_diffs[0][1]
    assert file_diffs[1][1].startswith("+++ b/src/second.py\n")


def test_headerless_diff_recognizes_modify_create_and_delete_header_pairs() -> None:
    diff = (
        "--- a/src/modified.py\n"
        "+++ b/src/modified.py\n"
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+modified = True\n"
        "--- /dev/null\n"
        "+++ b/src/created.py\n"
        "@@ -0,0 +1 @@\n"
        "+created = True\n"
        "--- a/src/deleted.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-deleted = True\n"
    )

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == ["src/modified.py", "src/created.py"]
    assert "+modified = True" in file_diffs[0][1]
    assert "+created = True" in file_diffs[1][1]
    assert "deleted = True" not in file_diffs[1][1]


def test_headerless_c_quoted_header_pair_preserves_non_ascii_path() -> None:
    diff = (
        '--- "a/src/caf\\303\\251.py"\n'
        '+++ "b/src/caf\\303\\251.py"\n'
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+new = True\n"
    )

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == ["src/café.py"]
    assert "+new = True" in file_diffs[0][1]


def test_c_quoted_rename_uses_decoded_destination_and_deleted_file_is_skipped() -> None:
    renamed = (
        'diff --git "a/src/old\\303\\251.py" "b/src/new\\303\\251.py"\n'
        '--- "a/src/old\\303\\251.py"\n'
        '+++ "b/src/new\\303\\251.py"\n'
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+new = True\n"
    )
    deleted = (
        'diff --git "a/src/gone\\303\\251.py" "b/src/gone\\303\\251.py"\n'
        '--- "a/src/gone\\303\\251.py"\n'
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-gone = True\n"
    )

    file_diffs = split_diff_per_file(renamed + deleted)

    assert [path for path, _chunk in file_diffs] == ["src/newé.py"]


@pytest.mark.parametrize(
    ("diff", "expected_path"),
    [
        pytest.param(
            "diff --git a/src/old b/name.py b/src/new b/name.py\n"
            "similarity index 100%\n"
            "rename from src/old b/name.py\n"
            "rename to src/new b/name.py\n",
            "src/new b/name.py",
            id="pure-rename-prefers-rename-to",
        ),
        pytest.param(
            "diff --git a/src/base file.py b/src/copied file.py\n"
            "similarity index 100%\n"
            "copy from src/base file.py\n"
            "copy to src/copied file.py\n",
            "src/copied file.py",
            id="pure-copy-prefers-copy-to",
        ),
        pytest.param(
            "diff --git a/tools b/helpers/run script b/tools b/helpers/run script\n"
            "old mode 100644\n"
            "new mode 100755\n",
            "tools b/helpers/run script",
            id="mode-only-falls-back-to-equal-header-paths",
        ),
        pytest.param(
            "diff --git a/assets/blob image.png b/assets/blob image.png\n"
            "index 0123456..abcdef0 100644\n"
            "Binary files a/assets/blob image.png and b/assets/blob image.png differ\n",
            "assets/blob image.png",
            id="binary-falls-back-to-unquoted-header",
        ),
    ],
)
def test_unquoted_space_paths_survive_metadata_and_header_fallback(
    diff: str,
    expected_path: str,
) -> None:
    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == [expected_path]


@pytest.mark.parametrize("combined_kind", ["cc", "combined"])
def test_mixed_ordinary_and_combined_diff_headers_are_independent_boundaries(
    combined_kind: str,
) -> None:
    diff = (
        _ordinary_chunk("README.md") + f"diff --{combined_kind} src/main.py\n"
        "index 1111111,2222222..3333333\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@@ -1,1 -1,1 +1,2 @@@\n"
        "  value = 1\n"
        "++if TYPE_CHECKING:\n"
    )

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == ["README.md", "src/main.py"]
    assert "diff --cc" not in file_diffs[0][1]
    assert "diff --combined" not in file_diffs[0][1]
    assert file_diffs[1][1].startswith(f"diff --{combined_kind} src/main.py\n")


def test_c_quoted_combined_diff_path_is_decoded() -> None:
    # Git emits the unprefixed path in a combined header, quoting that one token
    # under quotePath. Keep this metadata-only so the header is the path source.
    diff = 'diff --cc "src/caf\\303\\251.py"\n' "index 1111111,2222222..3333333\n" "mode 100644,100644..100755\n"

    file_diffs = split_diff_per_file(diff)

    assert [path for path, _chunk in file_diffs] == ["src/café.py"]


def test_partial_attribution_raises_without_treating_deletions_as_parse_loss() -> None:
    diff = _ordinary_chunk("src/kept.py") + (
        "diff --git src/old_name.py src/new_name.py\n"
        "similarity index 100%\n"
        "rename from src/old_name.py\n"
        "rename to src/new_name.py\n"
        "diff --git src/unknown.py src/unknown.py\n"
        "--- src/unknown.py\n"
        "+++ src/unknown.py\n"
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+new = True\n"
        "diff --git a/src/deleted.py b/src/deleted.py\n"
        "deleted file mode 100644\n"
        "--- a/src/deleted.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-deleted = True\n"
        "diff --git a/assets/deleted.png b/assets/deleted.png\n"
        "deleted file mode 100644\n"
        "index 1111111..0000000\n"
        "Binary files a/assets/deleted.png and /dev/null differ\n"
    )

    with pytest.raises(DiffParseError, match="1 file chunk could not be attributed") as error:
        split_diff_per_file(diff)

    assert error.value.unattributed_chunks == 1


@pytest.mark.parametrize(
    "diff",
    [
        pytest.param(
            "diff --git a/src/deleted.py b/src/deleted.py\n"
            "deleted file mode 100644\n"
            "--- a/src/deleted.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-deleted = True\n",
            id="text-lf",
        ),
        pytest.param(_binary_deleted_chunk("\n"), id="binary-lf"),
        pytest.param(_binary_deleted_chunk("\r\n"), id="binary-crlf"),
    ],
)
def test_deleted_diff_is_skipped_without_attribution_failure(diff: str) -> None:
    assert split_diff_per_file(diff) == []


def test_headerless_partial_attribution_is_reported_instead_of_silently_dropped() -> None:
    diff = (
        "--- a/src/kept.py\n"
        "+++ b/src/kept.py\n"
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+kept = True\n"
        "--- src/unknown.py\n"
        "+++ src/unknown.py\n"
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+unknown = True\n"
        "--- a/src/later.py\n"
        "+++ b/src/later.py\n"
        "@@ -1 +1 @@\n"
        "-old = True\n"
        "+later = True\n"
    )

    with pytest.raises(DiffParseError, match="1 file chunk could not be attributed"):
        split_diff_per_file(diff)


def test_headerless_initial_unattributed_chunk_is_not_hidden_by_a_valid_later_file() -> None:
    diff = (
        "+++ src/hidden.py\n"
        "@@ -0,0 +1 @@\n"
        "+if TYPE_CHECKING:\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -0,0 +1 @@\n"
        "+safe documentation\n"
    )

    with pytest.raises(DiffParseError, match="1 file chunk could not be attributed"):
        split_diff_per_file(diff)
