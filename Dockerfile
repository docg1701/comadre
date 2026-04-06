FROM python:3.12-slim

# System dependencies: ffmpeg (with AAC), libsndfile, build deps for espeak-ng
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        cmake \
        pkg-config \
        gcc \
        g++ \
        make \
        libsonic-dev \
    && rm -rf /var/lib/apt/lists/*

# Build espeak-ng from source — pinned 2026-03-24, includes PR #2344 pt-BR improvements
RUN git init /tmp/espeak-ng

WORKDIR /tmp/espeak-ng
RUN git fetch --depth 1 https://github.com/espeak-ng/espeak-ng.git 675d77226b16105e96382d38ee27c0ad9660fa1e && \
    git checkout FETCH_HEAD
RUN cmake -B build -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_SHARED_LIBS=ON && \
    cmake --build build -j"$(nproc)" && \
    cmake --install build && \
    ldconfig

# Copy custom pt_extra dictionary and compile from dictsource dir
COPY deploy/espeak-ng/pt_extra /tmp/espeak-ng/dictsource/pt_extra
WORKDIR /tmp/espeak-ng/dictsource
RUN espeak-ng --compile=pt

# Install uv for Python dependency management
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv

# Copy project files for dependency installation
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Install Python dependencies (production only)
RUN uv sync --frozen --no-dev

# Copy compiled espeak-ng pt data to misaki/espeakng_loader bundled path
# (misaki ignores ESPEAK_DATA_PATH — both paths must have the data)
RUN LOADER_DATA=$(python -c "import sys; sys.path.insert(0, '.venv/lib/python3.12/site-packages'); import espeakng_loader; print(espeakng_loader.get_data_path())") && \
    cp /usr/local/share/espeak-ng-data/pt_dict "$LOADER_DATA/" && \
    cp /usr/local/share/espeak-ng-data/phondata "$LOADER_DATA/" && \
    cp /usr/local/share/espeak-ng-data/phonindex "$LOADER_DATA/" && \
    cp /usr/local/share/espeak-ng-data/phontab "$LOADER_DATA/"

# Clean up espeak-ng source and build dependencies
# Protect libstdc++6 from autoremove (required by onnxruntime at runtime)
RUN rm -rf /tmp/espeak-ng && \
    apt-mark manual libstdc++6 && \
    apt-get purge -y \
        cmake \
        pkg-config \
        gcc \
        g++ \
        make \
        git \
    && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copy qwen3-tts-cli binary
COPY deploy/bin/qwen3-tts-cli /usr/local/bin/qwen3-tts-cli
RUN chmod +x /usr/local/bin/qwen3-tts-cli

# Copy noise WAV files for post-processing
COPY noise/ /app/noise/

# Copy entrypoint script
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh

# Create non-root user and volume mount points
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /models /audio /voices && \
    chown -R appuser:appuser /app /models /audio /voices

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
