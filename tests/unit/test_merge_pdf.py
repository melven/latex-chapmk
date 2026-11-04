"""Unit tests for merge_pdf.py helpers."""

from chapmk.merge_pdf import label_style, page_labels


def test_page_labels() -> None:
    assert label_style(4, "iv") == "/r" and label_style(4, "IV") == "/R"
    assert label_style(2, "b") == "/a" and label_style(3, "3") == "/D"
    assert label_style(1, "A-1") is None
    nums = page_labels([(1, "i"), (2, "ii"), (1, "1"), (2, "2"), (5, "5"), (1, "A-1")])
    assert [int(n) if isinstance(n, int) else dict(n) for n in nums][::2] == [0, 2, 4, 5]
    assert str(nums[1].S) == "/r" and int(nums[5].St) == 5 and str(nums[7].P) == "A-1"
