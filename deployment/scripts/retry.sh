#!/usr/bin/env bash
# Retry idempotent network/build operations; never wrap migrations or deployment.
set -Eeuo pipefail

attempts=${RETRY_ATTEMPTS:-4}
delay=${RETRY_DELAY_SECONDS:-10}
if [[ ! "$attempts" =~ ^[1-9][0-9]*$ || ! "$delay" =~ ^[0-9]+$ || $# -eq 0 ]]; then
  echo 'Usage: retry.sh command [args...]; attempts must be positive, delay nonnegative.' >&2
  exit 2
fi

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if "$@"; then
    exit 0
  else
    status=$?
  fi
  if ((attempt == attempts)); then
    echo "Operation failed after $attempt attempts (exit $status)." >&2
    exit "$status"
  fi
  echo "Attempt $attempt failed (exit $status); retrying in ${delay}s." >&2
  sleep "$delay"
  delay=$((delay * 2))
done
