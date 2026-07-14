#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, run migrations, then serve.
set -euo pipefail

echo "[entrypoint] waiting for postgres at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}"
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -q; do
  sleep 1
done

echo "[entrypoint] applying migrations"
alembic upgrade head

if [ "${BOOTSTRAP_SUPERUSER:-true}" = "true" ]; then
  echo "[entrypoint] ensuring superuser exists"
  python scripts/create_superuser.py || echo "[entrypoint] superuser bootstrap skipped"
fi

echo "[entrypoint] starting api"
exec "$@"
