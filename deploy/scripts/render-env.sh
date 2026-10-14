#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
export LOG_SCOPE=render-env

usage() {
  cat <<USAGE
Usage: render-env.sh

Reads /motionile/<environment>/* from SSM Parameter Store with decryption and writes
$ENV_FILE atomically with mode 600. Fails when a parameter marked required in
$PARAMETER_CATALOG is missing. Parameter values are never printed.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

load_instance_environment
[[ -r "$PARAMETER_CATALOG" ]] || die "missing $PARAMETER_CATALOG"
command -v jq >/dev/null || die "jq is required"

parameter_path="/motionile/${MOTIONILE_ENVIRONMENT}"
mapfile -t known_names < <(tail -n +2 "$PARAMETER_CATALOG" | cut -d, -f1)
mapfile -t required_names < <(tail -n +2 "$PARAMETER_CATALOG" | awk -F, '$3 == "yes" { print $1 }')

log "reading parameters under $parameter_path"
parameters_json=$(aws ssm get-parameters-by-path \
  --region "$AWS_REGION" \
  --path "$parameter_path" \
  --with-decryption \
  --output json)

umask 077
temporary_file=$(mktemp "${ENV_FILE}.XXXXXX")
trap 'rm -f "$temporary_file"' EXIT

declare -A present=()
while IFS= read -r -d '' name && IFS= read -r -d '' value; do
  [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "parameter name $name is not a valid environment variable name"
  if [[ ! " ${known_names[*]} " =~ \ ${name}\  ]]; then
    log "skipping $name: not listed in parameters.csv"
    continue
  fi
  [[ "$value" != *"'"* ]] || die "the value of $name contains a single quote, which the env file cannot represent"
  [[ "$value" != *$'\n'* ]] || die "the value of $name contains a newline; store multi-line values base64-encoded"
  printf "%s='%s'\n" "$name" "$value" >>"$temporary_file"
  present["$name"]=1
done < <(jq -j '.Parameters[] | (.Name | split("/") | last), "\u0000", .Value, "\u0000"' <<<"$parameters_json")

missing=()
for name in "${required_names[@]}"; do
  [[ -n "${present[$name]:-}" ]] || missing+=("$name")
done
if ((${#missing[@]} > 0)); then
  die "missing required parameters under $parameter_path: ${missing[*]}"
fi

chmod 600 "$temporary_file"
mv -f "$temporary_file" "$ENV_FILE"
trap - EXIT
log "wrote ${#present[@]} parameters to $ENV_FILE"
