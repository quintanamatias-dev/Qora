/**
 * CRM import API call — POST /api/v1/clients/{client_id}/crm/import
 *
 * Not part of src/api/* (that surface is off-limits for this feature) but
 * uses the shared apiFetch client so error handling stays consistent.
 * Mirrors backend/app/integrations/crm_router.py ImportResultResponse.
 */

import { apiFetch } from '@/api/client'

export interface CrmImportResult {
  created: number
  updated: number
  skipped: number
  errors: string[]
}

export async function triggerCrmImport(clientId: string): Promise<CrmImportResult> {
  return apiFetch<CrmImportResult>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/crm/import`,
    { method: 'POST' }
  )
}
