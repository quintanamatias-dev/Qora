"""Enum types for post-call analysis classifications."""

from __future__ import annotations

from enum import Enum


class OutcomeClassification(str, Enum):
    """Semantic classification of the call outcome."""

    interested = "interested"
    not_interested = "not_interested"
    busy = "busy"
    follow_up = "follow_up"
    no_answer = "no_answer"
    hostile = "hostile"
    confused = "confused"


class EngagementQuality(str, Enum):
    """How actively the lead participated in the conversation."""

    high = "high"
    medium = "medium"
    low = "low"
    none = "none"


class Urgency(str, Enum):
    """How urgently the lead needs the product."""

    high = "high"
    medium = "medium"
    low = "low"
