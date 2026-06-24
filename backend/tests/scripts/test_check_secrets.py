"""Tests for backend/scripts/check-secrets.py pre-flight validation script.

Spec reference:
  openspec/changes/phase-b-secrets-management/specs/secrets-preflight/spec.md

Coverage:
- Exit 0 when all REQUIRED vars are present and non-placeholder
- Exit 1 when any REQUIRED var is missing
- Exit 1 when a REQUIRED var contains a known weak placeholder
- CRM scan: detects missing env var referenced by crm.yaml
- Dead var detection: N8N_*, TWILIO_*, BROKER_NAME reported in dead_vars
- --json flag: output is valid JSON conforming to the documented schema
- Secret values are NEVER included in script output
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Absolute path to the script under test
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPT = _REPO_ROOT / "backend" / "scripts" / "check-secrets.py"

# Minimum required env vars (names only — no real values)
_REQUIRED_VARS = {
    "OPENAI_API_KEY": "sk-test-openai-key",
    "ELEVENLABS_API_KEY": "sk-test-elevenlabs-key",
    "QORA_API_KEY": "qora-test-key-for-preflight",
}

# Dead vars the script MUST report as dead/deprecated
_EXPECTED_DEAD_VARS = {"N8N_ENABLED", "N8N_WEBHOOK_URL", "N8N_WEBHOOK_SECRET",
                       "N8N_INTERNAL_API_KEY", "N8N_TIMEOUT_SECONDS",
                       "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER",
                       "BROKER_NAME"}


def _run_script(
    env_overrides: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    tmp_path: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run check-secrets.py in a subprocess with a controlled environment.

    Starts from a minimal environment (no real host env leaked in) and injects
    only the vars provided by the test. Never prints or logs secret values.

    Defaults QORA_CLIENTS_ROOT to a fresh tmp subdirectory (empty — no crm.yaml
    files) so tests that don't set it explicitly don't pick up real client configs
    from the working repo (which require QUINTANA_AIRTABLE_API_KEY).
    """
    _empty_clients = tmp_path / "clients" if tmp_path else None
    if _empty_clients is not None:
        _empty_clients.mkdir(parents=True, exist_ok=True)

    # Build a clean env — start from a base that excludes the host .env secrets
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        # Prevent the script from reading the real .env file by setting a
        # non-existent .env path via env var (script must honour QORA_ENV_FILE
        # when set, or we use a tmp_path that has no .env file).
        "QORA_ENV_FILE": str(tmp_path / ".env") if tmp_path else "/dev/null",
        # Default to the empty clients dir so tests don't pick up real crm.yaml files
        "QORA_CLIENTS_ROOT": str(_empty_clients) if _empty_clients else "",
    }
    if env_overrides:
        base_env.update(env_overrides)

    cmd = [sys.executable, str(_SCRIPT)]
    if extra_args:
        cmd.extend(extra_args)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=base_env,
    )


# ---------------------------------------------------------------------------
# Helper: write a minimal crm.yaml into a temp client directory
# ---------------------------------------------------------------------------


def _write_crm_yaml(clients_dir: Path, client_id: str, content: str) -> Path:
    """Write a crm.yaml file in a temporary clients directory."""
    client_dir = clients_dir / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    crm_file = client_dir / "crm.yaml"
    crm_file.write_text(content, encoding="utf-8")
    return crm_file


# ===========================================================================
# Task 2.1 — RED tests (check-secrets.py does not exist yet)
# ===========================================================================


