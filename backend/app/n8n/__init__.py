"""QORA — n8n orchestration module.

Provides:
- schemas: Pydantic models for trigger/callback/verification payloads
- client: Async HTTP client for firing webhooks to n8n
- dependencies: FastAPI dependency for internal API key validation
- router: Internal API endpoints for n8n ↔ backend communication
- verification: Comparison logic for dual-write result agreement
"""
