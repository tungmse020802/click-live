/** Parse stdout từ PowerShell helper (fallback) — giữ cho test tương thích. */

function parseHelperOkLine(line, clickId, px, py) {
  const trimmed = String(line || "").trim();
  const expected = `ok:${clickId},${px},${py}`;
  return trimmed === expected || trimmed.startsWith(`${expected}\r`);
}

function parseHelperPongLine(line, pingId) {
  const trimmed = String(line || "").trim();
  const expected = `pong:${pingId}`;
  return trimmed === expected || trimmed.startsWith(`${expected}\r`);
}

function parseHelperErrLine(line, clickId) {
  const trimmed = String(line || "").trim();
  const withDetail = `err:${clickId},`;
  if (trimmed.startsWith(withDetail)) {
    return trimmed.slice(withDetail.length) || "unknown";
  }
  if (trimmed === `err:${clickId}`) return "unknown";
  return null;
}

module.exports = {
  parseHelperOkLine,
  parseHelperPongLine,
  parseHelperErrLine,
};
