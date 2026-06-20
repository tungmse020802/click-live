#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect TikTok treasure icon in an iOS screenshot")
    parser.add_argument("--image", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--mask", default="")
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument(
        "--min-red-ratio",
        type=float,
        default=0.06,
        help="Minimum red/pink pixel ratio required for a yellow/red treasure chest",
    )
    parser.add_argument("--min-warm-ratio", type=float, default=0.18, help="Minimum yellow/pink/cream ratio for treasure variants with weak red")
    parser.add_argument("--scales", default="0.75,0.85,0.95,1.0,1.1,1.2,1.35", help="Comma-separated template scales")
    parser.add_argument("--roi", default="0,240,430,360", help="x,y,w,h in screenshot pixels")
    parser.add_argument("--debug-dir", default="", help="Optional directory to save ROI and detection crop")
    args = parser.parse_args()

    try:
        import cv2  # type: ignore
    except ImportError:
        print(json.dumps({"found": False, "error": "opencv-python is required. Install with: python3 -m pip install opencv-python numpy"}))
        return

    image_path = Path(args.image)
    template_path = Path(args.template)
    if not image_path.exists():
        print(json.dumps({"found": False, "error": f"image not found: {image_path}"}))
        return
    if not template_path.exists():
        print(json.dumps({"found": False, "error": f"template not found: {template_path}"}))
        return

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"found": False, "error": f"could not read image: {image_path}"}))
        return
    if template is None:
        print(json.dumps({"found": False, "error": f"could not read template: {template_path}"}))
        return

    try:
        rx, ry, rw, rh = [int(float(part.strip())) for part in args.roi.split(",", 3)]
    except Exception:
        print(json.dumps({"found": False, "error": f"invalid roi: {args.roi}"}))
        return

    height, width = image.shape[:2]
    rx = max(0, min(rx, width - 1))
    ry = max(0, min(ry, height - 1))
    rw = max(1, min(rw, width - rx))
    rh = max(1, min(rh, height - ry))
    roi = image[ry:ry + rh, rx:rx + rw]

    base_th, base_tw = template.shape[:2]
    if rw < base_tw or rh < base_th:
        print(json.dumps({
            "found": False,
            "error": "template_larger_than_roi",
            "screen": {"w": width, "h": height},
            "roi": {"x": rx, "y": ry, "w": rw, "h": rh},
            "template": {"w": base_tw, "h": base_th},
        }))
        return

    base_mask = None
    mask_path = Path(args.mask) if args.mask else None
    if mask_path and mask_path.exists():
        base_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if base_mask is not None and base_mask.shape[:2] != (base_th, base_tw):
            base_mask = cv2.resize(base_mask, (base_tw, base_th), interpolation=cv2.INTER_NEAREST)

    scales = []
    for raw_scale in args.scales.split(","):
        try:
            scale = float(raw_scale.strip())
        except ValueError:
            continue
        if 0.2 <= scale <= 3:
            scales.append(scale)
    if 1.0 not in scales:
        scales.append(1.0)

    best = None
    for scale in sorted(set(scales)):
        tw = max(8, int(round(base_tw * scale)))
        th = max(8, int(round(base_th * scale)))
        if rw < tw or rh < th:
            continue
        scaled_template = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        scaled_mask = None
        if base_mask is not None:
            scaled_mask = cv2.resize(base_mask, (tw, th), interpolation=cv2.INTER_NEAREST)
        method = cv2.TM_CCORR_NORMED if scaled_mask is not None else cv2.TM_CCOEFF_NORMED
        result = (
            cv2.matchTemplate(roi, scaled_template, method, mask=scaled_mask)
            if scaled_mask is not None
            else cv2.matchTemplate(roi, scaled_template, method)
        )
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        candidate = {
            "score": float(max_val),
            "loc": max_loc,
            "scale": scale,
            "w": tw,
            "h": th,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if best is None:
        print(json.dumps({
            "found": False,
            "error": "no_template_scale_fits_roi",
            "screen": {"w": width, "h": height},
            "roi": {"x": rx, "y": ry, "w": rw, "h": rh},
            "template": {"w": base_tw, "h": base_th},
        }))
        return

    score = best["score"]
    tw = best["w"]
    th = best["h"]
    x = rx + int(best["loc"][0])
    y = ry + int(best["loc"][1])
    candidate = image[y:y + th, x:x + tw]
    candidate_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV)
    red_mask = (
        ((candidate_hsv[:, :, 0] <= 12) | (candidate_hsv[:, :, 0] >= 170))
        & (candidate_hsv[:, :, 1] >= 70)
        & (candidate_hsv[:, :, 2] >= 80)
    )
    warm_mask = (
        (
            ((candidate_hsv[:, :, 0] >= 8) & (candidate_hsv[:, :, 0] <= 42))
            | ((candidate_hsv[:, :, 0] >= 145) & (candidate_hsv[:, :, 0] <= 179))
        )
        & (candidate_hsv[:, :, 1] >= 35)
        & (candidate_hsv[:, :, 2] >= 110)
    )
    red_ratio = float(red_mask.mean())
    warm_ratio = float(warm_mask.mean())
    color_valid = red_ratio >= args.min_red_ratio or warm_ratio >= args.min_warm_ratio
    box = {"x": x, "y": y, "w": tw, "h": th}
    tap = {"x": x + tw // 2, "y": y + th // 2}
    label_debug = detect_timer_label(cv2, image, box)
    found = score >= args.threshold and color_valid and label_debug["found"]
    method = "template"

    color_candidate = detect_color_candidate(
        cv2,
        image,
        {"x": rx, "y": ry, "w": rw, "h": rh},
        args.min_red_ratio,
        args.min_warm_ratio,
    )

    # Prefer the geometry/color candidate when it is clearly stronger. During
    # TikTok load animations, template matching can lock onto a nearby gift or
    # a scaled transition frame while the real chest has the timer underneath.
    cc = color_candidate
    if (cc and cc.get("found")
            and cc.get("score", 0) >= args.threshold
            and cc.get("timer_label", {}).get("found")
            and (not found or cc.get("score", 0) >= score + 0.08)):
        found = True
        score = cc["score"]
        method = "color_candidate"
        cb = cc["box"]
        box = {"x": cb["x"], "y": cb["y"], "w": cb["w"], "h": cb["h"]}
        tap = cc["tap"]
        ob = cc.get("object_box") or cb  # noqa: F841
        red_ratio = cc.get("red_ratio", red_ratio)
        warm_ratio = cc.get("warm_ratio", warm_ratio)
        color_valid = True
        label_debug = cc.get("timer_label", label_debug)

    debug = {}
    reject_reasons = []
    if score < args.threshold:
        reject_reasons.append("score_below_threshold")
    if not color_valid:
        reject_reasons.append("color_below_min_ratio")
    if not label_debug["found"]:
        reject_reasons.append("timer_label_not_visible")
    if args.debug_dir:
        debug_dir = Path(args.debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        stem = image_path.stem + "-" + template_path.stem
        roi_path = debug_dir / f"{stem}-roi.png"
        crop_path = debug_dir / f"{stem}-crop.png"
        marked_path = debug_dir / f"{stem}-marked.png"
        json_path = debug_dir / f"{stem}-debug.json"
        cv2.imwrite(str(roi_path), roi)
        cv2.imwrite(str(crop_path), candidate)
        marked = image.copy()
        cv2.rectangle(marked, (rx, ry), (rx + rw, ry + rh), (120, 120, 120), 2)
        cv2.rectangle(marked, (x, y), (x + tw, y + th), (0, 255, 0) if found else (0, 165, 255), 3)
        if label_debug["found"]:
            lb = label_debug["box"]
            cv2.rectangle(marked, (lb["x"], lb["y"]), (lb["x"] + lb["w"], lb["y"] + lb["h"]), (255, 255, 0), 2)
        if color_candidate:
            cb = color_candidate["box"]
            ob = color_candidate.get("object_box") or cb
            cv2.rectangle(marked, (cb["x"], cb["y"]), (cb["x"] + cb["w"], cb["y"] + cb["h"]), (255, 0, 255), 3)
            cv2.rectangle(marked, (ob["x"], ob["y"]), (ob["x"] + ob["w"], ob["y"] + ob["h"]), (255, 0, 120), 2)
            if color_candidate.get("timer_label", {}).get("found"):
                clb = color_candidate["timer_label"]["box"]
                cv2.rectangle(marked, (clb["x"], clb["y"]), (clb["x"] + clb["w"], clb["y"] + clb["h"]), (255, 160, 255), 2)
        cv2.drawMarker(marked, (tap["x"], tap["y"]), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=28, thickness=3)
        cv2.putText(
            marked,
            f"found={found} score={score:.3f} red={red_ratio:.3f} warm={warm_ratio:.3f}",
            (12, max(24, ry - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        if reject_reasons:
            cv2.putText(
                marked,
                "reject=" + ",".join(reject_reasons[:2]),
                (12, max(48, ry + 24)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 220, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(marked_path), marked)
        debug = {
            "roi_path": str(roi_path),
            "crop_path": str(crop_path),
            "marked_path": str(marked_path),
            "json_path": str(json_path),
        }
    result = {
        "found": found,
        "score": round(score, 4),
        "threshold": args.threshold,
        "red_ratio": round(red_ratio, 4),
        "min_red_ratio": args.min_red_ratio,
        "warm_ratio": round(warm_ratio, 4),
        "min_warm_ratio": args.min_warm_ratio,
        "color_valid": color_valid,
        "method": method,
        "scale": best["scale"],
        "color_candidate": color_candidate,
        "timer_label": label_debug,
        "screen": {"w": width, "h": height},
        "roi": {"x": rx, "y": ry, "w": rw, "h": rh},
        "box": box,
        "tap": tap,
        "template": str(template_path),
        "mask": str(mask_path) if mask_path and mask_path.exists() else None,
        "reject_reasons": reject_reasons,
        "debug": debug,
    }
    if args.debug_dir:
        Path(debug["json_path"]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def detect_timer_label(cv2, image, box):
    height, width = image.shape[:2]
    pad_x = max(10, int(box["w"] * 0.28))
    label_x = max(0, box["x"] - pad_x)
    label_y = max(0, box["y"] + int(box["h"] * 0.58))
    label_w = min(width - label_x, box["w"] + pad_x * 2)
    label_h = min(height - label_y, max(28, int(box["h"] * 0.58)))
    if label_w <= 0 or label_h <= 0:
        return {"found": False, "box": None, "white_ratio": 0.0, "method": "invalid_roi"}

    label_roi = image[label_y:label_y + label_h, label_x:label_x + label_w]
    gray = cv2.cvtColor(label_roi, cv2.COLOR_BGR2GRAY)
    white = gray >= 178
    white_ratio = float(white.mean())
    heuristic_found = white_ratio >= 0.025
    ocr = detect_timer_label_ocr(cv2, label_roi)
    # Use OCR when available, but keep the white-pixel heuristic as a fallback.
    found = bool(ocr["found"] or heuristic_found)
    return {
        "found": found,
        "box": {"x": label_x, "y": label_y, "w": label_w, "h": label_h},
        "white_ratio": round(white_ratio, 4),
        "method": "ocr" if ocr["found"] else "heuristic",
        "ocr": ocr,
    }


def detect_timer_label_ocr(cv2, label_roi):
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return {"available": False, "found": False, "text": "", "normalized": "", "error": "pytesseract_or_pillow_missing"}

    if label_roi.size == 0:
        return {"available": True, "found": False, "text": "", "normalized": "", "error": "empty_roi"}

    gray = cv2.cvtColor(label_roi, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    prepared = cv2.bitwise_not(thresh)

    try:
        text = pytesseract.image_to_string(
            Image.fromarray(prepared),
            config="--psm 7 -c tessedit_char_whitelist=0123456789:",
        )
    except Exception as error:
        return {"available": True, "found": False, "text": "", "normalized": "", "error": str(error)}

    normalized = re.sub(r"[^0-9:]", "", text or "")
    found = bool(re.search(r"\d", normalized))
    return {
        "available": True,
        "found": found,
        "text": text.strip(),
        "normalized": normalized,
    }


def color_ratios(cv2, image):
    if image.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red_mask = (
        ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
        & (hsv[:, :, 1] >= 70)
        & (hsv[:, :, 2] >= 80)
    )
    warm_mask = (
        (
            ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 46))
            | ((hsv[:, :, 0] >= 145) & (hsv[:, :, 0] <= 179))
        )
        & (hsv[:, :, 1] >= 30)
        & (hsv[:, :, 2] >= 105)
    )
    return float(red_mask.mean()), float(warm_mask.mean())


def detect_color_candidate(cv2, image, roi_box, min_red_ratio, min_warm_ratio):
    rx, ry, rw, rh = roi_box["x"], roi_box["y"], roi_box["w"], roi_box["h"]
    roi = image[ry:ry + rh, rx:rx + rw]
    if roi.size == 0:
        return None
    height, width = image.shape[:2]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red = (
        ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
        & (hsv[:, :, 1] >= 70)
        & (hsv[:, :, 2] >= 80)
    )
    warm = (
        (
            ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 46))
            | ((hsv[:, :, 0] >= 145) & (hsv[:, :, 0] <= 179))
        )
        & (hsv[:, :, 1] >= 30)
        & (hsv[:, :, 2] >= 105)
    )
    mask = ((red | warm).astype("uint8")) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in contours:
        cx, cy, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        max_w = min(int(width * 0.42), int(rw * 0.70), 260)
        max_h = min(int(height * 0.12), int(rh * 0.45), 145)
        if cw < 48 or ch < 34 or cw > max_w or ch > max_h:
            continue
        if area < 1600 or area > 26000:
            continue
        aspect = cw / max(1, ch)
        if aspect < 0.75 or aspect > 2.6:
            continue
        center_x = rx + cx + cw / 2
        center_y = ry + cy + ch / 2
        if center_x > width * 0.52:
            continue
        if center_y < height * 0.18 or center_y > height * 0.58:
            continue

        pad_x = max(10, int(cw * 0.28))
        pad_y_top = max(8, int(ch * 0.20))
        pad_y_bottom = max(12, int(ch * 0.35))
        x = max(0, rx + cx - pad_x)
        y = max(0, ry + cy - pad_y_top)
        right = min(image.shape[1], rx + cx + cw + pad_x)
        bottom = min(image.shape[0], ry + cy + ch + pad_y_bottom)
        box = {"x": x, "y": y, "w": max(1, right - x), "h": max(1, bottom - y)}
        object_box = {"x": rx + cx, "y": ry + cy, "w": cw, "h": ch}
        candidate = image[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
        red_ratio, warm_ratio = color_ratios(cv2, candidate)
        timer_label = detect_timer_label(cv2, image, object_box)
        color_ok = red_ratio >= min_red_ratio or warm_ratio >= min_warm_ratio
        if not color_ok or not timer_label["found"]:
            continue

        area_score = min(1.0, area / 9000)
        label_score = 0.22
        ratio_score = min(0.45, warm_ratio) + min(0.25, red_ratio * 1.5)
        aspect_score = max(0.0, 0.18 - abs(aspect - 1.35) * 0.08)
        position_score = max(0.0, 0.14 - abs((center_x / width) - 0.22) * 0.22)
        score = 0.35 + area_score * 0.16 + ratio_score + label_score + aspect_score + position_score
        score = min(0.99, score)
        result = {
            "found": True,
            "score": round(float(score), 4),
            "red_ratio": round(red_ratio, 4),
            "warm_ratio": round(warm_ratio, 4),
            "box": box,
            "object_box": object_box,
            "tap": {
                "x": object_box["x"] + object_box["w"] // 2,
                "y": object_box["y"] + max(1, int(object_box["h"] * 0.45)),
            },
            "timer_label": timer_label,
        }
        if best is None or result["score"] > best["score"]:
            best = result
    return best


if __name__ == "__main__":
    main()
