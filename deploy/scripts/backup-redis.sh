#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
export LOG_SCOPE=backup-redis

readonly SAVE_TIMEOUT_SECONDS="${REDIS_SAVE_TIMEOUT_SECONDS:-600}"

usage() {
  cat <<USAGE
Usage: backup-redis.sh

Triggers BGSAVE, waits for it to finish and uploads dump.rdb and the AOF directory to
s3://<BACKUP_BUCKET>/redis/<APP_ENV>/<UTC timestamp>/.
USAGE
}

redis_cli() {
  compose exec -T redis redis-cli "$@" | tr -d '\r'
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi
  load_instance_environment
  local bucket environment
  bucket=$(env_value BACKUP_BUCKET)
  environment=$(env_value APP_ENV)

  local last_save
  last_save=$(redis_cli LASTSAVE)
  log "requesting BGSAVE"
  redis_cli BGSAVE >/dev/null

  local waited=0
  until [[ "$(redis_cli LASTSAVE)" != "$last_save" ]]; do
    ((waited >= SAVE_TIMEOUT_SECONDS)) && die "BGSAVE did not finish within ${SAVE_TIMEOUT_SECONDS}s"
    sleep 2
    waited=$((waited + 2))
  done
  redis_cli INFO persistence | grep -q '^rdb_last_bgsave_status:ok$' || die "BGSAVE reported a failure"

  local work_dir
  work_dir=$(mktemp -d)
  trap 'rm -rf "$work_dir"' EXIT
  compose cp redis:/data/dump.rdb "$work_dir/dump.rdb"
  compose cp redis:/data/appendonlydir "$work_dir/appendonlydir"
  tar -C "$work_dir" -czf "$work_dir/appendonly.tar.gz" appendonlydir

  local stamp destination
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  destination="s3://${bucket}/redis/${environment}/${stamp}"
  aws s3 cp --region "$AWS_REGION" --only-show-errors "$work_dir/dump.rdb" "$destination/dump.rdb"
  aws s3 cp --region "$AWS_REGION" --only-show-errors "$work_dir/appendonly.tar.gz" "$destination/appendonly.tar.gz"
  log "uploaded backup to $destination"
}

main "$@"
