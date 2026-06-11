#!/bin/sh
set -eu

awk '
  /^-- migrate:up/ { in_up = 1; next }
  /^-- migrate:down/ { in_up = 0 }
  in_up { print }
' /gpt2giga-migrations/0001_traffic_logs.sql \
  | psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1
