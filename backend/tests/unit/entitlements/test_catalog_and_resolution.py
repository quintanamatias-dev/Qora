"""Plan catalog and entitlement resolution (multi-tenant-readiness WU2).

Spec: openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.entitlements.catalog import DEFAULT_PLAN, FEATURES, LIMITS, PLANS
from app.entitlements.service import (
    InvalidOverridesError,
    resolve_entitlements,
    validate_overrides,
)


def _client(plan: str = "starter", overrides: dict | None = None):
    return SimpleNamespace(
        id="acme",
        plan=plan,
        entitlement_overrides=json.dumps(overrides) if overrides is not None else None,
    )


class TestCatalog:
    def test_every_plan_defines_every_feature_and_limit(self):
        for name, plan in PLANS.items():
            assert set(plan.features) == set(FEATURES), name
            assert set(plan.limits) == set(LIMITS), name

    def test_default_plan_is_unrestricted_pilot(self):
        pilot = PLANS[DEFAULT_PLAN]
        assert DEFAULT_PLAN == "pilot"
        assert all(pilot.features.values())
        assert all(v is None for v in pilot.limits.values())

    def test_starter_matches_pricing_doc(self):
        starter = PLANS["starter"]
        assert starter.limits["max_agents"] == 1
        assert starter.limits["max_monthly_minutes"] == 200
        assert starter.features["auto_dialer"] is False


class TestResolution:
    def test_plan_defaults_without_overrides(self):
        ent = resolve_entitlements(_client("pro"))
        assert ent.plan == "pro"
        assert ent.features == PLANS["pro"].features
        assert ent.limits == PLANS["pro"].limits

    def test_override_enables_feature_and_keeps_the_rest(self):
        ent = resolve_entitlements(_client("starter", {"features": {"auto_dialer": True}}))
        assert ent.features["auto_dialer"] is True
        assert ent.features["crm_integration"] is False
        assert ent.limits == PLANS["starter"].limits

    def test_override_can_remove_a_limit(self):
        ent = resolve_entitlements(_client("starter", {"limits": {"max_monthly_minutes": None}}))
        assert ent.limits["max_monthly_minutes"] is None

    def test_unknown_plan_falls_back_to_starter(self):
        ent = resolve_entitlements(_client("enterprise-legacy"))
        assert ent.plan == "starter"
        assert ent.limits == PLANS["starter"].limits

    def test_missing_plan_attribute_uses_default(self):
        ent = resolve_entitlements(SimpleNamespace(id="x", plan=None, entitlement_overrides=None))
        assert ent.plan == DEFAULT_PLAN

    def test_corrupt_overrides_are_ignored(self):
        client = _client("pro")
        client.entitlement_overrides = "{not json"
        assert resolve_entitlements(client).features == PLANS["pro"].features

    def test_has_feature_and_limit_helpers(self):
        ent = resolve_entitlements(_client("starter"))
        assert ent.has_feature("outbound_calls") is True
        assert ent.has_feature("live_monitor") is False
        assert ent.limit("max_agents") == 1


class TestValidateOverrides:
    def test_accepts_known_keys(self):
        clean = validate_overrides({"features": {"analytics": False}, "limits": {"max_agents": 2}})
        assert clean == {"features": {"analytics": False}, "limits": {"max_agents": 2}}

    def test_empty_sections_are_dropped(self):
        assert validate_overrides({"features": {}, "limits": {}}) == {}
        assert validate_overrides(None) == {}

    @pytest.mark.parametrize(
        "bad",
        [
            {"features": {"teleport": True}},
            {"limits": {"max_planets": 3}},
            {"features": {"analytics": "yes"}},
            {"limits": {"max_agents": -1}},
            {"limits": {"max_agents": 1.5}},
            {"limits": {"max_agents": True}},
            {"other": {}},
        ],
    )
    def test_rejects_invalid_overrides(self, bad):
        with pytest.raises(InvalidOverridesError):
            validate_overrides(bad)
