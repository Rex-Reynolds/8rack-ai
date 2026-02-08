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

# Entrypoint script handles auth flag
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 7681

# Set TTYD_CREDENTIAL=user:password to enable basic auth
ENTRYPOINT ["/app/entrypoint.sh"]
