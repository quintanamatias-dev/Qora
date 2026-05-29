"""CRM adapters sub-package.

Each adapter lives in its own per-provider package implementing CRMPort.
Adding a new adapter requires only adding a new package here and registering
it in make_adapter() (CS-9).

Available adapters:
- airtable: AirtableAdapter (pyairtable-based, write-only upsert)
"""

from app.integrations.adapters.airtable import make_adapter

__all__ = ["make_adapter"]
