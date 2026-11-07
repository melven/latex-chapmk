"""Sweep: build each document of a manifest with chapmk (cold --check, then a typo in the middle
unit and an incremental --check); one JSON line per document. Runs inside the dev container:

    python3 sweep.py [--variant] manifest.json results.jsonl [ID ...]

Manifest entries: {"id", "root" (directory copied), "main" (main file relative to root)}.
--variant: build a robustness variant (see variant()), not the original document.
Work directories of failed documents are kept under /sweep/work.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT = 1800
INCLUDE = re.compile(r"^[ \t]*\\include\{([^}]+)\}", re.MULTILINE)
PLAIN = re.compile(r"^[^\W\d_][^\\%$&{}~^#]{40,}$")
FONT_LINES = re.compile(
    r"^\s*\\(usepackage(\[[^\]]*\])?\{(fontspec|unicode-math|polyglossia|xltxtra|xunicode)\}|"
    r"set(main|sans|mono|math)font|newfontfamily|defaultfontfeatures|setdefaultlanguage|"
    r"setotherlanguages?)\b"
)
BIB = re.compile(r"^(\s*)\\bibliography\s*\{([^}]+)\}", re.MULTILINE)
VARIANT = False
LATEXMK = False
EPOCH = 1700000000
LATEXMKRC = r"""
add_cus_dep('nlo', 'nls', 0, 'nlo2nls');
sub nlo2nls {
  my ($dir, $base) = ($_[0] =~ m{^(.*)[/\\]+([^/\\]+)$}) ? ($1, $2) : ('.', $_[0]);
  require Cwd;
  my $cwd = Cwd::getcwd();
  chdir($dir) or return 1;
  my $status = system('makeindex', '-s', 'nomencl.ist', '-o', "$base.nls", "$base.nlo");
  chdir($cwd) or return 1;
  return $status;
}
"""


def latexmk_vs_full(work: Path, main: Path) -> dict[str, Any]:
    """Reference build with latexmk (as tests/acceptance: same environment, shell escape, a
    nomencl rule) in the source directory, then chapmk --full, compared (design §3.3)."""
    import os

    from chapmk.analysis import analyse
    from chapmk.check import compare_pdfs, compare_synctex
    from chapmk.config import Config
    from chapmk.texdist import detect

    dist = detect()
    rc_file = work / "latexmkrc"
    rc_file.write_text(LATEXMKRC)
    argv = ["latexmk", "-pdf", "-shell-escape", "-synctex=1", "-interaction=nonstopmode",
            "-halt-on-error", "-file-line-error", "-r", str(rc_file), main.name]
    t = time.monotonic()
    try:
        r = subprocess.run(argv, cwd=main.parent, capture_output=True, text=True, errors="replace",
                           env=dist.environment(EPOCH, os.environ), timeout=TIMEOUT)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = -1, "latexmk timeout"
    res: dict[str, Any] = {"latexmk_rc": rc, "latexmk_seconds": round(time.monotonic() - t)}
    stem = main.stem
    pdf, syn = main.parent / f"{stem}.pdf", main.parent / f"{stem}.synctex.gz"
    if rc != 0 or not pdf.is_file():
        res["latexmk_error"] = [ln for ln in out.splitlines() if re.match(r"^(!|\S+:\d+: )", ln)][:3]
        return res
    ref = work / "ref"
    ref.mkdir()
    shutil.copy(pdf, ref / pdf.name)
    if syn.is_file():
        shutil.copy(syn, ref / syn.name)
    for p in main.parent.glob(f"{stem}.*"):  # latexmk's files must not be the next inputs
        if p.suffix not in (".tex",) and p.is_file():
            p.unlink()
    rc2, out2, rep2, sec2 = chapmk(main.parent, main.name, "--full", "--out-dir", str(work / "fi"))
    res["full"] = {**summary(rc2, out2, rep2), "seconds": round(sec2)}
    ours = work / "fi" / f"{stem}.pdf"
    if rc2 != 0 or not ours.is_file():
        return res
    try:
        report = compare_pdfs(ref / pdf.name, ours)
        names = [main.name] + [f"{i.arg}.tex" for i in analyse(Config(main=main)).includes]
        compare_synctex(ref / pdf.name, ours, [dist.synctex_query(main.parent, n) for n in names],
                        main.parent, report=report)
        res["vs_latexmk"] = "PASS" if report.ok else "FAIL"
        res["vs_latexmk_summary"] = report.summary().splitlines()[:12]
    except Exception as err:  # noqa: BLE001 - recorded, the sweep goes on
        res["vs_latexmk"] = f"error: {err}"[:200]
    return res


def chapmk(cwd: Path, *args: str) -> tuple[int, str, dict[str, Any], float]:
    report = cwd.parent / "report.json"
    report.unlink(missing_ok=True)
    t = time.monotonic()
    try:
        r = subprocess.run(
            ["python3", "-m", "chapmk", "build", *args, "--report", str(report), "-j", "4", "-v"],
            cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, errors="replace",
        )
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        rc, out = -1, f"timeout after {TIMEOUT} s\n{e.stdout or ''}{e.stderr or ''}"
    rep = json.loads(report.read_text()) if report.is_file() else {}
    return rc, out, rep, time.monotonic() - t


def summary(rc: int, out: str, rep: dict[str, Any]) -> dict[str, Any]:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    keep = [ln for ln in lines if re.search(
        r"warning|full build|cold build|self-check|PASS|FAIL|differ|rror|Traceback|timeout", ln)]
    return {
        "rc": rc,
        "mode": rep.get("mode"),
        "reason": rep.get("reason"),
        "compiled": rep.get("compiled"),
        "runs": len(rep.get("runs", [])),
        "check": "PASS" if any("PASS" in ln for ln in lines) else
                 "FAIL" if any("FAIL" in ln for ln in lines) else None,
        "messages": keep[:25] + (lines[-8:] if rc != 0 else []),
    }


def variant(root: Path, main: Path) -> list[str]:
    """Robustness variant (chapmk's correctness, not the original output): font setup of the
    Unicode engines commented out, bookmark added to hyperref, BibTeX replaced by biblatex
    with biber. Returns the transformations applied."""
    applied: list[str] = []
    texs = [p for p in root.rglob("*.tex") if p.is_file() and not p.is_symlink()]
    for p in texs:
        lines = p.read_text(errors="surrogateescape").split("\n")
        new = ["% sweep: " + ln if FONT_LINES.match(ln) else ln for ln in lines]
        if new != lines:
            p.write_text("\n".join(new), errors="surrogateescape")
            if "no-fontspec" not in applied:
                applied.append("no-fontspec")
    all_text = "".join(p.read_text(errors="replace") for p in texs)
    extra = ""
    if "hyperref" in all_text and "{bookmark}" not in all_text:
        extra += "\\usepackage{bookmark}\n"
        applied.append("bookmark")
    if "biblatex" not in all_text:
        bibs: list[str] = []
        for p in texs:
            t = p.read_text(errors="surrogateescape")
            found = BIB.findall(t)
            if not found:
                continue
            bibs += [b.strip() for _, arg in found for b in arg.split(",")]
            t = BIB.sub(lambda m: m.group(1) + "\\printbibliography", t)
            t = re.sub(r"(?m)^\s*\\bibliographystyle\{[^}]*\}", "", t)
            t = re.sub(r"(?m)^\s*\\usepackage(\[[^\]]*\])?\{(natbib|cite)\}", "", t)
            p.write_text(t, errors="surrogateescape")
        if bibs:
            extra += "\\usepackage[backend=biber,natbib=true]{biblatex}\n" + "".join(
                f"\\addbibresource{{{b if b.endswith('.bib') else b + '.bib'}}}\n" for b in bibs
            )
            applied.append("biblatex")
    if extra:
        text = main.read_text(errors="surrogateescape")
        main.write_text(text.replace("\\begin{document}", extra + "\\begin{document}", 1),
                        errors="surrogateescape")
    return applied


def typo(main: Path) -> str | None:
    """Change one plain text line in the middle \\include'd file; returns file:line."""
    names = INCLUDE.findall(main.read_text(errors="replace"))
    order = names[len(names) // 2 :] + names[: len(names) // 2]
    for name in order:
        f = main.parent / (name if name.endswith(".tex") else f"{name}.tex")
        if not f.is_file():
            continue
        lines = f.read_text(errors="surrogateescape").split("\n")
        for i, ln in enumerate(lines):
            if PLAIN.match(ln.strip()):
                lines[i] = ln.rstrip() + " Typo"
                f.write_text("\n".join(lines), errors="surrogateescape")
                return f"{name}:{i + 1}"
    return None


def sweep_one(entry: dict[str, Any]) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(dir="/sweep/work"))
    root = work / "doc"
    shutil.copytree(entry["root"], root, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", ".chapmk"))
    main = root / entry["main"]
    res: dict[str, Any] = {"id": entry["id"]}
    if VARIANT:
        res["variant"] = variant(root, main)
    if LATEXMK:
        res["reference"] = latexmk_vs_full(work, main)
    rc, out, rep, sec = chapmk(main.parent, main.name, "--check")
    res["cold"] = {**summary(rc, out, rep), "seconds": round(sec)}
    if rc == 0:
        res["edit"] = typo(main)
        if res["edit"]:
            rc, out, rep, sec = chapmk(main.parent, main.name, "--check")
            res["typo"] = {**summary(rc, out, rep), "seconds": round(sec)}
    else:  # does the document build at all (plain full mode)?
        rc2, out2, rep2, sec2 = chapmk(main.parent, main.name, "--full")
        res["full"] = {**summary(rc2, out2, rep2), "seconds": round(sec2)}
    ok = (res.get("reference") or {}).get("vs_latexmk", "PASS") == "PASS" and all(
        (res.get(k) or {}).get("rc", 0) == 0 and (res.get(k) or {}).get("check") != "FAIL"
             for k in ("cold", "typo"))
    if ok:
        shutil.rmtree(work, ignore_errors=True)
    else:
        res["workdir"] = str(work)
    return res


def main() -> int:
    global VARIANT, LATEXMK
    args = sys.argv[1:]
    while args and args[0].startswith("--"):
        VARIANT |= args[0] == "--variant"
        LATEXMK |= args[0] == "--latexmk"
        args = args[1:]
    manifest, results = Path(args[0]), Path(args[1])
    only = set(args[2:])
    entries = json.loads(manifest.read_text())
    done = set()
    if results.is_file():
        done = {json.loads(ln)["id"] for ln in results.read_text().splitlines() if ln}
    for e in entries:
        if (only and e["id"] not in only) or (not only and e["id"] in done):
            continue
        print(f"== {e['id']}", flush=True)
        res = sweep_one(e)
        with results.open("a") as f:
            f.write(json.dumps(res) + "\n")
        print(json.dumps({k: (v.get("mode"), v.get("check"), v.get("rc")) if isinstance(v, dict)
                          else v for k, v in res.items()}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
