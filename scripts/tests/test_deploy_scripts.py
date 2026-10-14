import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPOSITORY_ROOT / "deploy"
PUT_PARAMETERS = REPOSITORY_ROOT / "infra" / "scripts" / "put-parameters.sh"
REGISTRY = "123456789012.dkr.ecr.ap-south-1.amazonaws.com"

AWS_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$1 $2" in
  "ssm get-parameters-by-path") cat "$STUB_SSM_JSON" ;;
  "ssm put-parameter")
    for argument in "$@"; do
      case "$argument" in file://*) cp "${argument#file://}" "$(mktemp "$STUB_DIR/uploaded-XXXXXX")" ;; esac
    done
    ;;
  "ecr get-login-password") echo token ;;
esac
"""

DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
images=$(cat "$MOTIONILE_ROOT/state/images.env" 2>/dev/null || true)
case "$*" in
  *" run --rm --no-deps migrate"*)
    [[ -n "${FAIL_MIGRATE:-}" ]] && exit 1
    ;;
  *" up --detach"*)
    if [[ -n "${FAIL_UP_TAG:-}" && "$images" == *":${FAIL_UP_TAG}'"* ]]; then exit 1; fi
    ;;
  "pull"*)
    if [[ -n "${FAIL_PULL_TAG:-}" && "$*" == *":${FAIL_PULL_TAG}"* ]]; then exit 1; fi
    ;;
esac
exit 0
"""


@dataclass
class Server:
    root: Path
    stub_dir: Path
    env: dict[str, str]

    @property
    def log(self) -> list[str]:
        path = self.stub_dir / "calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def set_parameters(self, values: dict[str, str]) -> None:
        payload = {
            "Parameters": [
                {"Name": f"/motionile/staging/{name}", "Value": value, "Type": "SecureString"}
                for name, value in values.items()
            ]
        }
        (self.stub_dir / "ssm.json").write_text(json.dumps(payload), encoding="utf-8")

    def run(
        self, script: str, *arguments: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [str(self.root / "bundle" / "scripts" / script), *arguments],
            env={**self.env, **(extra_env or {})},
            capture_output=True,
            text=True,
            check=False,
        )


def required_values() -> dict[str, str]:
    lines = (DEPLOY_DIR / "parameters.csv").read_text(encoding="utf-8").splitlines()[1:]
    values = {line.split(",")[0]: "value" for line in lines if line.split(",")[2] == "yes"}
    values["IMAGE_REPOSITORY_API"] = f"{REGISTRY}/staging/motionile-api"
    values["IMAGE_REPOSITORY_WORKER"] = f"{REGISTRY}/staging/motionile-worker"
    values["ECR_REGISTRY"] = REGISTRY
    values["DATABASE_URL"] = "postgresql://app:p=ss word@db.example/motionile?sslmode=require"
    values["ENCRYPTION_KEYS"] = '{"1":"a2V5"}'
    return values


