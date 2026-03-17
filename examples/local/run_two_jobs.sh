#!/usr/bin/env bash

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (e.g. brew install jq)" >&2
  exit 1
fi

# Submit job 1
job1=$(pxq add "python3 examples/local/job1_sleep_hello.py" | jq -re '.id | tostring')

# Submit job 2
job2=$(pxq add "python3 examples/local/job2_sleep_hello.py" | jq -re '.id | tostring')

echo "Job IDs: $job1 $job2"

timeout_seconds=300
poll_interval_seconds=2
start_ts=$(date +%s)

echo "Checking job status..."
while true; do
  now_ts=$(date +%s)
  elapsed_seconds=$((now_ts - start_ts))
  if [ "$elapsed_seconds" -ge "$timeout_seconds" ]; then
    echo "ERROR: timeout waiting for jobs ${job1} and ${job2}" >&2
    pxq status --all | jq --arg id1 "$job1" --arg id2 "$job2" '
      [(.jobs // .)[]
        | select((.id | tostring) == $id1 or (.id | tostring) == $id2)
        | {id, status, provider, exit_code, command}]
    ' >&2 || true
    exit 2
  fi

  filtered=$(pxq status --all | jq --arg id1 "$job1" --arg id2 "$job2" -c '
    [(.jobs // .)[]
      | select((.id | tostring) == $id1 or (.id | tostring) == $id2)
      | {id: (.id | tostring), status, provider, exit_code, command}]
  ')

  status1=$(printf "%s" "$filtered" | jq -r --arg id "$job1" 'map(select(.id == $id))[0].status // "unknown"')
  status2=$(printf "%s" "$filtered" | jq -r --arg id "$job2" 'map(select(.id == $id))[0].status // "unknown"')
  provider1=$(printf "%s" "$filtered" | jq -r --arg id "$job1" 'map(select(.id == $id))[0].provider // ""')
  provider2=$(printf "%s" "$filtered" | jq -r --arg id "$job2" 'map(select(.id == $id))[0].provider // ""')

  echo "[${elapsed_seconds}s/${timeout_seconds}s] ${job1}=${status1} ${job2}=${status2}"

  terminal1=false
  terminal2=false
  case "$status1" in succeeded|failed|cancelled|stopped) terminal1=true ;; esac
  case "$status2" in succeeded|failed|cancelled|stopped) terminal2=true ;; esac

  if [ "$terminal1" = true ] && [ "$terminal2" = true ]; then
    printf "%s" "$filtered" | jq .

    if [ "$status1" = "succeeded" ] && [ "$status2" = "succeeded" ]; then
      exit 0
    fi

    if [ "$status1" = "failed" ] || [ "$status2" = "failed" ] || [ "$status1" = "cancelled" ] || [ "$status2" = "cancelled" ]; then
      exit 1
    fi

    if { [ "$status1" = "stopped" ] && [ "$provider1" = "local" ]; } || { [ "$status2" = "stopped" ] && [ "$provider2" = "local" ]; }; then
      exit 1
    fi

    exit 1
  fi

  sleep "$poll_interval_seconds"
done
