#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_dir/../.." && pwd)"
catalog="$repository_root/deploy/parameters.csv"
region="${AWS_REGION:-ap-south-1}"

usage() {
  cat <<USAGE
Usage: put-parameters.sh <staging|production> <values-file>

Uploads every NAME=value line of <values-file> as a SecureString parameter named
/motionile/<environment>/NAME. Only parameters whose source is "owner" in
deploy/parameters.csv are accepted. Values never appear on a command line or in output.
Keep <values-file> outside git, for example infra/parameters/staging.env (ignored).

Environment: AWS_REGION (default ap-south-1), AWS_PROFILE as usual for the AWS CLI.
USAGE
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

environment="$1"
values_file="$2"
[[ "$environment" == "staging" || "$environment" == "production" ]] || fail "environment must be staging or production"
[[ -r "$values_file" ]] || fail "cannot read $values_file"
[[ -r "$catalog" ]] || fail "cannot read $catalog"
command -v aws >/dev/null || fail "the AWS CLI v2 is required"

mapfile -t owner_names < <(tail -n +2 "$catalog" | awk -F, '$2 == "owner" { print $1 }')
mapfile -t required_owner_names < <(tail -n +2 "$catalog" | awk -F, '$2 == "owner" && $3 == "yes" { print $1 }')

umask 077
value_file=$(mktemp)
trap 'rm -f "$value_file"' EXIT

declare -A uploaded=()
line_number=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line_number=$((line_number + 1))
  [[ -z "${line//[[:space:]]/}" ]] && continue
  [[ "$line" == *=* ]] || fail "line $line_number is not NAME=value"
  name="${line%%=*}"
  value="${line#*=}"
  [[ " ${owner_names[*]} " == *" $name "* ]] || fail "line $line_number: $name is not an owner parameter in deploy/parameters.csv"
  [[ -n "$value" ]] || fail "line $line_number: $name has an empty value"
  [[ "$value" != *"'"* ]] || fail "line $line_number: $name contains a single quote, which the server env file cannot hold"
  printf '%s' "$value" >"$value_file"
  aws ssm put-parameter \
    --region "$region" \
    --name "/motionile/${environment}/${name}" \
    --type SecureString \
    --tier Standard \
    --overwrite \
    --value "file://$value_file" \
    --output text >/dev/null
  uploaded["$name"]=1
  printf 'stored /motionile/%s/%s\n' "$environment" "$name"
done <"$values_file"

missing=()
for name in "${required_owner_names[@]}"; do
  [[ -n "${uploaded[$name]:-}" ]] || missing+=("$name")
done
if ((${#missing[@]} > 0)); then
  printf 'note: %s were not in this file; render-env.sh fails until they exist in SSM\n' "${missing[*]}"
fi
