#!/bin/sh
set -e

ARGS="--writable --port 7681"

# Add basic auth if TTYD_CREDENTIAL is set (format: user:password)
if [ -n "$TTYD_CREDENTIAL" ]; then
    ARGS="$ARGS --credential $TTYD_CREDENTIAL"
fi

exec ttyd $ARGS uv run python scripts/play.py "$@"
