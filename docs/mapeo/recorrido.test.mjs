import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { JourneyModel, STEPS, PHASE_DURATION, GRAPH } = require('./recorrido.js');
const html = fs.readFileSync(new URL('./recorrido.html', import.meta.url), 'utf8');

test('the journey is a directed spatial circuit rather than a vertical phase stack', () => {
  assert.ok(GRAPH.nodes.length >= 10);
  assert.ok(GRAPH.edges.length >= 12);
  assert.ok(GRAPH.edges.some((edge) => edge.from === 'next-action' && edge.to === 'scheduler'));
  assert.ok(GRAPH.edges.some((edge) => edge.from === 'contact-memory' && edge.to === 'call-context'));
  assert.ok(GRAPH.edges.some((edge) => edge.from === 'call-capture' && edge.to === 'transcript'));
  assert.match(html, /<svg[^>]+id="loop-map"/);
  assert.match(html, /aria-controls="detail-drawer"/);
  assert.match(html, /id="memory-fact-1"/);
  assert.match(html, /id="dialogue-line-1"/);
  assert.match(html, /role="dialog"/);
  assert.doesNotMatch(html, /journey-stack|phase-card/);
});

test('the deterministic second call receives enriched persisted context', () => {
  const journey = new JourneyModel();
  assert.equal(journey.snapshot().memory.length, 0);
  journey.to('capture');
  assert.deepEqual(journey.snapshot().memory.map((fact) => fact.key), ['preferred_time', 'need']);
  journey.to('persist');
  assert.ok(journey.snapshot().memory.some((fact) => fact.key === 'call_summary'));
  journey.to('call-2');
  const secondCall = journey.snapshot();
  assert.equal(secondCall.step.id, 'call-2');
  assert.ok(secondCall.memory.some((fact) => fact.key === 'recalled_context'));
  assert.match(secondCall.step.detail, /contexto enriquecido/i);
  assert.deepEqual(secondCall.memory.slice(0, 3).map((fact) => fact.value), [
    'Mañana, después de las 16',
    'Revisar cobertura del hogar',
    'Quiere comparar opciones y pidió retomar mañana.',
  ]);
});

test('the loop has stable playback timing, parallel post-call branches, and safe boundaries', () => {
  assert.equal(PHASE_DURATION, 5500);
  assert.ok(STEPS.some((step) => step.id === 'analysis' && step.edges.length >= 4));
  const journey = new JourneyModel();
  assert.equal(journey.back(), false);
  for (let index = 0; index < STEPS.length + 2; index += 1) journey.forward();
  assert.equal(journey.index, STEPS.length - 1);
  assert.equal(journey.forward(), false);
  journey.reset();
  assert.deepEqual(journey.snapshot().memory, []);
});
