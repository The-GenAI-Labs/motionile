#!/usr/bin/env bash

export MOTIONILE_ROOT="${MOTIONILE_ROOT:-/srv/motionile}"
export BUNDLE_DIR="${MOTIONILE_ROOT}/bundle"
export STATE_DIR="${MOTIONILE_ROOT}/state"
export LOG_DIR="${MOTIONILE_ROOT}/logs"
export ENV_FILE="${MOTIONILE_ROOT}/.env"
export IMAGES_ENV_FILE="${STATE_DIR}/images.env"
export PARAMETER_CATALOG="${BUNDLE_DIR}/parameters.csv"
export INSTANCE_ENVIRONMENT_FILE="${INSTANCE_ENVIRONMENT_FILE:-/etc/motionile/environment}"

log() {
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${LOG_SCOPE:-motionile}" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

load_instance_environment() {
  [[ -r "$INSTANCE_ENVIRONMENT_FILE" ]] || die "missing $INSTANCE_ENVIRONMENT_FILE; was the instance bootstrapped by cloud-init?"
  local name value
  while IFS='=' read -r name value; do
    case "$name" in
      MOTIONILE_ENVIRONMENT | AWS_REGION | AWS_DEFAULT_REGION) export "$name=$value" ;;
      *) ;;
    esac
  done <"$INSTANCE_ENVIRONMENT_FILE"
  [[ -n "${MOTIONILE_ENVIRONMENT:-}" ]] || die "MOTIONILE_ENVIRONMENT is not set in $INSTANCE_ENVIRONMENT_FILE"
  [[ -n "${AWS_REGION:-}" ]] || die "AWS_REGION is not set in $INSTANCE_ENVIRONMENT_FILE"
}

env_value() {
  local name="$1"
  local line
  line=$(grep -E "^${name}=" "$ENV_FILE" | tail -n 1) || die "$name is missing from $ENV_FILE"
  line="${line#*=}"
  line="${line#\'}"
  printf '%s' "${line%\'}"
}

compose() {
  local env_files=(--env-file "$ENV_FILE")
  if [[ -f "$IMAGES_ENV_FILE" ]]; then
    env_files+=(--env-file "$IMAGES_ENV_FILE")
  fi
  docker compose \
    --project-directory "$BUNDLE_DIR" \
    "${env_files[@]}" \
    -f "$BUNDLE_DIR/compose.yml" \
    -f "$BUNDLE_DIR/compose.prod.yml" \
    "$@"
}
