const { systemPreferences } = require("electron");

function ensureAccessibility(prompt = true) {
  if (process.platform !== "darwin") {
    return { ok: true, trusted: true, platform: process.platform };
  }
  const trusted = systemPreferences.isTrustedAccessibilityClient(prompt);
  return { ok: trusted, trusted, platform: "darwin" };
}

module.exports = {
  ensureAccessibility,
};
