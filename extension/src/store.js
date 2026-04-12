import { DEFAULT_SETTINGS } from './constants.js';

export async function loadSettings() {
  const result = await chrome.storage.local.get('settings');
  const settings = { ...DEFAULT_SETTINGS, ...result.settings };
  if (settings.mode === 'block') settings.mode = 'selection';
  return settings;
}

export async function saveSettings(settings) {
  await chrome.storage.local.set({ settings });
}

export async function getSetting(key) {
  const settings = await loadSettings();
  return settings[key];
}

export async function setSetting(key, value) {
  const settings = await loadSettings();
  settings[key] = value;
  await saveSettings(settings);
  return settings;
}
