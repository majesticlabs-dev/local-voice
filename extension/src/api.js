export class LocalTTSClient {
  constructor(baseUrl = 'http://127.0.0.1:5517') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  async health() {
    const res = await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
    return res.json();
  }

  async voices() {
    const res = await fetch(`${this.baseUrl}/voices`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error(`Voices request failed: ${res.status}`);
    return res.json();
  }

  async synthesize({ text, voice, rate, format, lang, sessionId, normalizeAudio }) {
    const res = await fetch(`${this.baseUrl}/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice,
        rate,
        format,
        lang: lang || 'en',
        session_id: sessionId,
        normalize_audio: normalizeAudio ?? true,
      }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Synthesis failed (${res.status}): ${body}`);
    }
    return res.blob();
  }

  async stream({ text, voice, rate, format, chunking, sessionId }) {
    const res = await fetch(`${this.baseUrl}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice,
        rate,
        format,
        chunking: chunking || { strategy: 'sentence', target_chars: 500, max_chars: 1000 },
        session_id: sessionId,
      }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Stream failed (${res.status}): ${body}`);
    }
    return res.json();
  }

  async fetchChunk(url) {
    const full = url.startsWith('http') ? url : `${this.baseUrl}${url}`;
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const res = await fetch(full);
      if (res.ok) return res.blob();
      if (res.status === 425) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        continue;
      }
      const body = await res.text();
      throw new Error(`Chunk fetch failed (${res.status}): ${body || 'Unknown error'}`);
    }
    throw new Error('Chunk fetch timed out while waiting for synthesis.');
  }

  async stop(jobId) {
    const res = await fetch(`${this.baseUrl}/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId }),
    });
    if (!res.ok) throw new Error(`Stop failed: ${res.status}`);
    return res.json();
  }
}
