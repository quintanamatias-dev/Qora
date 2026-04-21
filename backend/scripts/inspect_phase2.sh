#!/bin/bash
# Quick DB inspection helper for Phase 2 testing
# Usage: bash scripts/inspect_phase2.sh [lead_id]

DB="${DB:-./qora.db}"
LEAD_ID="${1:-lead-quintana-001}"

echo "=== Last 3 Call Sessions ==="
sqlite3 -header -column "$DB" "
SELECT
  substr(id, 1, 8) as session_id,
  substr(lead_id, -6) as lead,
  status,
  closed_reason,
  total_user_turns as u,
  total_agent_turns as a,
  substr(summary, 1, 60) as summary_preview,
  datetime(started_at, 'localtime') as started
FROM call_sessions
ORDER BY started_at DESC
LIMIT 3;"

echo ""
echo "=== Lead '$LEAD_ID' state ==="
sqlite3 -header -column "$DB" "
SELECT
  name,
  call_count,
  do_not_call,
  interest_level,
  substr(summary_last_call, 1, 80) as last_summary,
  extracted_facts
FROM leads WHERE id='$LEAD_ID';"

echo ""
echo "=== Transcript turns for latest session ==="
sqlite3 -header -column "$DB" "
SELECT
  datetime(timestamp, 'localtime') as ts,
  role,
  substr(content, 1, 70) as content_preview
FROM transcript_turns
WHERE session_id = (SELECT id FROM call_sessions ORDER BY started_at DESC LIMIT 1)
ORDER BY timestamp;"

echo ""
echo "=== Phase 2 columns present? ==="
sqlite3 "$DB" "PRAGMA table_info(call_sessions);" | grep -E "summary|closed_reason|extracted_facts" | awk -F'|' '{print "  ✓ call_sessions."$2}'
sqlite3 "$DB" "PRAGMA table_info(leads);" | grep -E "do_not_call|extracted_facts|summary_last" | awk -F'|' '{print "  ✓ leads."$2}'
