"use strict";

const MODES = new Set(["off", "json", "images", "all"]);

function normalizeDebugMode(value, fallback = "off") {
  const mode = String(value || fallback || "off").trim().toLowerCase();
  return MODES.has(mode) ? mode : fallback;
}

function shouldWriteJson(mode) {
  return mode === "json" || mode === "images" || mode === "all";
}

function shouldWriteImages(mode) {
  return mode === "images" || mode === "all";
}

function shouldKeepCapture(mode) {
  return shouldWriteImages(mode);
}

module.exports = {
  normalizeDebugMode,
  shouldKeepCapture,
  shouldWriteImages,
  shouldWriteJson,
};
