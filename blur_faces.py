#!/usr/bin/env python3
"""완성된 릴스에서 얼굴을 자동 인식해 블러 처리한다.

사용법:
    python blur_faces.py input.mp4 output.mp4 --model yunet.onnx [--manual manual.json]

- 얼굴 검출: OpenCV YuNet (face_detection_yunet_2023mar.onnx)
- 검출이 순간적으로 끊겨도 최대 HOLD 프레임 동안 직전 위치 유지 → 블러가 깜빡이지 않게
- manual.json: 자동 검출이 놓치는 구간을 직접 지정
    [{"start": 12.0, "end": 13.5, "box": [x, y, w, h]}]   (1080x1920 기준 픽셀)
필요: pip install opencv-python-headless numpy, ffmpeg
"""
import argparse
import json
import subprocess

import cv2
import numpy as np

HOLD = 20          # 검출 끊김 시 유지 프레임 수 (30fps 기준 0.4초)
PAD = 0.6         # 얼굴 박스 확장 비율 (머리카락·턱선까지 덮도록)
SMOOTH = 0.6       # 박스 위치 스무딩 (0=즉시 이동, 1=고정)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    n, d = out[2].split("/")
    return int(out[0]), int(out[1]), float(n) / float(d)


def blur_region(frame, box):
    H, W = frame.shape[:2]
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    w, h = w * (1 + PAD * 2), h * (1 + PAD * 2)
    x0, y0 = int(max(0, cx - w / 2)), int(max(0, cy - h / 2))
    x1, y1 = int(min(W, cx + w / 2)), int(min(H, cy + h / 2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = frame[y0:y1, x0:x1]
    # 모자이크 + 가우시안 → 확실히 식별 불가하도록
    small = cv2.resize(roi, (max(1, (x1 - x0) // 18), max(1, (y1 - y0) // 18)), interpolation=cv2.INTER_LINEAR)
    pix = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    k = max(31, ((x1 - x0) // 3) | 1)
    blurred = cv2.GaussianBlur(pix, (k, k), 0)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.ellipse(mask, ((x1 - x0) // 2, (y1 - y0) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (21, 21), 0)[..., None] / 255.0
    frame[y0:y1, x0:x1] = (blurred * mask + roi * (1 - mask)).astype(np.uint8)


def blur_video(inp, output, model, manual=None, skip=None, score=0.5, log_path=None):
    """skip: [(start, end), ...] 블러를 적용하지 않을 구간(사진 컷 등 오검출 방지)."""
    class A: pass
    args = A()
    args.input, args.output, args.model, args.log = inp, output, model, log_path
    W, H, fps = probe(args.input)
    manual = manual or []
    skip = skip or []
    det = cv2.FaceDetectorYN.create(args.model, "", (W // 2, H // 2), score, 0.3, 50)

    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", args.input, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", f"{fps}", "-i", "-", "-i", args.input, "-map", "0:v", "-map", "1:a?",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-movflags", "+faststart", args.output], stdin=subprocess.PIPE)
    tracks = []  # [box(np), missed]
    log = []
    i = 0
    size = W * H * 3
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        tsec = i / fps
        if any(a <= tsec < b for a, b in skip):
            tracks = []
            log.append((round(tsec, 2), -1, 0))
            enc.stdin.write(frame.tobytes())
            i += 1
            continue
        small = cv2.resize(frame, (W // 2, H // 2))
        _, faces = det.detect(small)
        boxes = [] if faces is None else [f[:4] * 2 for f in faces]

        # 간단한 트래킹: 가장 가까운 기존 트랙에 매칭
        for t in tracks:
            t[1] += 1
        for b in boxes:
            c = b[:2] + b[2:] / 2
            best, bd = None, 1e9
            for t in tracks:
                d = np.linalg.norm((t[0][:2] + t[0][2:] / 2) - c)
                if d < bd:
                    best, bd = t, d
            if best is not None and bd < max(b[2], b[3]) * 1.5:
                best[0] = best[0] * SMOOTH + b * (1 - SMOOTH) if best[1] <= 1 else b
                best[1] = 0
            else:
                tracks.append([b.astype(float), 0])
        tracks = [t for t in tracks if t[1] <= HOLD]

        for t in tracks:
            blur_region(frame, t[0])
        for m in manual:
            if m["start"] <= tsec <= m["end"]:
                blur_region(frame, m["box"])
        log.append((round(tsec, 2), len(boxes), len(tracks)))
        enc.stdin.write(frame.tobytes())
        i += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    if args.log:
        json.dump(log, open(args.log, "w"))
    print(f"블러 완료: {args.output} ({i} frames)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--model", required=True)
    ap.add_argument("--manual")
    ap.add_argument("--score", type=float, default=0.5)
    ap.add_argument("--log")
    a = ap.parse_args()
    blur_video(a.input, a.output, a.model, json.load(open(a.manual)) if a.manual else None,
               score=a.score, log_path=a.log)


if __name__ == "__main__":
    main()
