# Dev and CI image for fastinc: TeX Live (full scheme) + Python tooling.
# For reproducibility, pin the base image by digest once M1 is green, e.g.
#   FROM texlive/texlive:latest@sha256:<digest>
FROM texlive/texlive:latest

ARG USERNAME=dev
ARG UID=1000
ARG GID=1000

# poppler-utils: pdftoppm / pdftotext for acceptance tests (PLAN.md §3.3)
# gnuplot-data: gnuplot-lua-tikz.sty is not part of TeX Live; Debian installs it
# to /usr/share/texmf, which this TeX Live does not search -> link into TEXMFLOCAL.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip poppler-utils git ca-certificates gnuplot-data \
 && rm -rf /var/lib/apt/lists/* \
 && d="$(kpsewhich -var-value TEXMFLOCAL)/tex/latex/gnuplot-lua-tikz" \
 && mkdir -p "$d" \
 && ln -s /usr/share/texmf/tex/*gnuplot-lua-tikz* "$d"/ \
 && mktexlsr "$(kpsewhich -var-value TEXMFLOCAL)"

# Python venv outside the repo; on PATH for every shell
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

# Fail the build early if a required tool is missing
RUN set -e; \
    for t in pdflatex latexmk biber makeindex synctex kpsewhich pdftoppm pdftotext; do \
      command -v "$t" >/dev/null || { echo "missing: $t"; exit 1; }; \
    done; \
    for f in mylatexformat.ltx nomencl.sty biblatex.sty hyperref.sty gnuplot-lua-tikz.sty; do \
      kpsewhich "$f" >/dev/null || { echo "missing: $f"; exit 1; }; \
    done; \
    python -c "import pikepdf, numpy, PIL"

# Non-root user (devcontainer); reuse an existing user with this UID if the base image has one
RUN set -e; \
    if ! getent group "$GID" >/dev/null; then groupadd -g "$GID" "$USERNAME"; fi; \
    if ! getent passwd "$UID" >/dev/null; then useradd -m -u "$UID" -g "$GID" -s /bin/bash "$USERNAME"; fi; \
    chown -R "$UID:$GID" "$VIRTUAL_ENV"
USER ${UID}:${GID}

# SOURCE_DATE_EPOCH / FORCE_SOURCE_DATE are set by the driver per build (PLAN.md N4),
# deliberately not here, so a driver that forgets them is not masked.
ENV max_print_line=10000

WORKDIR /work
