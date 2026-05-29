"""CRM Port — Abstract Base Class defining the write contract for CRM adapters.

Design decisions (design.md):
- CRMPort is a pure write interface: no Airtable reads during active call path (CS-7)
- Adding a new adapter requires zero changes outside app/integrations/adapters/ (CS-9)
- upsert_record is the single write operation: match by field, update or create (CS-3/CS-6)
- health_check() is included for diagnostics (optional — not used in call path)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CRMPort(ABC):
    """Abstract base class for CRM write adapters.

    All concrete adapters (Airtable, HubSpot, Salesforce, …) must implement
    this interface. The caller (crm_sync_service) only depends on CRMPort —
    never on a concrete adapter class.
    """

    @abstractmethod
    async def upsert_record(
        self,
        table_id: str,
        payload: dict[str, Any],
        match_field: str,
    ) -> str:
        """Upsert a CRM record by matching on a single field.

        Args:
            table_id: CRM table/view identifier (adapter-specific format).
            payload: Dict of CRM field names → values to write.
            match_field: The CRM field name to use for de-duplication lookup.
                         If a record with matching value exists, update it;
                         otherwise create a new record.

        Returns:
            The external record ID (adapter-specific string).

        Raises:
            NotImplementedError: If the concrete adapter does not implement this.
        """
        ...

    async def health_check(self) -> bool:
        """Optional connectivity check. Returns True if the CRM is reachable.

        Default implementation always returns True (non-blocking no-op).
        Override in adapters that support a cheap ping.
        """
        return True
