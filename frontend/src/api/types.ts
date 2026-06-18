/**
 * API Types — TypeScript interfaces mirroring backend Pydantic response schemas
 *
 * Backend source: backend/app/schemas/
 * Keep in sync with backend models. If API grows past 30 endpoints, switch to codegen.
 */

// ──────────────────────────────────────────────────────────────────────────────
// Lead
// ──────────────────────────────────────────────────────────────────────────────

export type LeadStatus = 'new' | 'called' | 'quoted' | 'interested' | 'not_interested' | 'follow_up'

// Phase A: Quote field with fill status (from CRM config metadata)
//
// Quote-readiness source of truth is the backend's quote_ready_fields (crm.yaml),
// surfaced per-field as in_quote_ready_fields. The legacy `required` flag describes
// capture_data write validation and can diverge from readiness — never use it to
// decide what counts toward quoting in the UI.
export interface QuoteField {
  field_key: string
  label: string
  field_type: string
  required: boolean
  // True when this field is part of crm.yaml quote_ready_fields (readiness set).
  in_quote_ready_fields: boolean
  // "quote_ready" → counts toward quoting; "crm_provided" → additional known context.
  source: 'quote_ready' | 'crm_provided'
  filled: boolean
  current_value: string | null
}

export interface InterestHistoryEntry {
  interest_level: number
  recorded_at: string | null
}

export interface Lead {
  id: string
  client_id: string
  name: string
  phone: string
  // Phase A: email now included in detail response (null when not stored)
  email?: string | null
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
  // WU-6: dynamic custom fields from lead_custom_fields table
  custom_fields?: Record<string, string>
  // Phase A: external CRM linkage (optional — not present on list responses)
  external_crm_id?: string | null
  external_lead_id?: number | null
  // Phase A: annotated quote fields with fill status
  quote_fields?: QuoteField[]
  // Issue #36: accumulated profile facts by namespace, interest history
  profile_facts?: Record<string, string[]>
  interest_history?: InterestHistoryEntry[]
}

// ──────────────────────────────────────────────────────────────────────────────
// Context Preview — Phase A
// GET /api/v1/leads/{lead_id}/context-preview
// ──────────────────────────────────────────────────────────────────────────────

export interface LeadContextPreview {
  lead_id: string
  system_prompt_present: boolean
  lead_profile: string
  call_history: string
  misc_notes: string
  skills_index: string | null
  tools: string[] | null
  // Operator-relevant runtime model config — null when context assembly failed
  model: string | null
  temperature: number | null
  max_tokens: number | null
  is_returning_caller: boolean
  call_number: number
  error: string | null
}

export interface CreateLeadPayload {
  name: string
  phone: string
  notes?: string | null
  // WU-6: optional custom fields written to lead_custom_fields table
  custom_fields?: Record<string, string>
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension Rollups — cubora-accumulated-dimension-rankings
// GET /api/v1/leads/{lead_id}/dimension-rollups
// ──────────────────────────────────────────────────────────────────────────────

export interface DetectedInterestRollup {
  interest: string
  count: number
  category: 'product' | 'need'
}

export interface ServiceIssueRollup {
  issue: string
  count: number
  strength: 'high' | 'medium' | 'low'
}

export interface CategoryRollup {
  category: string
  count: number
}

export interface DimensionRollups {
  detected_interests: DetectedInterestRollup[]
  service_issues: ServiceIssueRollup[]
  objections: CategoryRollup[]
  pain_points: CategoryRollup[]
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
  // BI-friendly denormalized columns (PR 2 — post-call-analysis-bi-friendly)
  // Populated from JSON arrays at write time; indexed for GROUP BY queries.
  primary_objection_category: string | null
  primary_pain_category: string | null
  objections_count: number | null
  pain_points_count: number | null
  service_issues_count: number | null
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
// Integration Config
// ──────────────────────────────────────────────────────────────────────────────

/**
 * IntegrationConfig — represents a configured CRM integration for a client.
 * Returned by GET /api/v1/clients/{client_id}/integrations.
 *
 * SECURITY: api_key_env is an env var name or masked credential label, never the actual secret.
 */
export interface IntegrationConfig {
  provider: string
  base_id: string
  table_id: string
  api_key_env: string   // env var name or masked credential label — never the secret value
  match_field: string
  field_count: number
  connected: boolean
  status_mapping?: Record<string, string>
  import_status_mapping?: Record<string, string>
  field_mappings?: CRMFieldMapping[]
  field_definitions?: CRMFieldDefinition[]
  quote_ready_fields?: string[]
}

export interface CRMFieldMapping {
  source: string
  target: string
  type: string
  required?: boolean
}

export interface CRMFieldDefinition {
  field_key: string
  field_type: string
  label: string
  required?: boolean
}

/**
 * UpdateIntegrationPayload — partial update for integration config.
 * PUT /api/v1/clients/{client_id}/integrations/{provider}
 */
export interface UpdateIntegrationPayload {
  base_id?: string
  table_id?: string
  api_key_env?: string
  match_field?: string
  status_mapping?: Record<string, string>
  import_status_mapping?: Record<string, string>
}

export interface AirtableField {
  id?: string | null
  name: string
  type?: string | null
}

export interface AirtableFieldsResponse {
  fields: AirtableField[]
}

export interface SaveMappingsPayload {
  field_mappings: CRMFieldMapping[]
  field_definitions: CRMFieldDefinition[]
  quote_ready_fields: string[]
}

/**
 * IntegrationTestResult — result of POST /api/v1/clients/{client_id}/integrations/{provider}/test
 */
export interface IntegrationTestResult {
  success: boolean
  message: string
  record_count?: number
}

/**
 * AvailableIntegration — a supported provider with its current connection status.
 * GET /api/v1/clients/{client_id}/integrations/available
 */
export interface AvailableIntegration {
  provider: string
  name: string
  description: string
  is_connected: boolean
  icon: string
}

/**
 * ConnectIntegrationPayload — payload to create a new integration.
 * POST /api/v1/clients/{client_id}/integrations/{provider}/connect
 * SECURITY: api_key_env is the env var NAME only, never the actual secret.
 */
export interface ConnectIntegrationPayload {
  base_id: string
  table_id: string
  api_key_env: string
}

/**
 * DisconnectResult — result of DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect
 */
export interface DisconnectResult {
  success: boolean
  message: string
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
