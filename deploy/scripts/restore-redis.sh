#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
export LOG_SCOPE=restore-redis

readonly REDIS_DATA_DIR="${MOTIONILE_ROOT}/data/redis"
readonly APPLICATION_SERVICES=(api mcp worker-default worker-generation worker-render)

usage() {
  cat <<USAGE
Usage: restore-redis.sh --list
       restore-redis.sh <timestamp|latest> --yes

Lists backups, or replaces the Redis data with the backup taken at <timestamp>
(for example 20261014T210312Z). Application services are stopped during the restore
and started again afterwards. --yes confirms that current Redis data is discarded.
USAGE
}

list_backups() {
  aws s3 ls --region "$AWS_REGION" "s3://$1/redis/$2/" | awk '$1 == "PRE" { print $2 }' | tr -d '/'
}

main() {
  if [[ $# -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    [[ $# -eq 0 ]] && exit 2
    exit 0
  fi
  load_instance_environment
  local bucket environment
  bucket=$(env_value BACKUP_BUCKET)
  environment=$(env_value APP_ENV)

  if [[ "$1" == "--list" ]]; then
    list_backups "$bucket" "$environment"
    exit 0
  fi
  [[ "${2:-}" == "--yes" ]] || die "pass --yes to confirm that current Redis data is replaced"

  local stamp="$1"
  if [[ "$stamp" == "latest" ]]; then
    stamp=$(list_backups "$bucket" "$environment" | sort | tail -n 1)
    [[ -n "$stamp" ]] || die "no backups found under s3://$bucket/redis/$environment/"
  fi
  [[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "invalid timestamp: $stamp"

  local work_dir
  work_dir=$(mktemp -d)
  trap 'rm -rf "$work_dir"' EXIT
  local source_prefix="s3://${bucket}/redis/${environment}/${stamp}"
  log "downloading $source_prefix"
  aws s3 cp --region "$AWS_REGION" --only-show-errors "$source_prefix/dump.rdb" "$work_dir/restore/dump.rdb"
  aws s3 cp --region "$AWS_REGION" --only-show-errors "$source_prefix/appendonly.tar.gz" "$work_dir/appendonly.tar.gz"
  tar -C "$work_dir/restore" -xzf "$work_dir/appendonly.tar.gz"

  local redis_image
  redis_image=$(compose config --format json | jq -r '.services.redis.image')

  log "stopping application services and Redis"
  compose stop "${APPLICATION_SERVICES[@]}" redis

  log "replacing $REDIS_DATA_DIR with backup $stamp"
  docker run --rm \
    --volume "$REDIS_DATA_DIR:/data" \
    --volume "$work_dir/restore:/restore:ro" \
    --entrypoint sh \
    "$redis_image" \
    -c 'rm -rf /data/appendonlydir /data/dump.rdb && cp -a /restore/dump.rdb /restore/appendonlydir /data/ && chown -R redis:redis /data'

  log "starting services"
  compose up --detach --wait --wait-timeout 180
  log "restored Redis from $stamp"
}

main "$@"
