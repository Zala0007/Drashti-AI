#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
export RETRY_DELAY_SECONDS=0 RETRY_ATTEMPTS=3

bash retry.sh bash -c '[[ "$1" == "argument with spaces" ]]' _ 'argument with spaces'

counter=0
flaky() {
  counter=$((counter + 1))
  ((counter >= 3))
}
export -f flaky
# Source in a subshell so the simulated transient error retains its counter.
(set -- flaky; source ./retry.sh)

if bash retry.sh bash -c 'exit 42'; then
  echo 'Persistent failure was incorrectly accepted.' >&2
  exit 1
else
  [[ $? == 42 ]]
fi
if RETRY_ATTEMPTS=0 bash retry.sh true; then
  exit 1
else
  [[ $? == 2 ]]
fi
echo 'Retry checks passed: success, recovery, exhaustion, arguments, invalid config.'
