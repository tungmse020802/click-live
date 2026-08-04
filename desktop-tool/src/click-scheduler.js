/** Generation token — chỉ click job mới nhất được fire. */

let clickGeneration = 0;

function nextClickGeneration() {
  clickGeneration += 1;
  return clickGeneration;
}

function currentClickGeneration() {
  return clickGeneration;
}

function isCurrentClickGeneration(gen) {
  return gen === clickGeneration;
}

/** Hủy vòng waitUntilTimestamp đang chạy (job cũ). */
let abortActiveWait = null;

function abortClickWait() {
  if (typeof abortActiveWait === "function") {
    try {
      abortActiveWait();
    } catch {
      /* ignore */
    }
  }
  abortActiveWait = null;
}

function registerClickWaitAbort(fn) {
  abortClickWait();
  abortActiveWait = typeof fn === "function" ? fn : null;
}

function clearClickWaitAbort(fn) {
  if (abortActiveWait === fn) abortActiveWait = null;
}

module.exports = {
  nextClickGeneration,
  currentClickGeneration,
  isCurrentClickGeneration,
  abortClickWait,
  registerClickWaitAbort,
  clearClickWaitAbort,
};
