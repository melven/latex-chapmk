"""Repository hygiene: every tracked path can be checked out on Windows."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# device names Windows reserves with any extension (aux.py cannot be checked out)
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
_INVALID = re.compile(r'[<>:"|?*\\]|[ .]$')


def test_paths_are_valid_on_windows() -> None:
    bad = []
    for path in REPO.rglob("*"):
        rel = path.relative_to(REPO)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue  # .git, build and cache directories, bytecode
        if _RESERVED.match(path.name) or _INVALID.search(path.name):
            bad.append(rel.as_posix())
    assert not bad
