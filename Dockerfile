FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PANORAMA_LIBRARY_ROOT=/library \
    PANORAMA_DATA_DIR=/data \
    PANORAMA_XPANO_BIN=/usr/local/bin/Xpano \
    PANORAMA_HOST=0.0.0.0 \
    PANORAMA_PORT=3040 \
    PANORAMA_USE_XVFB=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        software-properties-common \
        python3 \
        python3-venv \
        python3-pip \
        libimage-exiftool-perl \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libx11-6 \
        libgomp1 \
        xvfb \
    && add-apt-repository -y ppa:krupkat/code \
    && apt-get update \
    && apt-get install -y --no-install-recommends xpano \
    && if command -v Xpano >/dev/null 2>&1; then \
         ln -sf "$(command -v Xpano)" /usr/local/bin/Xpano; \
       elif command -v xpano >/dev/null 2>&1; then \
         ln -sf "$(command -v xpano)" /usr/local/bin/Xpano; \
       else \
         echo "Xpano binary was not installed" >&2; exit 1; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .

RUN mkdir -p /data /library
EXPOSE 3040

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3040/healthz')"

CMD ["/opt/venv/bin/uvicorn", "pano_xpano.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "3040"]
