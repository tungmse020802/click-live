#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect TikTok Open button in a screenshot")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        print(json.dumps({"found": False, "error": "opencv-python and numpy are required"}))
        return

    image_path = Path(args.image)
    if not image_path.exists():
        print(json.dumps({"found": False, "error": f"image not found: {image_path}"}))
        return

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"found": False, "error": f"could not read image: {image_path}"}))
        return

    height, width = image.shape[:2]
    y0 = int(height * 0.72)
    roi = image[y0:height, 0:width]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # TikTok action buttons are usually red/pink. Keep this strict and fall
    # back to ratio tapping when the visual detector is not confident.
    red_low = ((hsv[:, :, 0] <= 12) & (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 120))
    red_high = ((hsv[:, :, 0] >= 165) & (hsv[:, :, 1] >= 65) & (hsv[:, :, 2] >= 120))
    mask = (red_low | red_high).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        full_y = y + y0
        if w < width * 0.42 or h < 28:
            continue
        if w > width * 0.92 or h > height * 0.18:
            continue
        if area < w * h * 0.35:
            continue
        if full_y < height * 0.78:
            continue
        center_bias = 1.0 - min(1.0, abs((x + w / 2) - width / 2) / (width / 2))
        bottom_bias = full_y / height
        score = (area / max(1, width * height)) * 20 + center_bias * 0.35 + bottom_bias * 0.25
        candidates.append({
            "x": int(x),
            "y": int(full_y),
            "w": int(w),
            "h": int(h),
            "area": round(float(area), 1),
            "score": round(float(score), 4),
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        print(json.dumps({
            "found": False,
            "screen": {"w": width, "h": height},
            "candidates": [],
        }))
        return

    best = candidates[0]
    tap = {"x": best["x"] + best["w"] // 2, "y": best["y"] + best["h"] // 2}
    print(json.dumps({
        "found": True,
        "score": best["score"],
        "screen": {"w": width, "h": height},
        "box": best,
        "tap": tap,
        "candidates": candidates[:5],
    }))


if __name__ == "__main__":
    main()
