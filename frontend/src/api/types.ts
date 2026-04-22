/**
 * API Types — TypeScript interfaces mirroring backend Pydantic response schemas
 *
 * Backend source: backend/app/schemas/
 * Keep in sync with backend models. If API grows past 30 endpoints, switch to codegen.
 */

// ──────────────────────────────────────────────────────────────────────────────
// Lead
// ──────────────────────────────────────────────────────────────────────────────

export type LeadStatus = 'new' | 'called' | 'interested' | 'not_interested' | 'follow_up'

export interface Lead {
  id: string
  client_id: string
  name: string
  phone: string
  car_make: string | null
  car_model: string | null
  car_year: number | null
  current_insurance: string | null
  status: LeadStatus
  notes: string | null
  call_count: number
  last_called_at: string | null
  created_at: string | null
  updated_at: string | null
  // Phase 2 CRM fields
  summary_last_call: string | null
  objections_heard: string[] | null
  interest_level: number | null
  extracted_facts: Record<string, unknown> | null
  do_not_call: boolean
  next_action: string | null
  next_action_at: string | null
}

export interface CreateLeadPayload {
  name: string
  phone: string
  car_make?: string | null
  car_model?: string | null
  car_year?: number | null
  current_insurance?: string | null
  notes?: string | null
}

// ──────────────────────────────────────────────────────────────────────────────
// Call Sessions
// ──────────────────────────────────────────────────────────────────────────────

export type CallStatus = 'initiated' | 'in_progress' | 'completed' | 'failed' | 'abandoned'

// ──────────────────────────────────────────────────────────────────────────────
// Post-Call Analysis Types (Phase 5, Issue #7)
// ──────────────────────────────────────────────────────────────────────────────

export type OutcomeClassification =
  | 'interested'
  | 'not_interested'
  | 'busy'
  | 'follow_up'
  | 'no_answer'
  | 'hostile'
  | 'confused'

export type EngagementQuality = 'high' | 'medium' | 'low' | 'none'

export type Urgency = 'high' | 'medium' | 'low'

export interface CallOutcome {
  classification: OutcomeClassification
  reason: string
  engagement_quality: EngagementQuality
}

export interface DetectedInterests {
  products: string[]
  specific_needs: string[]
  buying_signals: string[]
}

export interface IdentifiedProblem {
  primary_need: string
  pain_points: string[]
  urgency: Urgency
}

export interface CallSession {
  id: string
  client_id: string
  lead_id: string
  status: CallStatus
  started_at: string | null
  ended_at: string | null
  duration_seconds: number | null
  summary: string | null
  // Phase 2 fields
  outcome: string | null
  closed_reason: string | null
  billable_minutes: number | null
  total_user_turns: number | null
  total_agent_turns: number | null
  extracted_facts: Record<string, unknown> | null
}

// ──────────────────────────────────────────────────────────────────────────────
// Transcript
// ──────────────────────────────────────────────────────────────────────────────

export interface TranscriptTurn {
  id: string
  role: string
  content: string
  timestamp: string
  filler_detected: boolean
}

export interface SessionTranscript {
  session_id: string
  turn_count: number
  turns: TranscriptTurn[]
}

// ──────────────────────────────────────────────────────────────────────────────
// Metrics — matches backend CallMetricsResponse
// ──────────────────────────────────────────────────────────────────────────────

export interface MetricsPeriod {
  date_from: string | null
  date_to: string | null
}

export interface CallMetricsResponse {
  total_calls: number
  completed_calls: number
  abandoned_calls: number
  total_duration_seconds: number
  average_duration_seconds: number
  total_billable_minutes: number
  period: MetricsPeriod
}

// ──────────────────────────────────────────────────────────────────────────────
// Client
// ──────────────────────────────────────────────────────────────────────────────

export interface Client {
  client_id: string
  broker_name: string
  agent_name: string
  voice_id: string
  is_active: boolean
  created_at: string
}
