#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

contract_paths=(apps/server/openapi.json packages/api-contract/src/generated)

snapshot() {
  git ls-files --cached --others --exclude-standard -- "${contract_paths[@]}" \
    | sort \
    | while read -r file; do
        if [[ -f "$file" ]]; then sha256sum "$file"; else echo "deleted $file"; fi
      done
}

before="$(snapshot)"
pnpm exec turbo run contract:generate --filter=@motionile/api-contract --output-logs=errors-only
after="$(snapshot)"

if [[ "${1:-}" == "--check" && "$before" != "$after" ]]; then
  echo "The API contract is out of date. Run 'pnpm contract:generate' and commit the result." >&2
  git --no-pager diff --stat -- "${contract_paths[@]}" >&2
  exit 1
fi
