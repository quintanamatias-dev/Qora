const PHASE_DURATION = 5500;
const GRAPH = Object.freeze({
  nodes: Object.freeze(['incoming', 'qora-record', 'scheduler', 'call-context', 'call-agent', 'call-dialogue', 'call-tools', 'call-capture', 'transcript', 'analysis', 'persisted-updates', 'contact-memory', 'crm-mirror', 'next-action']),
  edges: Object.freeze([
    ['incoming', 'qora-record'], ['qora-record', 'scheduler'], ['scheduler', 'call-context'], ['contact-memory', 'call-context'], ['call-context', 'call-agent'], ['call-agent', 'call-dialogue'], ['call-dialogue', 'call-tools'], ['call-tools', 'call-capture'], ['call-capture', 'transcript'], ['transcript', 'analysis'], ['analysis', 'persisted-updates'], ['persisted-updates', 'contact-memory'], ['persisted-updates', 'crm-mirror'], ['persisted-updates', 'next-action'], ['next-action', 'scheduler'],
  ].map(([from, to]) => Object.freeze({ from, to }))),
});
const STEPS = Object.freeze([
  { id: 'prepare', label: 'Entrada y agenda', phase: '01', nodes: ['incoming', 'qora-record', 'scheduler'], edges: ['edge-incoming', 'edge-record'], detail: 'Los contactos llegan por API/UI implementada; el scheduler procesa agenda aunque el marcado depende de flags.' },
  { id: 'call-1', label: 'Llamada 1', phase: '02', nodes: ['scheduler', 'call-context', 'call-agent', 'call-dialogue'], edges: ['edge-scheduler-context', 'edge-context-agent', 'edge-agent-dialogue'], detail: 'La primera llamada arma contexto, agente y diálogo dentro del contenedor CALL.' },
  { id: 'capture', label: 'Datos capturados', phase: '03', nodes: ['call-dialogue', 'call-tools', 'call-capture'], edges: ['edge-dialogue-tools', 'edge-tools-capture'], detail: 'La herramienta captura sólo campos configurados; esta captura no cambia el estado del contacto.' },
  { id: 'transcript', label: 'Transcripción', phase: '04', nodes: ['call-capture', 'transcript'], edges: ['edge-capture-transcript'], detail: 'La transcripción y el resultado pasan a post-llamada sin afirmar éxito ni conversión.' },
  { id: 'analysis', label: 'Análisis paralelo', phase: '05', nodes: ['transcript', 'analysis'], edges: ['edge-transcript-universal', 'edge-transcript-interest', 'edge-transcript-profile', 'edge-transcript-notes'], detail: 'Seis ejes universales y cuatro pipelines complementarios se procesan en paralelo; después se decide la próxima acción.' },
  { id: 'persist', label: 'Actualizaciones atómicas', phase: '06', nodes: ['analysis', 'persisted-updates', 'contact-memory', 'crm-mirror'], edges: ['edge-analysis-persist', 'edge-persist-memory', 'edge-persist-crm'], detail: 'Análisis, contacto, perfil, notas e historial se conservan en un savepoint; el espejo CRM sale después.' },
  { id: 'schedule', label: 'Agenda del ejemplo', phase: '07', nodes: ['persisted-updates', 'next-action', 'scheduler'], edges: ['edge-persist-next', 'edge-next-scheduler'], detail: 'Con guardas elegibles, esta simulación elige explícitamente mañana 16:30 y vuelve al scheduler.' },
  { id: 'call-2', label: 'Llamada 2 · mañana', phase: '08', nodes: ['scheduler', 'contact-memory', 'call-context', 'call-agent', 'call-dialogue'], edges: ['edge-memory-context', 'edge-context-agent', 'edge-agent-dialogue'], detail: 'La segunda llamada recibe contexto enriquecido: horario, necesidad, resumen, perfil y notas de la primera.' },
  { id: 'follow-up', label: 'Próxima acción informada', phase: '09', nodes: ['call-dialogue', 'call-tools', 'call-capture', 'transcript'], edges: ['edge-dialogue-tools', 'edge-tools-capture', 'edge-capture-transcript'], detail: 'El circuito deja una próxima acción informada; no inventa una conversión ni un cierre automático.' },
]);
const FACTS = Object.freeze([
  { at: 2, key: 'preferred_time', label: 'Horario preferido', value: 'Mañana, después de las 16', source: 'Captura configurada · llamada 1' },
  { at: 2, key: 'need', label: 'Necesidad declarada', value: 'Revisar cobertura del hogar', source: 'Captura configurada · llamada 1' },
  { at: 3, key: 'call_summary', label: 'Resumen', value: 'Quiere comparar opciones y pidió retomar mañana.', source: 'Transcripción · llamada 1' },
  { at: 4, key: 'analysis', label: 'Análisis', value: 'Interés, perfil, notas y correcciones evaluados.', source: 'Post-llamada paralelo' },
  { at: 5, key: 'persisted', label: 'Memoria persistida', value: 'Contacto + llamada + análisis guardados juntos.', source: 'Savepoint simulado' },
  { at: 7, key: 'recalled_context', label: 'Contexto recuperado', value: 'Horario, necesidad, resumen y notas.', source: 'Usado en llamada 2' },
]);
class JourneyModel {
  constructor() { this.index = 0; }
  forward() { if (this.index >= STEPS.length - 1) return false; this.index += 1; return true; }
  back() { if (!this.index) return false; this.index -= 1; return true; }
  to(id) { const index = STEPS.findIndex((step) => step.id === id); if (index < 0) return false; this.index = index; return true; }
  reset() { this.index = 0; return this.snapshot(); }
  snapshot() { return { index: this.index, step: STEPS[this.index], memory: FACTS.filter((fact) => fact.at <= this.index) }; }
}
const $ = (selector) => document.querySelector(selector);
function init() {
  const model = new JourneyModel(); const speed = $('#speed'); const reduced = matchMedia('(prefers-reduced-motion: reduce)'); const packets = [...document.querySelectorAll('.packet')];
  const controls = { status: $('#journey-status'), explanation: $('#step-explanation'), counter: $('#phase-counter'), play: $('#play'), pause: $('#pause'), forward: $('#forward'), back: $('#back'), reset: $('#reset') };
  let frame = null; let playing = false; let elapsed = 0; let startedAt = null; let lastDrawerNode = null;
  const duration = () => PHASE_DURATION / Number(speed.value);
  function activePaths() { return model.snapshot().step.edges.map((id) => $(`#${id}`)).filter(Boolean); }
  function placePacket(packet, path, progress) { const length = path.getTotalLength(); const point = path.getPointAtLength(length * progress); packet.setAttribute('cx', point.x); packet.setAttribute('cy', point.y); packet.dataset.path = path.id; packet.dataset.x = point.x.toFixed(2); packet.dataset.y = point.y.toFixed(2); }
  function renderPackets(progress = Math.min(1, elapsed / duration())) { const paths = activePaths(); packets.forEach((packet, index) => { const path = paths[index]; packet.classList.toggle('is-visible', Boolean(path)); if (path) placePacket(packet, path, reduced.matches ? 0.42 : Math.min(.97, progress)); }); }
  function brainLine(fact, recalled) { return `${recalled ? 'Recuperado' : fact.at <= 2 ? 'Captura' : 'Post-llamada'} · ${fact.value}`; }
  function renderFacts(snap) {
    const brain = [$('#memory-fact-1'), $('#memory-fact-2'), $('#memory-fact-3')];
    const visible = snap.memory.slice(0, 3);
    brain.forEach((line, index) => { line.textContent = visible[index] ? brainLine(visible[index], snap.step.id === 'call-2') : ''; });
    if (!visible.length) brain[0].textContent = 'Aún no hay hechos simulados';
  }
  function renderConversation(snap) {
    const secondCall = snap.step.id === 'call-2';
    $('#call-number').textContent = secondCall ? '2' : '1';
    $('#context-line').textContent = secondCall ? 'horario + hogar' : 'perfil inicial';
    $('#dialogue-line-1').textContent = secondCall ? 'Agente: «¿Revisamos hogar?»' : 'Contacto: «Mañana >16»';
    $('#dialogue-line-2').textContent = secondCall ? '«>16; comparar y retomar»' : 'Agente: «Revisamos hogar»';
  }
  function render() {
    const snap = model.snapshot(); const { step } = snap;
    controls.counter.textContent = `Fase ${step.phase} / ${String(STEPS.length).padStart(2, '0')}`; controls.status.textContent = step.label; controls.explanation.textContent = step.detail;
    document.querySelectorAll('.map-node').forEach((node) => node.classList.toggle('is-active', step.nodes.includes(node.id)));
    document.querySelectorAll('.edges path').forEach((path) => path.dataset.active = String(step.edges.includes(path.id)));
    renderFacts(snap); renderConversation(snap);
    controls.back.disabled = model.index === 0; controls.forward.disabled = model.index === STEPS.length - 1; controls.play.disabled = model.index === STEPS.length - 1; controls.pause.disabled = !playing;
    document.documentElement.dataset.reducedMotion = String(reduced.matches); renderPackets();
  }
  function stop() { if (frame !== null) cancelAnimationFrame(frame); if (playing && startedAt !== null) elapsed += performance.now() - startedAt; frame = null; playing = false; startedAt = null; render(); }
  function tick(now) { if (!playing) return; const progress = Math.min(1, (elapsed + now - startedAt) / duration()); renderPackets(progress); if (progress < 1) { frame = requestAnimationFrame(tick); return; } elapsed = 0; startedAt = now; if (!model.forward() || model.index === STEPS.length - 1) { playing = false; startedAt = null; frame = null; render(); return; } render(); frame = requestAnimationFrame(tick); }
  function play() { if (playing || model.index === STEPS.length - 1) return; playing = true; startedAt = performance.now(); render(); frame = requestAnimationFrame(tick); }
  function step(direction) { stop(); if (direction === 'next' ? model.forward() : model.back()) { elapsed = 0; render(); } }
  function reset() { stop(); elapsed = 0; model.reset(); render(); }
  function renderDrawerFacts(node) {
    const snap = model.snapshot(); const list = $('#drawer-facts'); list.replaceChildren();
    if (node.id !== 'contact-memory' && !(node.id === 'call-context' && snap.step.id === 'call-2')) return;
    snap.memory.forEach((fact) => { const item = document.createElement('li'); const value = document.createElement('span'); const source = document.createElement('small'); value.textContent = `${fact.label}: ${fact.value}`; source.textContent = snap.step.id === 'call-2' ? `Recuperado · ${fact.source}` : fact.source; item.append(value, source); list.append(item); });
    if (!snap.memory.length) { const item = document.createElement('li'); item.textContent = 'Aún no hay hechos ficticios en esta escena.'; list.append(item); }
  }
  function openDrawer(node) { lastDrawerNode = node; $('#drawer-title').textContent = node.dataset.title; $('#drawer-body').textContent = node.dataset.detail; renderDrawerFacts(node); $('#detail-drawer').hidden = false; $('#drawer-close').focus(); }
  function closeDrawer() { $('#detail-drawer').hidden = true; if (lastDrawerNode) lastDrawerNode.focus(); }
  function handleDrawerKeys(event) { const drawer = $('#detail-drawer'); if (drawer.hidden) return; if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); } else if (event.key === 'Tab') { event.preventDefault(); $('#drawer-close').focus(); } }
  controls.play.addEventListener('click', play); controls.pause.addEventListener('click', stop); controls.forward.addEventListener('click', () => step('next')); controls.back.addEventListener('click', () => step('back')); controls.reset.addEventListener('click', reset);
  speed.addEventListener('change', () => { if (playing) { const oldDuration = PHASE_DURATION / Number(speed.dataset.previous || 1); const ratio = elapsed / oldDuration; elapsed = ratio * duration(); startedAt = performance.now(); } speed.dataset.previous = speed.value; render(); }); speed.dataset.previous = speed.value;
  document.querySelectorAll('[data-node]').forEach((node) => { node.addEventListener('click', () => openDrawer(node)); node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDrawer(node); } }); }); $('#drawer-close').addEventListener('click', closeDrawer);
  reduced.addEventListener('change', render); document.addEventListener('keydown', handleDrawerKeys); document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); }); render();
  window.__journeyDebug = { snapshot: () => ({ ...model.snapshot(), playing, elapsed, duration: duration(), activeEdges: activePaths().map((path) => path.id), packets: packets.map((packet) => ({ visible: packet.classList.contains('is-visible'), path: packet.dataset.path, x: packet.dataset.x, y: packet.dataset.y })) }), forward: () => step('next'), back: () => step('back'), reset, play, pause: stop, to: (id) => { stop(); model.to(id); elapsed = 0; render(); }, closeDrawer };
}
if (typeof document !== 'undefined') init();
if (typeof module !== 'undefined' && module.exports) module.exports = { JourneyModel, STEPS, PHASE_DURATION, GRAPH };
