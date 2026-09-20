"""Tests for non-blocking CRM config loading on the asyncio event loop.

`CRMConfigLoader.load()` performs blocking filesystem work (`Path.exists`,
`Path.read_text`) and CPU-bound YAML parsing. Calling it directly from a
coroutine runs that work on the single event-loop thread, stalling the whole
process rather than one request.

These tests pin the contract:

1. An async entry point exists and runs the blocking work off the loop thread.
2. The synchronous entry point is preserved for existing sync callers.
3. Async call sites in `app/voice/webhook.py` and `app/voice/context.py` use
   the awaited, non-blocking entry point (never the bare sync one).
4. Both entry points agree on results and on error behaviour.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml as _yaml_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CRM_YAML = """
provider: airtable
base_id: appTEST123
table_id: tblTEST123
api_key: pat.literal-dev-key
match_field: phone
"""


def _write_crm_yaml(root: Path, client_id: str, body: str = _VALID_CRM_YAML) -> Path:
    """Create ``root/<client_id>/crm.yaml`` and return its path."""
    client_dir = root / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    path = client_dir / "crm.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _crm_loader_aliases(tree: ast.Module) -> set[str]:
    """Return local names bound to ``CRMConfigLoader`` anywhere in *tree*.

    Handles both module-level and function-local imports, and aliased imports
    such as ``from app.integrations.crm_config import CRMConfigLoader as _X``.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.integrations.crm_config":
            for alias in node.names:
                if alias.name == "CRMConfigLoader":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _loader_calls(tree: ast.Module, aliases: set[str]) -> list[tuple[str, bool]]:
    """Return ``(attribute_name, is_awaited)`` for every loader call in *tree*."""
    awaited_calls: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            awaited_calls.add(id(node.value))

    results: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id not in aliases:
            continue
        results.append((func.attr, id(node) in awaited_calls))
    return results


def _module_source_tree(module_name: str) -> ast.Module:
    import importlib

    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


# ---------------------------------------------------------------------------
# 1. The async entry point exists and does its blocking work off the loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_async_parses_yaml_off_the_event_loop_thread(tmp_path, monkeypatch):
    """The YAML parse must NOT run on the event loop thread.

    Observable fact, not timing: the thread identity recorded inside
    ``yaml.safe_load`` differs from the thread running the coroutine.
    """
    from app.integrations import crm_config

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "async-client")

    parse_threads: list[int] = []
    real_safe_load = _yaml_module.safe_load

    def _recording_safe_load(*args, **kwargs):
        parse_threads.append(threading.get_ident())
        return real_safe_load(*args, **kwargs)

    monkeypatch.setattr(crm_config.yaml, "safe_load", _recording_safe_load)

    loop_thread = threading.get_ident()
    config = await crm_config.CRMConfigLoader.load_async(
        "async-client", clients_root=clients_root
    )

    assert config is not None
    assert parse_threads, "yaml.safe_load was never called — test is not observing the parse"
    assert loop_thread not in parse_threads, (
        "CRM config YAML was parsed on the event loop thread "
        f"(loop={loop_thread}, parse={parse_threads})"
    )


@pytest.mark.asyncio
async def test_load_async_reads_file_off_the_event_loop_thread(tmp_path, monkeypatch):
    """The filesystem read must NOT run on the event loop thread either."""
    from app.integrations import crm_config

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "read-client")

    read_threads: list[int] = []
    real_read_text = Path.read_text

    def _recording_read_text(self, *args, **kwargs):
        if self.name == "crm.yaml":
            read_threads.append(threading.get_ident())
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _recording_read_text)

    loop_thread = threading.get_ident()
    await crm_config.CRMConfigLoader.load_async("read-client", clients_root=clients_root)

    assert read_threads, "crm.yaml was never read — test is not observing the read"
    assert loop_thread not in read_threads, (
        "crm.yaml was read on the event loop thread "
        f"(loop={loop_thread}, read={read_threads})"
    )


@pytest.mark.asyncio
async def test_load_async_missing_file_returns_none(tmp_path):
    """Missing crm.yaml → None, same as the sync entry point."""
    from app.integrations.crm_config import CRMConfigLoader

    result = await CRMConfigLoader.load_async(
        "nonexistent-client", clients_root=tmp_path / "clients"
    )

    assert result is None


@pytest.mark.asyncio
async def test_load_async_propagates_validation_error(tmp_path):
    """A malformed crm.yaml raises ConfigValidationError through the thread hop."""
    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "bad-client", body="provider: airtable\n")

    with pytest.raises(ConfigValidationError):
        await CRMConfigLoader.load_async("bad-client", clients_root=clients_root)


