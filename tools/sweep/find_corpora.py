"""Find public pdfLaTeX documents with several \\include'd units on GitHub (candidates for a
chapmk sweep). Uses the GitHub REST API through `gh` (code search: 10 requests/min, at most
1000 results per query; contents and repository metadata: core rate limit).

    python find_corpora.py --pages 3 --out candidates.json
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

QUERIES = [
    '"\\include{" "\\mainmatter" "\\tableofcontents" language:TeX',
    '"\\include{" "\\begin{document}" filename:thesis.tex',
    '"\\include{" "\\begin{document}" "\\mainmatter" filename:main.tex',
    '"\\include{" "\\begin{document}" filename:dissertation.tex',
    '"\\include{chapters/" "\\begin{document}" language:TeX',
    '"\\include{" "\\begin{document}" "\\usepackage[T1]{fontenc}" "\\chapter" language:TeX',
]

INCLUDE = re.compile(r"^[ \t]*\\include\{([^}]+)\}", re.MULTILINE)
CLASS = re.compile(r"^[^%\n]*\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", re.MULTILINE)
# not pdfLaTeX: Unicode engines, their packages, magic comments
NOT_PDFLATEX = re.compile(
    r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\b(fontspec|unicode-math|xeCJK|polyglossia|luacode|"
    r"xltxtra|ctex)\b|\\documentclass(?:\[[^\]]*\])?\{ctex|%\s*!TEX\s+(?:TS-)?program\s*=\s*"
    r"(?:xe|lua)latex",
    re.IGNORECASE,
)


def gh(path: str, **params: str) -> Any:
    argv = ["gh", "api", "-X", "GET", path]
    for k, v in params.items():
        argv += ["-f", f"{k}={v}"]
    for attempt in range(4):
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        if "rate limit" in r.stderr.lower() or "secondary" in r.stderr.lower():
            time.sleep(60)
            continue
        raise RuntimeError(f"{path}: {r.stderr.strip()[:200]}")
    raise RuntimeError(f"{path}: rate limited")


def search(pages: int) -> dict[tuple[str, str], str]:
    """(repo, path) -> query, deduplicated over all queries."""
    hits: dict[tuple[str, str], str] = {}
    for q in QUERIES:
        for page in range(1, pages + 1):
            data = gh("search/code", q=q, per_page="100", page=str(page))
            for item in data["items"]:
                hits.setdefault((item["repository"]["full_name"], item["path"]), q)
            time.sleep(6.5)  # code search: 10 requests per minute
            if len(data["items"]) < 100:
                break
    return hits


def repo_meta(repos: list[str]) -> dict[str, dict[str, Any]]:
    """Licence, stars, fork flag, size, last push per repository (repository search with
    several ``repo:`` qualifiers per request: no access to the repositories API needed)."""
    meta: dict[str, dict[str, Any]] = {}
    batch: list[str] = []
    for repo in [*repos, None]:
        if repo is not None and len(" ".join(f"repo:{r}" for r in [*batch, repo])) < 240:
            batch.append(repo)
            continue
        if batch:
            data = gh("search/repositories", q=" ".join(f"repo:{r}" for r in batch),
                      per_page="100")
            for m in data["items"]:
                meta[m["full_name"]] = {
                    "license": (m.get("license") or {}).get("spdx_id"),
                    "stars": m["stargazers_count"],
                    "fork": m["fork"],
                    "size_kb": m["size"],
                    "pushed": m["pushed_at"],
                }
            time.sleep(2.1)  # search: 30 requests per minute
        batch = [repo] if repo is not None else []
    return meta


def raw(repo: str, path: str) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/{urllib.request.quote(path)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return str(r.read().decode("utf-8", "replace"))


def inspect(repo: str, path: str) -> dict[str, Any] | None:
    text = raw(repo, path)
    includes = INCLUDE.findall(text)
    cls = CLASS.search(text)
    if len(includes) < 3 or cls is None or "\\begin{document}" not in text:
        return None
    return {
        "repo": repo,
        "path": path,
        "class": cls.group(1).strip(),
        "includes": len(includes),
        "pdflatex": NOT_PDFLATEX.search(text) is None,
        "babel": "{babel}" in text,
        "biblatex": "biblatex" in text,
        "hyperref": "hyperref" in text,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="result pages (100) per query")
    ap.add_argument("--out", default="candidates.json")
    args = ap.parse_args()
    hits = search(args.pages)
    print(f"{len(hits)} files in {len({r for r, _ in hits})} repositories", file=sys.stderr)
    found = []
    for repo, path in sorted(hits):
        try:
            c = inspect(repo, path)
        except (urllib.error.URLError, OSError, ValueError) as err:
            print(f"skip {repo}/{path}: {err}", file=sys.stderr)
            continue
        if c is not None:
            found.append(c)
    meta = repo_meta(sorted({c["repo"] for c in found}))
    for c in found:
        c.update(meta.get(c["repo"], {"license": None, "stars": 0, "fork": False}))
    found.sort(key=lambda c: (not c["pdflatex"], c["license"] in (None, "NOASSERTION"),
                              -c["stars"], -c["includes"]))
    with open(args.out, "w") as f:
        json.dump(found, f, indent=1)
    ok = [c for c in found if c["pdflatex"]]
    lic = [c for c in ok if c["license"] not in (None, "NOASSERTION")]
    print(f"{len(found)} main files with >= 3 includes; pdfLaTeX {len(ok)}; licensed {len(lic)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
