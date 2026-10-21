#!/bin/sh
set -e

alembic -c alembic.ini upgrade head

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# One worker by default: the AI rate limiter and confirmation replay-protection are
# in-process. Move them to a shared store (e.g. Redis) before raising WEB_CONCURRENCY.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-1}" --proxy-headers
