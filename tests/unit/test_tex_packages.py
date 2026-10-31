import re

import fastinc
from fastinc.texdist import TEX_DIR


def test_package_versions_match_driver() -> None:
    for sty in sorted(TEX_DIR.glob("*.sty")):
        m = re.search(r"\\ProvidesPackage\{[^}]+\}\[\S+ v(\S+) ", sty.read_text())
        assert m, sty.name
        assert m.group(1) == fastinc.__version__, sty.name