@pytest.mark.asyncio
async def test_load_async_matches_sync_load_result(tmp_path):
    """Sync and async entry points must produce equivalent configs."""
    from app.integrations.crm_config import CRMConfigLoader

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "parity-client")

    sync_config = CRMConfigLoader.load("parity-client", clients_root=clients_root)
    async_config = await CRMConfigLoader.load_async(
        "parity-client", clients_root=clients_root
    )

    assert sync_config is not None
    assert async_config is not None
    assert async_config.model_dump() == sync_config.model_dump()


# ---------------------------------------------------------------------------
# 2. The synchronous entry point is preserved for existing sync callers
# ---------------------------------------------------------------------------


def test_sync_load_still_works_for_non_async_callers(tmp_path):
    """Existing synchronous callers must keep working with the same signature."""
    from app.integrations.crm_config import CRMConfig, CRMConfigLoader

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "sync-client")

    config = CRMConfigLoader.load("sync-client", clients_root=clients_root)

    assert isinstance(config, CRMConfig)
    assert config.base_id == "appTEST123"
    assert config.match_field == "phone"


def test_sync_load_is_callable_without_a_running_event_loop(tmp_path):
    """The sync path must not depend on an event loop being present."""
    import asyncio

    from app.integrations.crm_config import CRMConfigLoader

    clients_root = tmp_path / "clients"
    _write_crm_yaml(clients_root, "no-loop-client")

    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()

    assert CRMConfigLoader.load("no-loop-client", clients_root=clients_root) is not None


# ---------------------------------------------------------------------------
# 3. Async call sites use the awaited, non-blocking entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    ["app.voice.webhook", "app.voice.context"],
)
def test_async_modules_never_call_sync_crm_loader(module_name):
    """No async voice module may call the blocking ``CRMConfigLoader.load``."""
    tree = _module_source_tree(module_name)
    aliases = _crm_loader_aliases(tree)

    assert aliases, f"{module_name} does not import CRMConfigLoader — call sites moved?"

    calls = _loader_calls(tree, aliases)
    blocking = [attr for attr, _ in calls if attr == "load"]

    assert not blocking, (
        f"{module_name} still calls the blocking CRMConfigLoader.load() "
        f"{len(blocking)} time(s) from async code"
    )


@pytest.mark.parametrize(
    ("module_name", "expected_call_sites"),
    [("app.voice.webhook", 4), ("app.voice.context", 1)],
)
def test_async_modules_await_load_async_at_every_call_site(
    module_name, expected_call_sites
):
    """Every CRM config call site in these modules is an awaited ``load_async``."""
    tree = _module_source_tree(module_name)
    aliases = _crm_loader_aliases(tree)
    calls = _loader_calls(tree, aliases)

    assert len(calls) == expected_call_sites, (
        f"{module_name}: expected {expected_call_sites} CRMConfigLoader call sites, "
        f"found {len(calls)}: {calls}"
    )
    for attr, is_awaited in calls:
        assert attr == "load_async", f"{module_name}: non-async call site {attr!r}"
        assert is_awaited, f"{module_name}: {attr} call site is not awaited"


@pytest.mark.asyncio
async def test_build_voice_context_loads_crm_config_off_the_loop_thread():
    """`build_voice_context` must not run CRM config loading on the loop thread."""
    from app.integrations import crm_config
    from app.voice.context import build_voice_context

    call_threads: list[int] = []
    real_load = crm_config.CRMConfigLoader.load

    def _recording_load(client_id, **kwargs):
        call_threads.append(threading.get_ident())
        return real_load(client_id, **kwargs)

    agent = MagicMock()
    agent.client_id = "acme"
    agent.slug = "aria"
    agent.name = "Aria"
    agent.system_prompt = ""
    agent.knowledge_base = None
    agent.model = "gpt-4o"
    agent.temperature = 0.7
    agent.max_tokens = 300
    agent.tools_enabled = '["capture_data"]'
    agent.tool_config = None

    client = MagicMock()
    client.id = "acme"
    client.name = "Acme Seguros"
    client.agent_name = "Aria"

    loop_thread = threading.get_ident()

    with patch.object(
        crm_config.CRMConfigLoader, "load", staticmethod(_recording_load)
    ), patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        await build_voice_context(
            agent=agent,
            lead=None,
            db=AsyncMock(),
            client=client,
        )

    assert call_threads, "build_voice_context never loaded CRM config"
    assert loop_thread not in call_threads, (
        "build_voice_context loaded CRM config on the event loop thread "
        f"(loop={loop_thread}, calls={call_threads})"
    )