def write_stub(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def server(tmp_path: Path) -> Server:
    root = tmp_path / "srv"
    shutil.copytree(DEPLOY_DIR, root / "bundle")
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    write_stub(stub_dir / "aws", AWS_STUB)
    write_stub(stub_dir / "docker", DOCKER_STUB)
    instance_env = tmp_path / "instance-environment"
    instance_env.write_text("MOTIONILE_ENVIRONMENT=staging\nAWS_REGION=ap-south-1\n", encoding="utf-8")
    env = {
        "PATH": f"{stub_dir}:{os.environ['PATH']}",
        "MOTIONILE_ROOT": str(root),
        "INSTANCE_ENVIRONMENT_FILE": str(instance_env),
        "STUB_LOG": str(stub_dir / "calls.log"),
        "STUB_SSM_JSON": str(stub_dir / "ssm.json"),
        "STUB_DIR": str(stub_dir),
    }
    created = Server(root=root, stub_dir=stub_dir, env=env)
    created.set_parameters(required_values())
    return created


def test_render_env_writes_only_catalog_parameters_with_mode_600(server: Server) -> None:
    server.set_parameters({**required_values(), "UNLISTED": "x"})

    result = server.run("render-env.sh")

    env_file = server.root / ".env"
    content = env_file.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert "DATABASE_URL='postgresql://app:p=ss word@db.example/motionile?sslmode=require'" in content
    assert 'ENCRYPTION_KEYS=\'{"1":"a2V5"}\'' in content
    assert "UNLISTED" not in content
    assert "p=ss word" not in result.stdout + result.stderr


def test_render_env_names_missing_required_parameters_and_keeps_old_file(server: Server) -> None:
    (server.root / ".env").write_text("OLD=1\n", encoding="utf-8")
    values = required_values()
    del values["REDIS_PASSWORD"]
    del values["TURNSTILE_SECRET_KEY"]
    server.set_parameters(values)

    result = server.run("render-env.sh")

    assert result.returncode == 1
    assert "REDIS_PASSWORD" in result.stderr
    assert "TURNSTILE_SECRET_KEY" in result.stderr
    assert (server.root / ".env").read_text(encoding="utf-8") == "OLD=1\n"


@pytest.mark.parametrize("bad_value", ["line\nbreak", "it's"])
def test_render_env_rejects_values_the_env_file_cannot_hold(server: Server, bad_value: str) -> None:
    server.set_parameters({**required_values(), "SECURITY_PAGINATION_SECRET": bad_value})

    result = server.run("render-env.sh")

    assert result.returncode == 1
    assert "SECURITY_PAGINATION_SECRET" in result.stderr
    assert not (server.root / ".env").exists()


def test_deploy_migrates_starts_and_records_tags(server: Server) -> None:
    first = server.run("deploy.sh", "abc123")
    second = server.run("deploy.sh", "def456")

    state = server.root / "state"
    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert (state / "current-tag").read_text(encoding="utf-8").strip() == "def456"
    assert (state / "previous-tag").read_text(encoding="utf-8").strip() == "abc123"
    assert f"MOTIONILE_API_IMAGE='{REGISTRY}/staging/motionile-api:def456'" in (state / "images.env").read_text(
        encoding="utf-8"
    )
    calls = server.log
    migrate_index = next(index for index, call in enumerate(calls) if "run --rm --no-deps migrate" in call)
    up_index = next(index for index, call in enumerate(calls) if "up --detach --remove-orphans --wait" in call)
    assert migrate_index < up_index
    assert "deployed def456" in (server.root / "logs" / "deploy.log").read_text(encoding="utf-8")


def test_failed_health_check_rolls_back_to_the_previous_tag(server: Server) -> None:
    assert server.run("deploy.sh", "good").returncode == 0

    result = server.run("deploy.sh", "broken", extra_env={"FAIL_UP_TAG": "broken"})

    state = server.root / "state"
    assert result.returncode == 1
    assert "rolling back from broken to good" in result.stdout
    assert "rollback to good succeeded" in result.stdout
    assert (state / "current-tag").read_text(encoding="utf-8").strip() == "good"
    assert ":good'" in (state / "images.env").read_text(encoding="utf-8")


def test_failed_migration_rolls_back_and_fails(server: Server) -> None:
    assert server.run("deploy.sh", "good").returncode == 0

    result = server.run("deploy.sh", "next", extra_env={"FAIL_MIGRATE": "1"})

    assert result.returncode == 1
    assert "failed during migrations" in result.stdout
    assert (server.root / "state" / "current-tag").read_text(encoding="utf-8").strip() == "good"


def test_unpullable_images_change_nothing(server: Server) -> None:
    assert server.run("deploy.sh", "good").returncode == 0

    result = server.run("deploy.sh", "missing", extra_env={"FAIL_PULL_TAG": "missing"})

    assert result.returncode == 1
    assert ":good'" in (server.root / "state" / "images.env").read_text(encoding="utf-8")
    assert not any("missing" in call and "up --detach" in call for call in server.log)


@pytest.mark.parametrize("tag", ["", "-rf", "a b", "x" * 200, "../etc"])
def test_deploy_rejects_invalid_tags(server: Server, tag: str) -> None:
    result = server.run("deploy.sh", tag)

    assert result.returncode != 0
    assert not (server.root / "state" / "current-tag").exists()


def test_concurrent_deployments_are_refused(server: Server) -> None:
    state = server.root / "state"
    state.mkdir(parents=True)
    lock = state / "deploy.lock"
    with subprocess.Popen(["flock", str(lock), "sleep", "5"]) as holder:  # noqa: S603, S607
        try:
            subprocess.run(["sleep", "0.3"], check=True)  # noqa: S607
            result = server.run("deploy.sh", "abc123")
        finally:
            holder.terminate()

    assert result.returncode == 1
    assert "another deployment holds" in result.stdout


def test_put_parameters_accepts_only_owner_parameters_and_hides_values(server: Server, tmp_path: Path) -> None:
    values_file = tmp_path / "staging.env"
    values_file.write_text("REDIS_PASSWORD=sup3r=secret\n\nTURNSTILE_SECRET_KEY=turnstile-value\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603
        [str(PUT_PARAMETERS), "staging", str(values_file)],
        env=server.env,
        capture_output=True,
        text=True,
        check=False,
    )

    calls = "\n".join(server.log)
    uploaded = sorted(path.read_text(encoding="utf-8") for path in server.stub_dir.glob("uploaded-*"))
    assert result.returncode == 0, result.stderr
    assert "--name /motionile/staging/REDIS_PASSWORD" in calls
    assert "--type SecureString" in calls
    assert "sup3r=secret" not in calls + result.stdout + result.stderr
    assert uploaded == ["sup3r=secret", "turnstile-value"]
    assert "DATABASE_URL" in result.stdout


def test_put_parameters_rejects_infrastructure_parameters(server: Server, tmp_path: Path) -> None:
    values_file = tmp_path / "staging.env"
    values_file.write_text("STORAGE_BUCKET=override\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603
        [str(PUT_PARAMETERS), "staging", str(values_file)],
        env=server.env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "not an owner parameter" in result.stderr
    assert not server.log
