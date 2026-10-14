#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
export LOG_SCOPE=deploy

readonly WAIT_TIMEOUT_SECONDS="${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"
readonly CURRENT_TAG_FILE="${STATE_DIR}/current-tag"
readonly PREVIOUS_TAG_FILE="${STATE_DIR}/previous-tag"
readonly LOCK_FILE="${STATE_DIR}/deploy.lock"
readonly LOG_FILE="${LOG_DIR}/deploy.log"

usage() {
  cat <<USAGE
Usage: deploy.sh <image-tag>

Deploys motionile-api and motionile-worker images tagged <image-tag>:
renders $ENV_FILE from SSM, pulls the images, runs migrations against
DATABASE_DIRECT_URL, starts every service and waits for health checks.
On failure it restarts the previous tag and exits non-zero.
USAGE
}

write_images_env() {
  local tag="$1"
  local temporary_file
  temporary_file=$(mktemp "${IMAGES_ENV_FILE}.XXXXXX")
  {
    printf "MOTIONILE_API_IMAGE='%s:%s'\n" "$(env_value IMAGE_REPOSITORY_API)" "$tag"
    printf "MOTIONILE_WORKER_IMAGE='%s:%s'\n" "$(env_value IMAGE_REPOSITORY_WORKER)" "$tag"
  } >"$temporary_file"
  mv -f "$temporary_file" "$IMAGES_ENV_FILE"
}

registry_login() {
  local registry
  registry=$(env_value ECR_REGISTRY)
  log "logging in to $registry"
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$registry" >/dev/null
}

pull_images() {
  local tag="$1"
  log "pulling images tagged $tag"
  docker pull --quiet "$(env_value IMAGE_REPOSITORY_API):$tag" >/dev/null
  docker pull --quiet "$(env_value IMAGE_REPOSITORY_WORKER):$tag" >/dev/null
}

start_services() {
  compose up --detach --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT_SECONDS"
}

roll_back() {
  local failed_tag="$1"
  local previous_tag="$2"
  if [[ -z "$previous_tag" || "$previous_tag" == "$failed_tag" ]]; then
    log "no previous tag to roll back to; services are left as they are"
    return
  fi
  log "rolling back from $failed_tag to $previous_tag"
  write_images_env "$previous_tag"
  if pull_images "$previous_tag" && start_services; then
    log "rollback to $previous_tag succeeded"
  else
    log "rollback to $previous_tag failed; check docker compose ps and logs"
  fi
}

main() {
  if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    [[ $# -eq 1 ]] && exit 0
    exit 2
  fi
  local tag="$1"
  [[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || die "invalid image tag: $tag"

  mkdir -p "$STATE_DIR" "$LOG_DIR"
  exec > >(tee -a "$LOG_FILE") 2>&1
  exec 9>"$LOCK_FILE"
  flock --nonblock 9 || die "another deployment holds $LOCK_FILE"

  load_instance_environment
  log "deploying $tag to $MOTIONILE_ENVIRONMENT"

  "$script_dir/render-env.sh"
  registry_login

  local previous_tag=""
  [[ -f "$CURRENT_TAG_FILE" ]] && previous_tag=$(<"$CURRENT_TAG_FILE")

  if ! pull_images "$tag"; then
    die "could not pull images tagged $tag; nothing was changed"
  fi
  write_images_env "$tag"

  log "running database migrations"
  if ! compose run --rm --no-deps migrate; then
    log "migrations failed"
    roll_back "$tag" "$previous_tag"
    die "deployment of $tag failed during migrations"
  fi

  log "starting services and waiting up to ${WAIT_TIMEOUT_SECONDS}s for health checks"
  if ! start_services; then
    compose ps --all || true
    roll_back "$tag" "$previous_tag"
    die "deployment of $tag failed health checks"
  fi

  if [[ -n "$previous_tag" && "$previous_tag" != "$tag" ]]; then
    printf '%s\n' "$previous_tag" >"$PREVIOUS_TAG_FILE"
  fi
  printf '%s\n' "$tag" >"$CURRENT_TAG_FILE"
  log "deployed $tag"

  log "pruning images unused for more than 24 hours"
  docker image prune --all --force --filter "until=24h" >/dev/null || log "image pruning failed; continuing"
}

main "$@"