class TestCheckSecretsExitCodes:
    """Exit code contract: 0 = deploy-safe, 1 = blocked."""

    def test_exit_0_when_all_required_vars_present(self, tmp_path):
        """Exit 0 when OPENAI_API_KEY, ELEVENLABS_API_KEY, and QORA_API_KEY are set."""
        result = _run_script(env_overrides=_REQUIRED_VARS, tmp_path=tmp_path)
        assert result.returncode == 0, (
            f"Expected exit 0 (all required vars set) but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exit_1_when_openai_api_key_missing(self, tmp_path):
        """Exit 1 when OPENAI_API_KEY is absent."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "OPENAI_API_KEY"}
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 1, (
            f"Expected exit 1 (OPENAI_API_KEY missing) but got {result.returncode}"
        )

    def test_exit_1_when_elevenlabs_api_key_missing(self, tmp_path):
        """Exit 1 when ELEVENLABS_API_KEY is absent."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "ELEVENLABS_API_KEY"}
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 1

    def test_exit_1_when_qora_api_key_missing(self, tmp_path):
        """Exit 1 when QORA_API_KEY is absent."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "QORA_API_KEY"}
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 1

    @pytest.mark.parametrize("placeholder", [
        "change-me-before-production",
        "your-key-here",
        "TODO",
        "xxx",
        "changeme",
        "REPLACE_ME",
    ])
    def test_exit_1_when_required_var_is_placeholder(self, tmp_path, placeholder):
        """Exit 1 when a REQUIRED var contains a known weak placeholder."""
        env = dict(_REQUIRED_VARS)
        env["OPENAI_API_KEY"] = placeholder
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 1, (
            f"Expected exit 1 for placeholder '{placeholder}' but got {result.returncode}"
        )


class TestCheckSecretsOutputContent:
    """Output content: failures named; no secret values in output."""

    def test_output_names_missing_variable(self, tmp_path):
        """When OPENAI_API_KEY is missing, the output mentions 'OPENAI_API_KEY'."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "OPENAI_API_KEY"}
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert "OPENAI_API_KEY" in result.stdout or "OPENAI_API_KEY" in result.stderr

    def test_output_does_not_contain_secret_values(self, tmp_path):
        """Secret values must never appear in script output."""
        secret_val = "sk-super-secret-test-value-b8"
        env = dict(_REQUIRED_VARS)
        env["OPENAI_API_KEY"] = secret_val
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        combined_output = result.stdout + result.stderr
        assert secret_val not in combined_output, (
            "Secret value leaked into script output — this is a security violation!"
        )

    def test_success_output_indicates_deploy_safe(self, tmp_path):
        """On exit 0, output signals that secrets are OK (contains 'ok' or similar)."""
        result = _run_script(env_overrides=_REQUIRED_VARS, tmp_path=tmp_path)
        # The script must print some positive confirmation, not just be silent
        combined = (result.stdout + result.stderr).lower()
        assert any(kw in combined for kw in ("ok", "pass", "valid", "ready", "success")), (
            f"Expected deploy-safe confirmation in output but got: {combined[:200]}"
        )


class TestCheckSecretsCRMScan:
    """CRM scan: detects missing env vars referenced by crm.yaml files."""

    def test_exit_1_when_crm_yaml_references_missing_env_var(self, tmp_path):
        """Exit 1 when crm.yaml references an env var that is not set."""
        clients_dir = tmp_path / "clients"
        _write_crm_yaml(clients_dir, "test-client", textwrap.dedent("""\
            api_key: TEST_CLIENT_CRM_API_KEY
            provider: airtable
            base_id: appXXXXXXXXXXXXXX
        """))

        env = dict(_REQUIRED_VARS)
        env["QORA_CLIENTS_ROOT"] = str(clients_dir)
        # Do NOT set TEST_CLIENT_CRM_API_KEY — expect failure
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 1

    def test_exit_0_when_crm_yaml_env_var_is_set(self, tmp_path):
        """Exit 0 when crm.yaml references an env var that IS set with a real value."""
        clients_dir = tmp_path / "clients"
        _write_crm_yaml(clients_dir, "test-client", textwrap.dedent("""\
            api_key: TEST_CLIENT_CRM_API_KEY
            provider: airtable
            base_id: appXXXXXXXXXXXXXX
        """))

        env = dict(_REQUIRED_VARS)
        env["QORA_CLIENTS_ROOT"] = str(clients_dir)
        env["TEST_CLIENT_CRM_API_KEY"] = "pat-real-airtable-key-for-test"
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 0

    def test_skips_disabled_crm_integration(self, tmp_path):
        """Exit 0 when crm.yaml has enabled: false — missing key should NOT fail."""
        clients_dir = tmp_path / "clients"
        _write_crm_yaml(clients_dir, "test-client", textwrap.dedent("""\
            enabled: false
            api_key: MISSING_CRM_KEY_THAT_IS_NOT_SET
            provider: airtable
            base_id: appXXXXXXXXXXXXXX
        """))

        env = dict(_REQUIRED_VARS)
        env["QORA_CLIENTS_ROOT"] = str(clients_dir)
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 0

    def test_crm_check_output_names_client_and_var(self, tmp_path):
        """When a CRM key is missing, the output mentions both client id and var name."""
        clients_dir = tmp_path / "clients"
        _write_crm_yaml(clients_dir, "acme-corp", textwrap.dedent("""\
            api_key: ACME_AIRTABLE_SECRET_KEY
            provider: airtable
            base_id: appXXXXXXXXXXXXXX
        """))

        env = dict(_REQUIRED_VARS)
        env["QORA_CLIENTS_ROOT"] = str(clients_dir)
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        combined = result.stdout + result.stderr
        assert "acme-corp" in combined or "ACME_AIRTABLE_SECRET_KEY" in combined


class TestCheckSecretsDeadVarDetection:
    """Dead var detection: N8N_*, TWILIO_*, BROKER_NAME reported in output."""

    @pytest.mark.parametrize("dead_var", [
        "N8N_ENABLED",
        "N8N_WEBHOOK_URL",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "BROKER_NAME",
    ])
    def test_dead_var_appears_in_output_when_set(self, tmp_path, dead_var):
        """When a known dead var is set in the environment, the script reports it."""
        env = dict(_REQUIRED_VARS)
        env[dead_var] = "some-value"
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        combined = result.stdout + result.stderr
        assert dead_var in combined, (
            f"Expected dead var '{dead_var}' to appear in output but it didn't.\n"
            f"Output: {combined[:400]}"
        )

    def test_dead_var_does_not_cause_exit_1(self, tmp_path):
        """Dead vars are warnings only — must not cause exit 1 when all REQUIRED vars are set."""
        env = dict(_REQUIRED_VARS)
        env["N8N_ENABLED"] = "true"
        env["BROKER_NAME"] = "Quintana Seguros"
        result = _run_script(env_overrides=env, tmp_path=tmp_path)
        assert result.returncode == 0, (
            "Dead/deprecated vars should warn, not fail. "
            f"Got exit {result.returncode}.\nstdout: {result.stdout}"
        )


class TestCheckSecretsJsonFlag:
    """--json flag: output is valid JSON conforming to the documented schema."""

    def test_json_output_is_valid_json(self, tmp_path):
        """--json flag produces parseable JSON output."""
        result = _run_script(
            env_overrides=_REQUIRED_VARS,
            extra_args=["--json"],
            tmp_path=tmp_path,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"--json output is not valid JSON: {exc}\nOutput: {result.stdout[:500]}")
        assert isinstance(data, dict), "JSON output must be a dict"

    def test_json_schema_has_required_keys(self, tmp_path):
        """JSON output contains status, failures, warnings, dead_vars, crm_checks."""
        result = _run_script(
            env_overrides=_REQUIRED_VARS,
            extra_args=["--json"],
            tmp_path=tmp_path,
        )
        data = json.loads(result.stdout)
        for key in ("status", "failures", "warnings", "dead_vars", "crm_checks"):
            assert key in data, f"JSON output missing required key: '{key}'"

    def test_json_status_ok_when_all_required_set(self, tmp_path):
        """JSON status is 'ok' when all required vars are present."""
        result = _run_script(
            env_overrides=_REQUIRED_VARS,
            extra_args=["--json"],
            tmp_path=tmp_path,
        )
        data = json.loads(result.stdout)
        assert data["status"] == "ok", f"Expected status 'ok' but got '{data['status']}'"

    def test_json_status_fail_when_required_missing(self, tmp_path):
        """JSON status is 'fail' when a required var is missing."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "OPENAI_API_KEY"}
        result = _run_script(env_overrides=env, extra_args=["--json"], tmp_path=tmp_path)
        data = json.loads(result.stdout)
        assert data["status"] == "fail"
        assert len(data["failures"]) >= 1

    def test_json_failure_entry_has_var_and_reason(self, tmp_path):
        """Each failure entry in JSON output has 'var' and 'reason' keys."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "OPENAI_API_KEY"}
        result = _run_script(env_overrides=env, extra_args=["--json"], tmp_path=tmp_path)
        data = json.loads(result.stdout)
        assert data["failures"], "Expected at least one failure entry"
        for entry in data["failures"]:
            assert "var" in entry, f"Failure entry missing 'var': {entry}"
            assert "reason" in entry, f"Failure entry missing 'reason': {entry}"

    def test_json_failure_reason_is_missing_or_placeholder(self, tmp_path):
        """Failure reason is 'missing' or 'placeholder' — never the secret value."""
        env = {k: v for k, v in _REQUIRED_VARS.items() if k != "OPENAI_API_KEY"}
        result = _run_script(env_overrides=env, extra_args=["--json"], tmp_path=tmp_path)
        data = json.loads(result.stdout)
        for entry in data["failures"]:
            assert entry["reason"] in {"missing", "placeholder"}, (
                f"Unexpected reason value: '{entry['reason']}' — must be 'missing' or 'placeholder'"
            )

    def test_json_dead_vars_is_list(self, tmp_path):
        """JSON dead_vars field is a list."""
        env = dict(_REQUIRED_VARS)
        env["N8N_ENABLED"] = "true"
        result = _run_script(env_overrides=env, extra_args=["--json"], tmp_path=tmp_path)
        data = json.loads(result.stdout)
        assert isinstance(data["dead_vars"], list)

    def test_json_crm_checks_is_list(self, tmp_path):
        """JSON crm_checks field is a list."""
        result = _run_script(
            env_overrides=_REQUIRED_VARS,
            extra_args=["--json"],
            tmp_path=tmp_path,
        )
        data = json.loads(result.stdout)
        assert isinstance(data["crm_checks"], list)

    def test_json_secret_values_not_in_output(self, tmp_path):
        """Secret values must never appear in --json output."""
        secret_val = "sk-super-secret-test-value-json-b8"
        env = dict(_REQUIRED_VARS)
        env["OPENAI_API_KEY"] = secret_val
        result = _run_script(env_overrides=env, extra_args=["--json"], tmp_path=tmp_path)
        assert secret_val not in result.stdout, (
            "Secret value leaked into --json output — security violation!"
        )
