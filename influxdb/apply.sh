#!/bin/sh
# Apply influxdb/manifest.yml idempotently, via a single named stack.
#
# WHY THIS EXISTS
# ---------------
# `influx apply` WITHOUT --stack-id mints a brand-new stack on every invocation,
# and each stack owns its own copy of every resource it creates. Buckets survive
# this because bucket names are unique-constrained, so a second apply reuses
# them. TASK NAMES ARE NOT UNIQUE -- so every `docker compose up` silently added
# another 12 duplicate downsample tasks, each recomputing the same windows on the
# same schedule. This was observed in the wild: 4 stacks -> 48 tasks where the
# manifest declares 12.
#
# Pinning one named stack makes repeated applies UPDATE in place, which is what
# `influx apply` is idempotent *relative to*.
#
# NOTE: `influx stacks remove` deletes every resource in the stack, INCLUDING
# BUCKETS AND THEIR DATA. Do not "clean up" stacks casually.
set -eu

HOST="${INFLUX_HOST:-http://influxdb:8086}"
ORG="${DOCKER_INFLUXDB_INIT_ORG}"
TOKEN="${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN}"
STACK_NAME="${INFLUX_STACK_NAME:-digsiviz}"

sid=$(influx stacks --host "$HOST" --org "$ORG" --token "$TOKEN" \
        --stack-name "$STACK_NAME" --hide-headers 2>/dev/null | awk 'NR==1 {print $1}')

if [ -z "${sid:-}" ]; then
  sid=$(influx stacks init --host "$HOST" --org "$ORG" --token "$TOKEN" \
          --stack-name "$STACK_NAME" --hide-headers | awk 'NR==1 {print $1}')
  echo "influx-setup: created stack '$STACK_NAME' ($sid)"
else
  echo "influx-setup: reusing stack '$STACK_NAME' ($sid)"
fi

exec influx apply \
  --host "$HOST" \
  --org "$ORG" \
  --token "$TOKEN" \
  --stack-id "$sid" \
  --file /manifest.yml \
  --force yes
