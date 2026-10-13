#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: run-baseline.sh <target-url> [report-name]}"
report="${2:-zap-baseline}"
zap_dir="$(cd "$(dirname "$0")" && pwd)"
reports_dir="${ZAP_REPORTS_DIR:-$zap_dir/../../zap-report}"
image="${ZAP_IMAGE:-zaproxy/zap-stable:2.17.0}"

mkdir -p "$reports_dir"
chmod 777 "$reports_dir"

docker run --rm --network host \
  --volume "$zap_dir:/zap/config:ro" \
  --volume "$reports_dir:/zap/wrk:rw" \
  "$image" zap-baseline.py \
  -t "$target" \
  -c /zap/config/rules.tsv \
  -r "$report.html" \
  -J "$report.json" \
  -I
