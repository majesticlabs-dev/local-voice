import test from 'node:test';
import assert from 'node:assert/strict';
import { LocalTTSClient, SETUP_GUIDANCE } from '../src/api.js';

const client = new LocalTTSClient();
const originalFetch = globalThis.fetch;

test('installed voice synthesizes and streaming remains available', async () => {
  globalThis.fetch = async (url) => url.endsWith('/synthesize')
    ? new Response(new Blob(['audio']), { status: 200 })
    : Response.json({ job_id: 'job', chunks: [{ url: '/audio/job/0.mp3' }] });
  try {
    assert.equal(await (await client.synthesize({ text: 'hello', voice: 'af_bella' })).text(), 'audio');
    assert.equal((await client.stream({ text: 'long', voice: 'af_bella' })).chunks.length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('missing models give desktop guidance without a management request', async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    return Response.json({ error: 'setup_needed', voice: 'af_bella', assets: ['kokoro-model'] }, { status: 503 });
  };
  try {
    await assert.rejects(client.synthesize({ text: 'hello', voice: 'af_bella' }), { message: SETUP_GUIDANCE });
    await assert.rejects(client.stream({ text: 'long', voice: 'af_bella' }), { message: SETUP_GUIDANCE });
    assert.deepEqual(urls.map((url) => new URL(url).pathname), ['/synthesize', '/stream']);
  } finally { globalThis.fetch = originalFetch; }
});

test('chunk synthesis setup error is actionable; other errors preserve status', async () => {
  globalThis.fetch = async () => Response.json({ error: 'setup_needed' }, { status: 503 });
  try { await assert.rejects(client.fetchChunk('/audio/job/0.mp3'), { message: SETUP_GUIDANCE }); }
  finally { globalThis.fetch = originalFetch; }
  globalThis.fetch = async () => Response.json({ detail: 'bad input' }, { status: 400 });
  try { await assert.rejects(client.synthesize({ text: 'x' }), /400.*bad input/); }
  finally { globalThis.fetch = originalFetch; }
});
