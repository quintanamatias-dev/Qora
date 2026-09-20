"""Tests for non-blocking CRM config loading on the asyncio event loop.

`CRMConfigLoader.load()` performs blocking filesystem work (`Path.exists`,
`Path.read_text`) and CPU-bound YAML parsing. Calling it directly from a
coroutine runs that work on the single event-loop thread, stalling the whole
process rather than one request.

These tests pin the contract:

1. An async entry point exists and runs the blocking work off the loop thread.
2. The synchronous entry point is preserved for existing sync callers.
3. Async call sites across the voice, CRM integration, leads and summarizer
   modules use the awaited, non-blocking entry point (never the bare sync one).
4. Synchronous call sites are left on the synchronous entry point.
5. Both entry points agree on results and on error behaviour.
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
    return [(attr, awaited) for attr, awaited, _ in _loader_calls_with_context(tree, aliases)]


def _loader_calls_with_context(
    tree: ast.Module, aliases: set[str]
) -> list[tuple[str, bool, bool]]:
    """Return ``(attribute_name, is_awaited, in_async_def)`` per loader call.

    ``in_async_def`` is True when the nearest enclosing function definition is
    an ``async def``. That is the property that matters: only calls running on
    the event loop thread must be awaited. A call inside a plain ``def`` helper
    must keep using the synchronous entry point.
    """
    awaited_calls: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            awaited_calls.add(id(node.value))

    parents: dict[int, ast.AST] = {}
    nodes_by_id: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
            nodes_by_id[id(child)] = child

    def _nearest_function_is_async(node: ast.AST) -> bool:
        current = parents.get(id(node))
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return isinstance(current, ast.AsyncFunctionDef)
            current = parents.get(id(current))
        return False

    results: list[tuple[str, bool, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id not in aliases:
            continue
        results.append(
            (func.attr, id(node) in awaited_calls, _nearest_function_is_async(node))
        )
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


_MODULES_WITH_CRM_LOADER_CALLS = [
    "app.voice.webhook",
    "app.voice.context",
    "app.integrations.crm_sync_service",
    "app.integrations.crm_import_service",
    "app.integrations.crm_config_router",
    "app.leads.router",
    "app.summarizer",
]


@pytest.mark.parametrize("module_name", _MODULES_WITH_CRM_LOADER_CALLS)
def test_async_modules_never_call_sync_crm_loader(module_name):
    """No ``async def`` may call the blocking ``CRMConfigLoader.load``."""
    tree = _module_source_tree(module_name)
    aliases = _crm_loader_aliases(tree)

    assert aliases, f"{module_name} does not import CRMConfigLoader — call sites moved?"

    calls = _loader_calls_with_context(tree, aliases)
    blocking = [attr for attr, _, in_async in calls if attr == "load" and in_async]

    assert not blocking, (
        f"{module_name} still calls the blocking CRMConfigLoader.load() "
        f"{len(blocking)} time(s) from async code"
    )


@pytest.mark.parametrize(
    ("module_name", "expected_async_call_sites"),
    [
        ("app.voice.webhook", 4),
        ("app.voice.context", 1),
        ("app.integrations.crm_sync_service", 1),
        ("app.integrations.crm_import_service", 1),
        ("app.integrations.crm_config_router", 3),
        ("app.leads.router", 1),
        ("app.summarizer", 1),
    ],
)
def test_async_modules_await_load_async_at_every_call_site(
    module_name, expected_async_call_sites
):
    """Every CRM config call site inside an ``async def`` is an awaited ``load_async``."""
    tree = _module_source_tree(module_name)
    aliases = _crm_loader_aliases(tree)
    async_calls = [
        (attr, awaited)
        for attr, awaited, in_async in _loader_calls_with_context(tree, aliases)
        if in_async
    ]

    assert len(async_calls) == expected_async_call_sites, (
        f"{module_name}: expected {expected_async_call_sites} async CRMConfigLoader "
        f"call sites, found {len(async_calls)}: {async_calls}"
    )
    for attr, is_awaited in async_calls:
        assert attr == "load_async", f"{module_name}: non-async call site {attr!r}"
        assert is_awaited, f"{module_name}: {attr} call site is not awaited"


def test_sync_helper_in_crm_config_router_keeps_using_sync_load():
    """``_load_config_or_none`` is a plain ``def`` and must stay on ``load()``.

    It is not on the event loop by virtue of being a coroutine, so converting
    it would require changing its signature — explicitly out of scope here.
    This test pins the remaining sync call site so it is not silently churned.
    """
    tree = _module_source_tree("app.integrations.crm_config_router")
    aliases = _crm_loader_aliases(tree)
    sync_calls = [
        attr
        for attr, _, in_async in _loader_calls_with_context(tree, aliases)
        if not in_async
    ]

    assert sync_calls == ["load"], (
        "crm_config_router should have exactly one synchronous CRMConfigLoader "
        f"call site using load(), found: {sync_calls}"
    )


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


@pytest.mark.asyncio
async def test_get_lead_by_id_loads_crm_config_off_the_loop_thread():
    """The `GET /leads/{id}` handler must not load CRM config on the loop thread.

    Behavioural, not static: the handler coroutine is driven directly and the
    thread identity is recorded inside the blocking `CRMConfigLoader.load`
    that `load_async` delegates to. Asserting on thread identity (not timing)
    makes this deterministic.
    """
    from app.integrations import crm_config
    from app.leads import router as leads_router

    call_threads: list[int] = []

    def _recording_load(client_id, **kwargs):
        call_threads.append(threading.get_ident())
        return None

    lead = MagicMock()
    lead.id = "lead-1"
    lead.client_id = "acme"

    loop_thread = threading.get_ident()

    with patch.object(
        crm_config.CRMConfigLoader, "load", staticmethod(_recording_load)
    ), patch.object(
        leads_router, "get_lead", AsyncMock(return_value=lead)
    ), patch.object(
        leads_router, "get_active_profile_facts", AsyncMock(return_value=[])
    ), patch.object(
        leads_router, "get_interest_history", AsyncMock(return_value=[])
    ), patch.object(
        leads_router.cf_service, "get_all", AsyncMock(return_value={})
    ), patch.object(
        leads_router, "_batch_next_scheduled_call_at", AsyncMock(return_value={})
    ), patch.object(
        leads_router, "_lead_to_dict", MagicMock(return_value={})
    ):
        await leads_router.get_lead_by_id("lead-1", session=AsyncMock())

    assert call_threads, "get_lead_by_id never loaded CRM config"
    assert loop_thread not in call_threads, (
        "get_lead_by_id loaded CRM config on the event loop thread "
        f"(loop={loop_thread}, calls={call_threads})"
    )
