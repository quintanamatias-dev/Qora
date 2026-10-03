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


# client-integrations-secrets Phase 5: app.integrations.crm_config_router and
# app.leads.router — the two call sites Phase 4 explicitly deferred — are now
# cut over to IntegrationStore (an awaited DB read, not a blocking filesystem
# read) and no longer import CRMConfigLoader at all. No module under
# backend/app/ calls CRMConfigLoader anymore; that invariant is covered by
# tests/unit/test_crm_config_loader_removed.py. Off-loop-thread coverage for
# the new read path lives in tests/unit/voice/test_context.py and
# tests/unit/integrations/test_integration_store.py.
