const { screen } = require("electron");

/**
 * Chuyển tọa độ lưu trong settings → pixel vật lý cho SetCursorPos (Windows DPI).
 */
function toPhysicalScreenPoint(x, y) {
  const px = Math.round(Number(x));
  const py = Math.round(Number(y));
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    throw new Error("Toa do click khong hop le");
  }
  if (process.platform !== "win32") {
    return { x: px, y: py };
  }
  try {
    if (typeof screen.dipToScreenPoint === "function") {
      const physical = screen.dipToScreenPoint({ x: px, y: py });
      return {
        x: Math.round(physical.x),
        y: Math.round(physical.y),
      };
    }
  } catch {
    /* ignore */
  }
  return { x: px, y: py };
}

function readCursorScreenPoint() {
  const pt = screen.getCursorScreenPoint();
  return { x: Math.round(pt.x), y: Math.round(pt.y) };
}

module.exports = {
  toPhysicalScreenPoint,
  readCursorScreenPoint,
};
