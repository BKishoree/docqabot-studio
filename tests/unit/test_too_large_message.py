"""C1 (Architect Review v1): the file_too_large message never shows a size at or below the limit."""

from __future__ import annotations

import re

import pytest

from tests.conftest import need_module

MB = 1024 * 1024


@pytest.fixture(scope="module")
def msg():
    return need_module("studio.routes.documents").too_large_message


@pytest.mark.parametrize(
    "size,limit,expected",
    [
        (21_000_000, 20 * MB, "The file is 20.03 MB. The limit is 20 MB."),
        (20 * MB + 1, 20 * MB, "The file is larger than the 20 MB limit."),
        (None, 20 * MB, "The file is larger than the 20 MB limit."),
        (int(22.0 * MB), 20 * MB, "The file is 22.0 MB. The limit is 20 MB."),
        (32_715_571, 20 * MB, "The file is 31.2 MB. The limit is 20 MB."),
    ],
)
def test_C1_documented_examples(msg, size, limit, expected):
    assert msg(size, limit) == expected


@pytest.mark.parametrize("limit_mb", [1, 2, 20, 100])
def test_C1_shown_size_always_exceeds_limit(msg, limit_mb):
    limit = limit_mb * MB
    for size in [limit + 1, limit + 1023, limit + 5000, limit + MB // 200, limit + MB // 20, limit + MB, 3 * limit]:
        text = msg(size, limit)
        m = re.fullmatch(r"The file is ([\d.]+) MB\. The limit is (\d+(?:\.\d+)?) MB\.", text)
        if m:
            assert float(m.group(1)) > float(m.group(2)), text
        else:
            assert text == f"The file is larger than the {limit_mb} MB limit.", text
