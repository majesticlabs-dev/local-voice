export function noVerifiedVoice(catalog) {
  return !catalog?.languages?.some((language) => language.voices.some((voice) => voice.installed));
}

export function createSetupGuide(openModels, notify) {
  let prompted = false;
  return {
    promptOnce({ setupNeeded, modelsChecked, catalog }) {
      if (prompted || !modelsChecked || !setupNeeded || !noVerifiedVoice(catalog)) return false;
      prompted = true;
      openModels(false);
      return true;
    },
    async requireVoice({ setupNeeded, catalog }) {
      if (!setupNeeded || !noVerifiedVoice(catalog)) return true;
      await notify('No voice is installed. Open the Model manager and choose a language to set up speech.');
      openModels(true);
      return false;
    },
  };
}
