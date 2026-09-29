export const SERVICE_UNAVAILABLE = 'Local Voice service unavailable. Restart it or check logs: journalctl --user -u local-voice.service.';

export async function serviceFetch(fetcher, url, options) {
  try {
    return await fetcher(url, options);
  } catch (_) {
    throw new Error(SERVICE_UNAVAILABLE);
  }
}

export function createErrorPresenter(dialog, inline) {
  let dialogOpen = false;
  return {
    async show(message, options) {
      if (message === SERVICE_UNAVAILABLE) {
        inline(message);
        return;
      }
      if (dialogOpen) return;
      dialogOpen = true;
      try {
        await dialog(message, options);
      } finally {
        dialogOpen = false;
      }
    },
  };
}
