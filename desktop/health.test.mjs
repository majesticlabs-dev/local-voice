import assert from 'node:assert/strict';
import test from 'node:test';
import { healthBlockers } from './health.js';

const missing = (name) => ({ name, required: true, available: false, detail: `${name} missing` });

test('model setup does not report expected missing voices as startup failures', () => {
  const health = {
    status: 'setup_needed',
    dependencies: [missing('kokoro'), missing('piper'), { name: 'ffmpeg', required: true, available: true }],
  };
  assert.deepEqual(healthBlockers(health), []);
});

test('setup still reports missing MP3 encoder, and runtime failures report providers', () => {
  const dependencies = [missing('kokoro'), missing('ffmpeg')];
  assert.deepEqual(healthBlockers({ status: 'setup_needed', dependencies }), [dependencies[1]]);
  assert.deepEqual(healthBlockers({ status: 'error', dependencies }), dependencies);
});
