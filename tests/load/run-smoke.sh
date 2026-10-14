#!/usr/bin/env bash
set -euo pipefail

load_dir="$(cd "$(dirname "$0")" && pwd)"
image="${K6_IMAGE:-grafana/k6:2.3.0}"
if [[ $# -gt 0 ]]; then
  scenarios=("$@")
else
  scenarios=(smoke public)
fi

for scenario in "${scenarios[@]}"; do
  docker run --rm --network host \
    --volume "$load_dir:/load:ro" \
    --env "API_BASE_URL=${API_BASE_URL:-http://localhost:8000}" \
    --env "WEB_BASE_URL=${WEB_BASE_URL:-http://localhost:3000}" \
    "$image" run "/load/scenarios/${scenario}.js"
done
