# Dev and CI image for fastinc: TeX Live (full scheme) + Python tooling.
# For reproducibility, pin the base image by digest once M1 is green, e.g.
#   FROM texlive/texlive:latest@sha256:<digest>
FROM texlive/texlive:latest

ARG USERNAME=dev
ARG UID=1000
ARG GID=1000

# poppler-utils: pdftoppm / pdftotext for acceptance tests (PLAN.md §3.3)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip poppler-utils git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python venv outside the repo; on PATH for every shell
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

# Fail the build early if a required tool is missing
RUN set -e; \
    for t in pdflatex biber makeindex synctex kpsewhich pdftoppm pdftotext; do \
      command -v "$t" >/dev/null || { echo "missing: $t"; exit 1; }; \
    done; \
    kpsewhich mylatexformat.ltx nomencl.sty biblatex.sty hyperref.sty >/dev/null; \
    python -c "import pikepdf, numpy, PIL"

# Non-root user (devcontainer); reuse an existing user with this UID if the base image has one
RUN set -e; \
    if ! getent group "$GID" >/dev/null; then groupadd -g "$GID" "$USERNAME"; fi; \
    if ! getent passwd "$UID" >/dev/null; then useradd -m -u "$UID" -g "$GID" -s /bin/bash "$USERNAME"; fi; \
    chown -R "$UID:$GID" "$VIRTUAL_ENV"
USER ${UID}:${GID}

ENV SOURCE_DATE_EPOCH=1700000000 \
    FORCE_SOURCE_DATE=1 \
    max_print_line=10000

WORKDIR /work
