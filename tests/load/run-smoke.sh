#!/usr/bin/env bash
set -euo pipefail

load_dir="$(cd "$(dirname "$0")" && pwd)"
image="${K6_IMAGE:-grafana/k6:2.3.0}"
reports_dir="${K6_REPORTS_DIR:-$load_dir/../../k6-report}"

if [[ $# -gt 0 ]]; then
  scenarios=("$@")
else
  scenarios=(smoke public explore)
fi

mkdir -p "$reports_dir"
chmod 777 "$reports_dir"

for scenario in "${scenarios[@]}"; do
  docker run --rm --network host \
    --volume "$load_dir:/load:ro" \
    --volume "$reports_dir:/reports:rw" \
    --env "API_BASE_URL=${API_BASE_URL:-http://localhost:8000}" \
    --env "WEB_BASE_URL=${WEB_BASE_URL:-http://localhost:3000}" \
    --env "LOAD_PROFILE=${LOAD_PROFILE:-smoke}" \
    --env AUTH_LOAD_ACCOUNTS \
    "$image" run --summary-export "/reports/${scenario}.json" "/load/scenarios/${scenario}.js"
done
