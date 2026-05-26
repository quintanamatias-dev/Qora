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
  // Phase 7 — earliest pending/in_progress scheduled call time, or null
  next_scheduled_call_at: string | null
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
  | 'no_answer'
  | 'busy'
  | 'callback_requested'
  | 'completed_positive'
  | 'completed_neutral'
  | 'completed_negative'
  | 'do_not_contact'
  | 'wrong_number'
  | 'hostile'
  | 'confused'
  | 'technical_issue'

export type OutcomeConfidence = 'low' | 'medium' | 'high'

export type Urgency = 'high' | 'medium' | 'low'

export interface CallOutcome {
  classification: OutcomeClassification
  reason: string
  confidence: OutcomeConfidence
}

export interface DetectedInterests {
  products: string[]
  specific_needs: string[]
  buying_signals: string[]
}

// ──────────────────────────────────────────────────────────────────────────────
// Problem Axis Types (qora-problem, Issue #52)
// Replaces flat IdentifiedProblem with structured PainPoint model
// ──────────────────────────────────────────────────────────────────────────────

export type PainPointCategory =
  | 'cost'
  | 'coverage'
  | 'renewal'
  | 'bad_experience'
  | 'lack_of_clarity'
  | 'new_need'
  | 'risk_exposure'
  | 'comparison'
  | 'deadline'
  | 'dissatisfaction'
  | 'other'

export type PainUrgency = 'low' | 'medium' | 'high' | 'unknown'
export type PainConfidence = 'low' | 'medium' | 'high'

export interface PainPoint {
  category: PainPointCategory
  description: string
  evidence: string
  urgency: PainUrgency
  confidence: PainConfidence
  is_primary: boolean
}

export interface ProblemAxis {
  pain_points: PainPoint[]
}

// Backward-compat alias: detail-page.tsx and other consumers use IdentifiedProblem
// Now typed as ProblemAxis — consumers should migrate to ProblemAxis over time
export type IdentifiedProblem = ProblemAxis

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
// Call Analysis — matches backend CallAnalysisResponse
// GET /api/v1/calls/{session_id}/analysis
// ──────────────────────────────────────────────────────────────────────────────

export interface CallAnalysis {
  session_id: string
  // Scalar analysis fields
  summary: string | null
  interest_level: number | null
  classification: string | null
  outcome_reason: string | null
  urgency: string | null
  primary_need: string | null
  next_action_suggested: string | null
  current_insurance: string | null
  // JSON columns — returned as parsed Python objects (list or dict)
  objections: Record<string, unknown>[] | null
  products: string[] | null
  pain_points: Record<string, unknown>[] | null
  service_issues: Record<string, unknown>[] | null
  profile_facts: Record<string, unknown>[] | null
  commitment_signals: Record<string, unknown>[] | null
  specific_needs: string[] | null
  misc_notes: Record<string, unknown> | Record<string, unknown>[] | null
  data_corrections: Record<string, unknown>[] | null
  extra_axes_data: Record<string, unknown> | null
  // Abandonment
  was_abrupt: boolean | null
  abandonment_trigger: string | null
  // Audit
  analysis_status: string
  analysis_error: string | null
  analyzed_at: string
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
  name: string
  agent_name: string
  voice_id: string
  is_active: boolean
  created_at: string
  agent_count?: number  // returned by list endpoint
}

export interface CreateClientPayload {
  client_id: string
  name: string
  agent_name: string
}

export interface UpdateClientPayload {
  name?: string
  agent_name?: string
  voice_id?: string
}

// ──────────────────────────────────────────────────────────────────────────────
// Agent
// ──────────────────────────────────────────────────────────────────────────────

export interface Agent {
  agent_id: string
  client_id: string
  slug: string
  name: string
  voice_id: string
  model: string
  system_prompt: string | null
  tools_enabled: string[]
  is_active: boolean
  is_default: boolean
  created_at: string
  // ElevenLabs binding + readiness (PR 2 — qora-agent-studio-demo)
  elevenlabs_agent_id: string | null
  knowledge_base: string | null
  temperature: number
  max_tokens: number
  /** Computed server-side: /api/v1/voice/{client_id}/custom-llm/chat/completions */
  custom_llm_url: string
  /** true when system_prompt is non-empty */
  has_prompt: boolean
  /** true when elevenlabs_agent_id is non-null */
  has_elevenlabs_agent_id: boolean
  /** true when has_prompt AND has_elevenlabs_agent_id */
  is_conversation_ready: boolean
  // Voice tuning — TTS runtime config
  tts_speed: number
  tts_stability: number
  tts_similarity_boost: number
}

export interface CreateAgentPayload {
  slug: string
  name: string
  voice_id: string
  model: string
  system_prompt?: string | null
  tools_enabled: string[]
  elevenlabs_agent_id?: string | null
  knowledge_base?: string | null
  temperature?: number
  max_tokens?: number
  // Voice tuning
  tts_speed?: number
  tts_stability?: number
  tts_similarity_boost?: number
}

export interface UpdateAgentPayload {
  name?: string
  voice_id?: string
  system_prompt?: string | null
  tools_enabled?: string[]
  elevenlabs_agent_id?: string | null
  knowledge_base?: string | null
  temperature?: number
  max_tokens?: number
  // Voice tuning
  tts_speed?: number
  tts_stability?: number
  tts_similarity_boost?: number
}

/** A single item in the agent readiness checklist */
export interface ReadinessCheck {
  label: string
  ready: boolean
}

// ──────────────────────────────────────────────────────────────────────────────
// Analytics
// ──────────────────────────────────────────────────────────────────────────────

export type AnalyticsPeriod = 'day' | 'week' | 'month' | 'custom'

export interface AnalyticsParams {
  period: AnalyticsPeriod
  agentId?: string
  startDate?: string
  endDate?: string
}

export interface AnalyticsOverviewResponse {
  total_calls: number
  outcome_distribution: Record<string, number>
  avg_call_duration_seconds: number | null
  conversion_rate: number | null
  period: string
  start_date: string
  end_date: string
  agent_id: string | null
}

export interface ServiceIssueItem {
  issue: string
  count: number
  rank: number
}

export interface AnalyticsServiceIssuesResponse {
  issues: ServiceIssueItem[]
  period: string
  start_date: string
  end_date: string
  agent_id: string | null
}

export interface InterestItem {
  interest: string
  count: number
  trend: 'up' | 'down' | 'stable'
  previous_count: number
}

export interface AnalyticsInterestsResponse {
  interests: InterestItem[]
  period: string
  start_date: string
  end_date: string
  agent_id: string | null
}

export interface AgentStatItem {
  agent_id: string
  agent_name: string | null
  total_calls: number
  outcome_distribution: Record<string, number>
  conversion_rate: number | null
}

export interface AnalyticsAgentStatsResponse {
  agents: AgentStatItem[]
  period: string
  start_date: string
  end_date: string
}
