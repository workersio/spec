#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
  echo "usage: .workers/run-with-postgres.sh <command> [args...]" >&2
  exit 64
fi

PGDATA="${WIO_PGDATA:-/tmp/wio-postgres-data}"
PGLOG="${WIO_PGLOG:-/tmp/wio-postgres.log}"
INITLOG="${WIO_PG_INITLOG:-/tmp/wio-postgres-initdb.log}"
PGHOST_ADDR="${WIO_PGHOST_ADDR:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
if [ -n "${WIO_PG_EXTENSION_DIR:-}" ]; then
  EXT_DIR="${WIO_PG_EXTENSION_DIR}"
elif command -v pg_config >/dev/null 2>&1; then
  EXT_DIR="$(pg_config --sharedir)/extension"
else
  EXT_DIR="/usr/share/postgresql16/extension"
fi

if ! command -v initdb >/dev/null 2>&1 || ! command -v postgres >/dev/null 2>&1 || ! command -v pg_ctl >/dev/null 2>&1; then
  echo "setup-block: postgres binaries are not available in the WIO guest" >&2
  exit 44
fi

if [ ! -f "${EXT_DIR}/uuid-ossp.control" ]; then
  if [ ! -d "${EXT_DIR}" ] || [ ! -w "${EXT_DIR}" ]; then
    echo "setup-block: postgres uuid-ossp extension is missing and ${EXT_DIR} is not writable" >&2
    exit 44
  fi
  cat >"${EXT_DIR}/uuid-ossp.control" <<'EOF'
comment = 'WIO compatibility uuid-ossp extension marker'
default_version = '1.0'
relocatable = true
trusted = true
EOF
  cat >"${EXT_DIR}/uuid-ossp--1.0.sql" <<'EOF'
-- Most products use built-in gen_random_uuid(); this marker satisfies CREATE EXTENSION.
EOF
fi

rm -rf "${PGDATA}"
mkdir -p "${PGDATA}"
chown postgres:postgres "${PGDATA}"

su postgres -c "initdb -D '${PGDATA}' -A trust --encoding=UTF8 --no-locale" >"${INITLOG}" 2>&1
su postgres -c "pg_ctl -D '${PGDATA}' -l '${PGLOG}' -o \"-k /tmp -h '${PGHOST_ADDR}' -p '${PGPORT}'\" start" >>"${INITLOG}" 2>&1

cleanup() {
  su postgres -c "pg_ctl -D '${PGDATA}' -m fast stop" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if pg_isready -h "${PGHOST_ADDR}" -p "${PGPORT}" -U postgres >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "${ready}" != "1" ]; then
  echo "setup-block: postgres did not become ready on ${PGHOST_ADDR}:${PGPORT}" >&2
  echo "initdb log:" >&2
  sed -n '1,120p' "${INITLOG}" >&2 || true
  echo "postgres log:" >&2
  sed -n '1,160p' "${PGLOG}" >&2 || true
  exit 44
fi

export PGPASSWORD="${PGPASSWORD:-wio}"
"$@"
