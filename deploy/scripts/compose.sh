#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
export LOG_SCOPE=compose

if [[ $# -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<USAGE
Usage: compose.sh <docker compose arguments>

Runs docker compose with the production files, $ENV_FILE and the image tags of the
current deployment, for example:
  compose.sh ps
  compose.sh logs --follow --tail 200 api
  compose.sh restart worker-default
USAGE
  exit 0
fi

compose "$@"
