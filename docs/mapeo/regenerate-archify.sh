#!/usr/bin/env bash
set -euo pipefail

ARCHIFY_ROOT=${1:?Uso: bash docs/mapeo/regenerate-archify.sh /ruta/a/archify}
ARCHIFY="$ARCHIFY_ROOT/bin/archify.mjs"

if [[ ! -f "$ARCHIFY" ]]; then
  printf 'No se encontró %s\n' "$ARCHIFY" >&2
  exit 2
fi

export ARCHIFY_UPDATE_CHECK_DISABLED=1

run() {
  local type=$1 stem=$2
  node "$ARCHIFY" validate "$type" "docs/mapeo/diagrams/$stem.archify.json" --quality showcase --json
  node "$ARCHIFY" deliver "$type" "docs/mapeo/diagrams/$stem.archify.json" "docs/mapeo/diagrams/$stem.html" --quality showcase --json
}

run architecture 01-system-context
run sequence 02-voice-turn
run workflow 03-tool-execution
run dataflow 04-post-call-dataflow
run workflow 05-outbound-control-flow
run workflow 06-two-call-journey

printf 'Entregas generadas. Ejecutá visual-check por cada HTML si necesitás evidencia de navegador; revisá sus rutas y metadatos antes de compartir la salida.\n'
