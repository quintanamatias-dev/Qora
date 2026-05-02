"""Enum types for post-call analysis classifications."""

from __future__ import annotations

from enum import Enum


class Urgency(str, Enum):
    """How urgently the lead needs the product."""

    high = "high"
    medium = "medium"
    low = "low"
