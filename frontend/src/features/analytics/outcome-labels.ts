/**
 * OUTCOME_LABELS — Spanish display labels for call outcome classifications.
 *
 * Keys mirror the 11 canonical classification codes emitted by
 * backend/app/analysis/universal/outcome.py (OutcomeClassificationType).
 */

export const OUTCOME_LABELS: Record<string, string> = {
  no_answer: 'Sin respuesta',
  busy: 'Ocupado',
  callback_requested: 'Pidió que lo llamen',
  completed_positive: 'Completada · positiva',
  completed_neutral: 'Completada · neutral',
  completed_negative: 'Completada · negativa',
  do_not_contact: 'No contactar',
  wrong_number: 'Número equivocado',
  hostile: 'Hostil',
  confused: 'Confundido',
  technical_issue: 'Problema técnico',
}

export function outcomeLabel(classification: string): string {
  return OUTCOME_LABELS[classification] ?? classification
}
