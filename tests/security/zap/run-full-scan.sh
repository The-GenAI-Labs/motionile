#!/usr/bin/env bash
set -euo pipefail

mode="${1:?usage: run-full-scan.sh <web|api> <target-url> [report-name]}"
target="${2:?usage: run-full-scan.sh <web|api> <target-url> [report-name]}"
report="${3:-zap-$mode-full}"
zap_dir="$(cd "$(dirname "$0")" && pwd)"
reports_dir="${ZAP_REPORTS_DIR:-$zap_dir/../../../zap-report}"
image="${ZAP_IMAGE:-zaproxy/zap-stable:2.17.0}"

case "$mode" in
  web) scan=(zap-full-scan.py -t "$target" -m "${ZAP_SPIDER_MINUTES:-5}") ;;
  api) scan=(zap-api-scan.py -t "$target" -f openapi) ;;
  *)
    echo "mode must be web or api" >&2
    exit 2
    ;;
esac

mkdir -p "$reports_dir"
chmod 777 "$reports_dir"

docker run --rm --network host \
  --volume "$zap_dir:/zap/config:ro" \
  --volume "$reports_dir:/zap/wrk:rw" \
  "$image" "${scan[@]}" \
  -c /zap/config/rules.tsv \
  -r "$report.html" \
  -J "$report.json" \
  -I
