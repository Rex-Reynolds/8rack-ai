FROM python:3.14-slim

# Install ttyd from GitHub release (not in Debian repos)
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget && \
    wget -qO /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.x86_64 && \
    chmod +x /usr/local/bin/ttyd && \
    apt-get purge -y wget && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

# Copy source and config
COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/

# Pre-build the card database (hits Scryfall API at build time)
RUN uv run python scripts/sync_cards.py

EXPOSE 7681

# ttyd serves the interactive game on port 7681
# --writable allows keyboard input
# TERM=xterm-256color ensures Rich colors work
CMD ["ttyd", "--writable", "--port", "7681", \
     "uv", "run", "python", "scripts/play.py"]
