import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('./local-voice.panel/Status.js', import.meta.url), 'utf8');
const status = runInNewContext(`${source}\n({ controller, service, label, primaryAction, appLabel, active, icon, powerAction, powerLabel })`);
const fakeController = state => status.controller(JSON.stringify({ state, error: null }), 0);

assert.equal(status.label(fakeController('playing'), 'ready'), 'Playing');
assert.equal(status.label(fakeController('reading'), 'ready'), 'Reading');
assert.equal(status.label(fakeController('idle'), 'ready'), 'Ready');
assert.equal(status.label(fakeController('offline'), 'ready'), 'Ready');
assert.equal(status.label(fakeController('idle'), 'setup_needed'), 'Setup needed');
assert.equal(status.label(fakeController('setup_needed'), 'ready'), 'Setup needed');
assert.equal(status.label(fakeController('playing'), 'down'), 'Service down');
assert.equal(status.label(fakeController('error'), 'ready'), 'Playback error');
assert.equal(status.service('{"status":"setup_needed"}', 0), 'setup_needed');
assert.equal(status.service('{"status":"ok"}', 0), 'ready');
assert.equal(status.service('{"status":"ok"}', 7), 'down');
assert.equal(status.service('not json', 0), 'down');
assert.equal(status.controller('not json', 0).state, 'offline');
assert.equal(status.controller('{"state":"unrecognized"}', 0).state, 'offline');
for (const state of ['reading', 'synthesizing', 'playing']) {
  assert.equal(status.primaryAction(fakeController(state)), 'stop');
  assert.equal(status.active(fakeController(state), 'ready'), true);
}
for (const state of ['idle', 'setup_needed', 'error', 'offline']) {
  assert.equal(status.primaryAction(fakeController(state)), 'read');
  assert.equal(status.active(fakeController(state), 'ready'), false);
}
assert.equal(status.active(fakeController('playing'), 'down'), false);
assert.equal(status.appLabel(fakeController('idle'), 'setup_needed'), 'Open Local Voice (set up models)');
assert.equal(status.appLabel(fakeController('idle'), 'ready'), 'Open Local Voice');
assert.notEqual(status.icon(fakeController('idle'), 'ready'), status.icon(fakeController('idle'), 'down'));
assert.notEqual(status.icon(fakeController('playing'), 'ready'), status.icon(fakeController('reading'), 'ready'));
assert.notEqual(status.icon(fakeController('idle'), 'setup_needed'), status.icon(fakeController('idle'), 'ready'));
assert.notEqual(status.icon(fakeController('error'), 'ready'), status.icon(fakeController('idle'), 'ready'));
assert.equal(status.controller('{"state":"off"}', 0).state, 'off');
assert.equal(status.label(fakeController('off'), 'down'), 'Off');
assert.equal(status.primaryAction(fakeController('off'), 'down'), 'start');
assert.equal(status.powerAction(fakeController('off'), 'down'), 'start');
assert.equal(status.powerLabel(fakeController('off'), 'down'), 'Start Local Voice');
assert.equal(status.primaryAction(fakeController('off'), 'ready'), 'read');
assert.equal(status.powerAction(fakeController('off'), 'ready'), 'quit');
assert.equal(status.powerAction(fakeController('idle'), 'ready'), 'quit');
assert.equal(status.powerLabel(fakeController('idle'), 'ready'), 'Quit Local Voice');
assert.notEqual(status.icon(fakeController('off'), 'down'), status.icon(fakeController('idle'), 'down'));
console.log('Omarchy panel status tests passed');
