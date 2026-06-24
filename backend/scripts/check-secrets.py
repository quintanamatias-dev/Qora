"""Pre-flight secrets validation script for Qora.

Validates all required environment variables before deployment.
Prints a classification table and exits with a meaningful status code.

Usage:
    python backend/scripts/check-secrets.py          # human-readable table
    python backend/scripts/check-secrets.py --json   # machine-readable JSON

Exit codes:
    0 — All REQUIRED checks pass. Safe to deploy.
    1 — One or more REQUIRED checks failed. Deploy blocked.

Environment variable overrides (for testing):
    QORA_ENV_FILE       Override the .env file path (default: <repo-root>/.env)
    QORA_CLIENTS_ROOT   Override the clients directory (default: backend/clients/)

Security:
    Secret values are NEVER included in output, logs, or the JSON report.
    Only variable names and their status (missing/placeholder/ok) are reported.

Spec reference:
    openspec/changes/phase-b-secrets-management/specs/secrets-preflight/spec.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve repo root and load .env file before validation
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent          # backend/scripts/
_BACKEND_DIR = _SCRIPT_DIR.parent                      # backend/
_REPO_ROOT = _BACKEND_DIR.parent                       # repo root

# Honour QORA_ENV_FILE override (used by tests to inject a custom .env path)
_DEFAULT_ENV_FILE = _REPO_ROOT / ".env"
_ENV_FILE = Path(os.environ.get("QORA_ENV_FILE", str(_DEFAULT_ENV_FILE)))

# Load .env file if it exists — do not override values already in os.environ
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        # python-dotenv not available — env vars must already be injected
        pass


# ---------------------------------------------------------------------------
# Known weak placeholder values
# ---------------------------------------------------------------------------

WEAK_PLACEHOLDERS: frozenset[str] = frozenset({
    "change-me-before-production",
    "your-key-here",
    "todo",
    "replace_me",
    "xxx",
    "test",
    "changeme",
})

# Dead / deprecated variable names that are no longer wired into the app.
# If any of these appear in the environment, we warn the operator.
DEAD_VARS: tuple[str, ...] = (
    "N8N_ENABLED",
    "N8N_WEBHOOK_URL",
    "N8N_WEBHOOK_SECRET",
    "N8N_INTERNAL_API_KEY",
    "N8N_TIMEOUT_SECONDS",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "BROKER_NAME",
)

# ALL_CAPS_UNDERSCORES env var name pattern (same heuristic as CRMConfig)
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")

# Required variables and their classification tier
REQUIRED_VARS: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "CRITICAL"),
    ("ELEVENLABS_API_KEY", "CRITICAL"),
    ("QORA_API_KEY", "HIGH"),
)


# ---------------------------------------------------------------------------
# Pure validation helpers
# ---------------------------------------------------------------------------


def is_weak_placeholder(value: str) -> bool:
    """Return True if value is a known weak placeholder (case-insensitive)."""
    return value.strip().lower() in WEAK_PLACEHOLDERS


def _looks_like_env_var_name(value: str) -> bool:
    """Return True if value matches the ALL_CAPS_UNDERSCORES env var name pattern."""
    return bool(_ENV_VAR_NAME_PATTERN.match(value))


def check_required_var(var_name: str) -> dict[str, str]:
    """Check a single required var. Returns a result dict (no secret values included).

    Returns:
        {"var": var_name, "status": "ok" | "missing" | "placeholder"}
    """
    value = os.environ.get(var_name)
    if value is None:
        return {"var": var_name, "status": "missing"}
    if not value.strip():
        return {"var": var_name, "status": "missing"}
    if is_weak_placeholder(value):
        return {"var": var_name, "status": "placeholder"}
    return {"var": var_name, "status": "ok"}


def _scan_crm_yaml(
    clients_root: Path,
) -> list[dict[str, str]]:
    """Scan all crm.yaml files for env var references and validate their presence.

    Returns a list of dicts: {"client": ..., "var": ..., "status": "ok|missing|placeholder"}
    Secret values are NEVER included.
    """
    import yaml  # only needed here; standard in backend venv

    checks: list[dict[str, str]] = []

    if not clients_root.exists():
        return checks

    for client_dir in sorted(clients_root.iterdir()):
        if not client_dir.is_dir():
            continue

        client_id = client_dir.name
        crm_yaml_path = client_dir / "crm.yaml"
        if not crm_yaml_path.exists():
            continue

        try:
            raw = yaml.safe_load(crm_yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue

        if not isinstance(raw, dict):
            continue

        # Skip disabled integrations
        if not raw.get("enabled", True):
            continue

        # Resolve the api_key field (supporting api_key, api_key_env, credentials_key)
        api_key_value: str | None = (
            raw.get("api_key") or raw.get("api_key_env") or raw.get("credentials_key")
        )
        if not api_key_value:
            continue

        # Only validate if the value looks like an env var name
        if not _looks_like_env_var_name(api_key_value):
            # Literal value — used as-is in dev/test; not validated
            continue

        env_var_name = api_key_value
        env_value = os.environ.get(env_var_name)

        if env_value is None or not env_value.strip():
            checks.append({"client": client_id, "var": env_var_name, "status": "missing"})
        elif is_weak_placeholder(env_value):
            checks.append({"client": client_id, "var": env_var_name, "status": "placeholder"})
        else:
            checks.append({"client": client_id, "var": env_var_name, "status": "ok"})

    return checks


def _detect_dead_vars() -> list[str]:
    """Return list of dead/deprecated env var names that are currently set."""
    return [var for var in DEAD_VARS if os.environ.get(var) is not None]


# ---------------------------------------------------------------------------
# Main validation logic
# ---------------------------------------------------------------------------


def run_checks(clients_root: Path) -> dict:
    """Run all checks and return a result dict.

    The result dict conforms to the --json schema:
    {
        "status": "ok" | "fail",
        "failures": [{"var": "...", "reason": "missing|placeholder"}],
        "warnings": [{"var": "...", "reason": "..."}],
        "dead_vars": ["N8N_ENABLED", ...],
        "crm_checks": [{"client": "...", "var": "...", "status": "ok|missing|placeholder"}]
    }

    Secret values are NEVER included in any field.
    """
    failures: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    # Check required vars
    for var_name, _tier in REQUIRED_VARS:
        result = check_required_var(var_name)
        if result["status"] != "ok":
            failures.append({"var": var_name, "reason": result["status"]})

    # CRM scan
    crm_checks = _scan_crm_yaml(clients_root)
    for check in crm_checks:
        if check["status"] != "ok":
            failures.append({"var": check["var"], "reason": check["status"]})

    # Dead var detection
    dead_vars = _detect_dead_vars()
    for var in dead_vars:
        warnings.append({
            "var": var,
            "reason": "deprecated — not wired into app code; safe to remove from .env",
        })

    status = "fail" if failures else "ok"
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "dead_vars": dead_vars,
        "crm_checks": crm_checks,
    }


# ---------------------------------------------------------------------------
# Human-readable table output
# ---------------------------------------------------------------------------

_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

_SUPPORTS_COLOR = sys.stdout.isatty()


def _color(text: str, code: str) -> str:
    if _SUPPORTS_COLOR:
        return f"{code}{text}{_ANSI_RESET}"
    return text


def _print_human_report(result: dict) -> None:
    """Print a human-readable classification table."""
    print()
    print("=" * 65)
    print("  QORA Pre-Flight Secrets Check")
    print("=" * 65)

    # Required vars status
    print("\n  REQUIRED VARS\n")
    for var_name, tier in REQUIRED_VARS:
        var_result = check_required_var(var_name)
        status = var_result["status"]
        if status == "ok":
            tag = _color("[OK]", _ANSI_GREEN)
        elif status == "missing":
            tag = _color("[MISSING]", _ANSI_RED)
        else:
            tag = _color("[PLACEHOLDER]", _ANSI_RED)
        print(f"  {tag:25s}  {tier:10s}  {var_name}")

    # CRM checks
    if result["crm_checks"]:
        print("\n  PER-CLIENT CRM CREDENTIALS\n")
        for check in result["crm_checks"]:
            status = check["status"]
            if status == "ok":
                tag = _color("[OK]", _ANSI_GREEN)
            elif status == "missing":
                tag = _color("[MISSING]", _ANSI_RED)
            else:
                tag = _color("[PLACEHOLDER]", _ANSI_RED)
            print(f"  {tag:25s}  {check['client']}  →  {check['var']}")

    # Dead vars
    if result["dead_vars"]:
        print("\n  DEPRECATED VARS (set but not wired into app code)\n")
        for var in result["dead_vars"]:
            tag = _color("[DEPRECATED]", _ANSI_YELLOW)
            print(f"  {tag:25s}  {var}")

    # Summary
    print("\n" + "=" * 65)
    if result["status"] == "ok":
        print("  " + _color("✓ All checks PASSED — safe to deploy.", _ANSI_GREEN))
    else:
        print("  " + _color("✗ Check FAILED — deploy blocked.", _ANSI_RED))
        print()
        for failure in result["failures"]:
            print(f"    • {failure['var']}: {failure['reason']}")
    print("=" * 65)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run preflight checks and return exit code (0 = ok, 1 = fail)."""
    parser = argparse.ArgumentParser(
        description="QORA pre-flight secrets validation. Exit 0 = deploy-safe; 1 = blocked.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON instead of a human table.",
    )
    args = parser.parse_args()

    # Honour QORA_CLIENTS_ROOT override (for testing with a temp directory)
    _default_clients_root = _BACKEND_DIR / "clients"
    clients_root = Path(os.environ.get("QORA_CLIENTS_ROOT", str(_default_clients_root)))

    result = run_checks(clients_root)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        _print_human_report(result)

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
