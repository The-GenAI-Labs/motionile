#!/usr/bin/env bash
set -euo pipefail

log_opts="${1:---all}"
image="${GITLEAKS_IMAGE:-zricethezav/gitleaks:v8.30.1}"
repository="$(cd "$(dirname "$0")/.." && pwd)"

docker run --rm --volume "$repository:/repo:ro" --entrypoint sh "$image" -c \
  'git config --global --add safe.directory /repo && gitleaks git /repo --redact --verbose --exit-code 1 --log-opts="$0"' \
  "$log_opts"
