// Model management uses a bounded native proxy. No token reaches JavaScript.
const JOB_KEY = 'local-voice-model-job';
const active = (job) => job && ['queued', 'downloading'].includes(job.status);
const bytes = (size) => size == null ? 'unknown size' : `${(size / 1048576).toFixed(1)} MiB`;

export function createNativeModelRequest(invoke) {
  return async (path, options = {}) => {
    if (!invoke) throw new Error('Native desktop authorization is unavailable.');
    const method = options.method ?? 'GET';
    const job = /^\/models\/downloads\/([0-9a-f]{32})(\/cancel)?$/.exec(path);
    let action;
    if (path === '/models' && method === 'GET') action = 'catalog';
    else if (path === '/models/downloads' && method === 'POST') action = 'download';
    else if (path === '/models/removals' && method === 'POST') action = 'remove';
    else if (path === '/models/migration' && method === 'GET') action = 'migration';
    else if (path === '/models/migration' && method === 'POST') action = 'migrate';
    else if (job && method === (job[2] ? 'POST' : 'GET')) action = job[2] ? 'cancel' : 'job';
    else throw new Error('Invalid model management route.');
    let body = {};
    if (['download', 'remove', 'migrate'].includes(action)) {
      try { body = JSON.parse(options.body); } catch { throw new Error('Invalid model management request.'); }
    }
    try {
      return await invoke('manage_models', { action, jobId: job?.[1] ?? null,
        languages: body.languages ?? null, candidates: body.candidates ?? null });
    } catch (error) {
      throw new Error(error?.message ?? String(error));
    }
  };
}

export function choiceAssets(catalog, ids) {
  const required = new Set(catalog.languages.filter((language) => ids.includes(language.id))
    .flatMap((language) => language.assets));
  return catalog.assets.filter((asset) => required.has(asset.id));
}

