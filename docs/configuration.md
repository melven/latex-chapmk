# Configuration: `chapmk.toml`

`chapmk.toml` is optional. chapmk reads it from the directory of the main file (or the
current directory when no main file is given). Relative paths are relative to the file.
Command-line options override the file. Unknown keys are an error (exit code 2).

```toml
main = "thesis.tex"            # main file when none is given on the command line
jobs = 0                       # parallel pdflatex processes; 0 = number of CPUs
build_dir = ".chapmk/thesis"   # default: .chapmk/<jobname> next to the main file
out_dir = "."                  # where <jobname>.pdf/.synctex.gz/.log go; default: next to main

[format]
split_before = []              # regexes: the precompiled preamble ends before the first match

[units]
heading = []                   # extra chapter-level heading commands, e.g. ["mychapter"]

[lint]
allow = []                     # commands allowed in unit bodies outside groups, e.g. ["\\setlength"]
verbatim = []                  # extra verbatim environments, e.g. ["codeexample"]
shortverb = []                 # short-verbatim delimiters, e.g. ["|"]

[state]
ignore = []                    # \count registers that number run-local objects, e.g. ["mycounter@id"]

[pictures]
cache = true                   # false: typeset TikZ pictures inline even with \tikzexternalize
```

## Keys

| Key | Default | Meaning |
|---|---|---|
| `main` | none | Main `.tex` file. Required if `chapmk` is called without one. |
| `jobs` | `0` | Parallel pdflatex processes (`-j`); `0` uses the number of CPUs. |
| `build_dir` | `.chapmk/<jobname>` | Build directory (`--build-dir`). Each job name needs its own; `chapmk clean` removes it. |
| `out_dir` | directory of `main` | Output directory for the PDF, SyncTeX file and log (`--out-dir`). |
| `format.split_before` | `[]` | chapmk precompiles the preamble up to a split point; packages that must run at every start (e.g. code that creates PDF images) go after it. Lines matching one of these regular expressions end the precompiled part. A built-in list covers the known cases. |
| `units.heading` | `[]` | Commands that, as the first command of an `\include`d file, start a new compilation unit, in addition to `\chapter`, `\addchap`, `\part`, `\addpart` (and starred forms). |
| `lint.allow` | `[]` | Commands chapmk should not report when a unit body uses them outside a group. Only for commands whose effect is local to the unit; otherwise later units may be built with a wrong state. |
| `lint.verbatim` | `[]` | Environments whose content the lint skips (besides `verbatim`, `lstlisting`, …). |
| `lint.shortverb` | `[]` | Characters used as `\MakeShortVerb` delimiters. |
| `state.ignore` | `[]` | Names of `\count` registers (without backslash) that number objects created in a run, like hyperref's `Hy@abspage`. They are not compared between runs. Needed only if a build reports a changing state for such a register. |
| `pictures.cache` | `true` | With `\tikzexternalize`, chapmk makes and reuses the figures itself (result equal to an externalized build). `false` typesets every picture inline. |

Removed in 0.9: `aux.self` and `aux.ignore` (they had no effect); setting them is an error.
