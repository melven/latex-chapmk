"""Unit tests for canon.py: the commit journal."""

from pathlib import Path

import pytest

from chapmk.canon import JOURNAL_FILE, committing, journal_reason
from chapmk.state import State, load_state


def _state() -> State:
    return State(1700000000, {}, "stamp", [], {})


def test_committing_saves_the_state_and_removes_the_journal(tmp_path: Path) -> None:
    canon, state = tmp_path / "canon", _state()
    with committing(canon, state, ["r1", "r2"]):
        assert (canon / JOURNAL_FILE).read_text() == "r1 r2"
        state.next_run = 3
    assert not (canon / JOURNAL_FILE).exists()
    loaded = load_state(canon)
    assert loaded is not None and loaded.next_run == 3


def test_an_interrupted_commit_leaves_the_journal(tmp_path: Path) -> None:
    canon, state = tmp_path / "canon", _state()
    with pytest.raises(KeyboardInterrupt), committing(canon, state, ["r1"]):
        raise KeyboardInterrupt
    assert (canon / JOURNAL_FILE).is_file() and load_state(canon) is None
    assert journal_reason(canon) == "the previous build was interrupted while committing"


def test_a_fallback_in_the_commit_is_noted_in_the_journal(tmp_path: Path) -> None:
    """A fallback (or tool error) inside the commit: the next build starts cold and says why,
    not 'interrupted' (sweep: a .bcf self-check, MiKTeX: a list self-check)."""
    from chapmk.tools import ToolInputError

    canon, state = tmp_path / "canon", _state()
    assert journal_reason(canon) is None
    with pytest.raises(ToolInputError), committing(canon, state, ["r1"]):
        raise ToolInputError(".bcf has 1 citekeys, the aux 0 citations\nmore")
    assert journal_reason(canon) == (
        "the previous build stopped while committing (.bcf has 1 citekeys, the aux 0 citations)"
    )