export function createModelManager({ root, request, confirm, storage, onCatalog = () => {} }) {
  let catalog = null;
  let job = null;
  let migration = [];
  let selected = [];
  let notice = '';
  let available = true;
  const el = (selector) => root.querySelector(selector);
  const node = (tag, text) => {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  };
  const call = (path, options) => request(`/models${path}`, options);
  const selectedAssets = () => choiceAssets(catalog, selected);
  const render = () => {
    el('#model-message').textContent = notice;
    el('#model-unavailable').hidden = available;
    el('#model-content').hidden = !available || !catalog;
    if (!catalog) return;
    const choices = el('#model-choices');
    choices.replaceChildren();
    for (const language of catalog.languages) {
      const label = node('label', `${language.label} (${language.engine}) ${language.installed ? 'Installed' : 'Setup needed'}`);
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = language.id;
      input.checked = selected.includes(language.id);
      input.addEventListener('change', () => {
        selected = catalog.languages.filter((item) =>
          item.id === language.id ? input.checked : selected.includes(item.id)).map((item) => item.id);
        render();
      });
      label.prepend(input);
      const voiceList = node('span', ` Voices: ${language.voices.map((voice) => voice.label).join(', ')}`);
      label.append(voiceList);
      choices.append(label);
    }
    const assets = selectedAssets();
    const list = el('#model-assets');
    list.replaceChildren();
    const shared = catalog.assets.filter((item) => catalog.languages.filter((lang) =>
      lang.assets.includes(item.id)).length > 1).map((item) => item.id);
    for (const asset of assets) {
      list.append(node('li', `${asset.id}${shared.includes(asset.id) ? ' (shared)' : ''}: ${bytes(asset.size_bytes)}, ${asset.state}, ${asset.license || 'license unknown'}`));
    }
    const missing = assets.filter((asset) => asset.state !== 'verified');
    const known = missing.reduce((sum, asset) => sum + (asset.size_bytes || 0), 0);
    el('#model-size').textContent = selected.length
      ? `Transfer for missing assets: ${bytes(known)}${missing.some((asset) => asset.size_bytes == null) ? ' plus unknown size' : ''}. Installed disk use may be higher; runtime assets are not included.`
      : 'Select languages to review assets and transfer sizes. No download starts on selection.';
    el('#model-download').disabled = !selected.length || !!active(job);
    el('#model-remove').disabled = !selected.length || !!active(job) || !selected.some((id) =>
      catalog.languages.find((language) => language.id === id)?.installed);
    el('#model-cancel').hidden = !active(job);
    const progress = el('#model-progress');
    progress.hidden = !job;
    if (job) {
      const total = job.bytes_total == null ? 'unknown total' : bytes(job.bytes_total);
      progress.textContent = `${job.status}: ${bytes(job.bytes_done || 0)} / ${total}${job.error ? `, ${job.error}` : ''}`;
    }
    const migrationList = el('#model-migration');
    migrationList.replaceChildren();
    for (const candidate of migration) {
      const button = node('button', `Import ${candidate.asset_id} from ${candidate.source}`);
      button.type = 'button';
      button.className = 'secondary';
      button.addEventListener('click', () => run(async () => {
        if (!await confirm(`Copy ${candidate.asset_id} from ${candidate.source}? The original is kept.`, { title: 'Import existing model' })) return;
        const result = await call('/migration', { method: 'POST', body: JSON.stringify({ candidates: [candidate.id] }) });
        notice = `Imported ${result.migrated.join(', ')}. The source was kept.`;
        await refresh();
      }));
      migrationList.append(button);
    }
  };
  const run = async (action) => {
    try { await action(); } catch (error) { notice = error.message; render(); }
  };
  const refresh = async () => {
    catalog = await call('');
    available = true;
    onCatalog(catalog);
    migration = (await call('/migration')).candidates;
    const id = storage.getItem(JOB_KEY);
    if (!id) job = null;
    if (id) {
      try {
        job = await call(`/downloads/${encodeURIComponent(id)}`);
        if (!active(job)) storage.removeItem(JOB_KEY);
      } catch (error) {
        job = null;
        storage.removeItem(JOB_KEY);
        notice = 'Previous download job is unavailable after service restart. Check installed assets, then retry.';
      }
    }
    render();
  };
  const poll = async () => {
    if (!active(job)) return;
    try {
      job = await call(`/downloads/${encodeURIComponent(job.job_id)}`);
      if (!active(job)) {
        storage.removeItem(JOB_KEY);
        notice = job.status === 'failed' ? `Download failed: ${job.error || 'Unknown error'}. Retry after checking the service.`
          : job.status === 'cancelled' ? 'Download cancelled. You can retry.' : 'Download complete.';
        await refresh();
      } else render();
    } catch (error) {
      notice = error.message;
      render();
    }
  };
  el('#model-download').addEventListener('click', () => run(async () => {
    const ids = [...selected];
    const assets = selectedAssets().filter((asset) => asset.state !== 'verified');
    if (!await confirm(`Download ${ids.map((id) => catalog.languages.find((item) => item.id === id).label).join(', ')}?\n\n${assets.map((asset) => `${asset.id}: ${bytes(asset.size_bytes)}${asset.license ? ` (${asset.license})` : ' (license unknown)'}`).join('\n')}\n\nShared assets are transferred once. Installed disk use and runtime assets are not included.`, { title: 'Download model assets' })) return;
    try {
      job = await call('/downloads', { method: 'POST', body: JSON.stringify({ languages: ids }) });
      storage.setItem(JOB_KEY, job.job_id);
      notice = 'Download started in the service. You can close this window.';
    } catch (error) {
      notice = `Download unavailable: ${error.message}${ids.includes('en') ? ' English is blocked until the spaCy wheel digest is verified.' : ''}`;
    }
    render();
  }));
  el('#model-cancel').addEventListener('click', () => run(async () => {
    job = await call(`/downloads/${encodeURIComponent(job.job_id)}/cancel`, { method: 'POST' });
    notice = 'Cancellation requested.';
    render();
  }));
  el('#model-remove').addEventListener('click', () => run(async () => {
    const ids = selected.filter((id) => catalog.languages.find((item) => item.id === id)?.installed);
    if (!ids.length || !await confirm(`Remove ${ids.map((id) => catalog.languages.find((item) => item.id === id).label).join(', ')}? Shared assets needed by other installed languages are kept. Removal is refused while assets are in use.`, { title: 'Remove models' })) return;
    try {
      const result = await call('/removals', { method: 'POST', body: JSON.stringify({ languages: ids }) });
      notice = `Removed: ${result.removed.join(', ') || 'no assets'}.`;
      await refresh();
    } catch (error) {
      notice = `Removal refused: ${error.message}`;
      render();
    }
  }));
  return {
    async refresh() {
      try { await refresh(); } catch (error) {
        available = false;
        notice = `Model management unavailable: ${error.message}`;
        render();
      }
    },
    poll: () => run(poll),
  };
}
