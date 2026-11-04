# Dev and CI image for chapmk: TeX Live (full scheme) + Python tooling.
# The base image is pinned by digest (R12): TeX Live 2026 as used by CI on 2026-11-03.
# To update: build with texlive/texlive:latest, take the digest from the build log, run the
# full suite (the reference cache is keyed by the TeX installation).
# Other TeX Live versions (.github/workflows/versions.yml):
#   docker build --build-arg TEXLIVE_IMAGE=texlive/texlive:TL2024-historic -t chapmk-dev-tl2024 .
ARG TEXLIVE_IMAGE=texlive/texlive:latest@sha256:07e8062637249c4f780ca59f42cc2ed592bc2dc1db4320769406aee3f98aa70e
FROM ${TEXLIVE_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/melven/latex-chapmk" \
      org.opencontainers.image.description="chapmk dev and CI image: TeX Live full, Python tooling"

ARG USERNAME=dev
ARG UID=1000
ARG GID=1000

# poppler-utils: pdftoppm / pdftotext for acceptance tests (design §3.3)
# gnuplot-data: gnuplot-lua-tikz.sty is not part of TeX Live; Debian installs it
# to /usr/share/texmf, which this TeX Live does not search -> link into TEXMFLOCAL.
# apt over https: works behind HTTPS-only (CONNECT) proxies
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
      /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null; \
    apt-get update \
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
# Optional CA bundle for TLS-intercepting proxies (not stored in the image):
#   docker build --secret id=ca,src=/path/to/ca-bundle.crt ...
# The file replaces pip's default bundle, so it must include the public CAs.
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir -r /tmp/requirements-dev.txt

# Fail the build early if a required tool is missing
RUN set -e; \
    for t in pdflatex latexmk biber makeindex synctex kpsewhich pdftoppm pdftotext; do \
      command -v "$t" >/dev/null || { echo "missing: $t"; exit 1; }; \
    done; \
    for f in mylatexformat.ltx nomencl.sty biblatex.sty hyperref.sty gnuplot-lua-tikz.sty; do \
      kpsewhich "$f" >/dev/null || { echo "missing: $f"; exit 1; }; \
    done; \
    python -c "import pikepdf, pytest_cov, hypothesis"

# Non-root user (devcontainer); reuse an existing user with this UID if the base image has one
RUN set -e; \
    if ! getent group "$GID" >/dev/null; then groupadd -g "$GID" "$USERNAME"; fi; \
    if ! getent passwd "$UID" >/dev/null; then useradd -m -u "$UID" -g "$GID" -s /bin/bash "$USERNAME"; fi; \
    chown -R "$UID:$GID" "$VIRTUAL_ENV"
USER ${UID}:${GID}

# SOURCE_DATE_EPOCH / FORCE_SOURCE_DATE are set by the driver per build (design N4),
# deliberately not here, so a driver that forgets them is not masked.
ENV max_print_line=10000

WORKDIR /work
