#!/usr/bin/env python3
"""완성 전 합본 영상에서 얼굴을 자동 인식해 얼굴 모양(타원)대로 블러 처리한다.

2-pass 방식
  1) 전 프레임 얼굴 검출 (OpenCV YuNet) → 결과 캐시
  2) 컷 단위로 검출을 트랙으로 연결
     - 짧게 튀는 오검출 트랙 제거 (MIN_TRACK 프레임 미만 / 저신뢰)
     - 트랙 내부 검출 누락 프레임은 선형 보간
     - 트랙 시작/끝을 컷 경계 쪽으로 최대 EXTEND 프레임 연장 → 컷 전환 직전 블러 풀림 방지
  3) 얼굴 랜드마크 기준 타원 마스크로 블러

CLI: python blur_faces.py input.mp4 output.mp4 --model yunet.onnx [--cuts 3.6,6.6,...]
필요: pip install opencv-python-headless numpy, ffmpeg
"""
import argparse
import json
import os
import subprocess

import cv2
import numpy as np

MIN_TRACK = 12      # 이 프레임 수 미만으로 잡힌 트랙은 오검출로 간주
MIN_PEAK = 0.80     # 트랙 내 최고 신뢰도가 이보다 낮으면 오검출로 간주
EXTEND = 15         # 트랙 앞뒤 연장 프레임 (컷 경계는 넘지 않음)
SCALE_W = 1.25      # 타원 가로 = 검출 박스 가로 × SCALE_W
SCALE_H = 1.45      # 타원 세로 = 검출 박스 세로 × SCALE_H (이마·턱 포함)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    n, d = out[2].split("/")
    return int(out[0]), int(out[1]), float(n) / float(d)


def frames(path, W, H):
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    size = W * H * 3
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
    dec.wait()


def detect_all(path, model, W, H, score, cache):
    if cache and os.path.exists(cache):
        data = json.load(open(cache))
        if data.get("src_size") == os.path.getsize(path):
            return data["dets"]
    det = cv2.FaceDetectorYN.create(model, "", (W // 2, H // 2), score, 0.3, 50)
    dets = []
    for f in frames(path, W, H):
        _, faces = det.detect(cv2.resize(f, (W // 2, H // 2)))
        dets.append([] if faces is None else [[float(v) * 2 for v in fc[:14]] + [float(fc[14])] for fc in faces])
    if cache:
        json.dump({"src_size": os.path.getsize(path), "dets": dets}, open(cache, "w"))
    return dets


def build_tracks(dets, cut_frames, n, win=1):
    """dets[i] = [[x,y,w,h, 10 landmark coords, score], ...] → 프레임별 박스 리스트."""
    bounds = sorted(set([0] + cut_frames + [n]))
    seg_of = np.zeros(n, int)
    for s, (a, b) in enumerate(zip(bounds, bounds[1:])):
        seg_of[a:b] = s
    tracks = []   # {"seg", "pts": {frame: det}}
    active = []
    for i in range(n):
        if i in bounds:
            active = []
        for d in dets[i]:
            c = np.array([d[0] + d[2] / 2, d[1] + d[3] / 2])
            best, bd = None, 1e9
            for t in active:
                lf = max(t["pts"])
                if i - lf > EXTEND * 2:
                    continue
                ld = t["pts"][lf]
                dist = np.linalg.norm(np.array([ld[0] + ld[2] / 2, ld[1] + ld[3] / 2]) - c)
                if dist < bd:
                    best, bd = t, dist
            if best is not None and bd < max(d[2], d[3]) * 1.2 and i not in best["pts"]:
                best["pts"][i] = d
            else:
                t = {"seg": int(seg_of[i]), "pts": {i: d}}
                tracks.append(t)
                active.append(t)

    out = [[] for _ in range(n)]
    for t in tracks:
        ks = sorted(t["pts"])
        if len(ks) < MIN_TRACK or max(t["pts"][k][-1] for k in ks) < MIN_PEAK:
            continue  # 오검출 제거
        a, b = bounds[t["seg"]], bounds[t["seg"] + 1]
        arr = {k: np.array(t["pts"][k][:14]) for k in ks}
        # 내부 누락 보간
        for k0, k1 in zip(ks, ks[1:]):
            for k in range(k0 + 1, k1):
                r = (k - k0) / (k1 - k0)
                arr[k] = arr[k0] * (1 - r) + arr[k1] * r
        # 앞뒤 연장 (컷 경계 안에서). 컷 경계까지 EXTEND*2 이내면 경계까지 꽉 채움
        first, last = ks[0], ks[-1]
        pre = a if first - a <= EXTEND * 2 else first - EXTEND
        post = b - 1 if (b - 1) - last <= EXTEND * 2 else last + EXTEND
        for k in range(max(a, pre), first):
            arr[k] = arr[first]
        for k in range(last + 1, min(b, post + 1)):
            arr[k] = arr[last]
        # 위치 스무딩 (±win 프레임 가중 이동평균, 이모지는 넓게 → 떨림 방지)
        keys = sorted(arr)
        sm = {}
        for j, k in enumerate(keys):
            idx = [m for m in range(max(0, j - win), min(len(keys), j + win + 1)) if abs(keys[m] - k) <= win]
            wts = np.array([win + 1 - abs(keys[m] - k) for m in idx], float)
            sm[k] = np.average([arr[keys[m]] for m in idx], axis=0, weights=wts)
        for k, v in sm.items():
            out[k].append(v)
    return out


def face_ellipse(d):
    x, y, w, h = d[:4]
    lm = d[4:14].reshape(5, 2)  # 오른눈, 왼눈, 코, 입 오른쪽, 입 왼쪽
    eyes = (lm[0] + lm[1]) / 2
    mouth = (lm[3] + lm[4]) / 2
    # 타원 중심: 눈과 입 사이 약간 위 (이마 포함), 기울기: 두 눈 각도
    cx, cy = (eyes[0] + mouth[0]) / 2, eyes[1] * 0.55 + mouth[1] * 0.45
    if not (x <= cx <= x + w):
        cx, cy = x + w / 2, y + h / 2
    ang = np.degrees(np.arctan2(lm[1][1] - lm[0][1], lm[1][0] - lm[0][0]))
    ax, ay = w * SCALE_W / 2, h * SCALE_H / 2
    # 옆얼굴 보정: 두 눈 간격이 좁으면(고개 돌림) 타원을 넓히고 뒤통수 쪽으로 이동
    turn = 1 - min(1.0, np.linalg.norm(lm[1] - lm[0]) / (w * 0.42 + 1e-6))
    if turn > 0.15:
        facing = np.sign(lm[2][0] - eyes[0]) or 1.0   # 코가 향한 방향
        ax *= 1 + turn * 0.9
        ay *= 1 + turn * 0.25
        cx -= facing * w * 0.25 * turn
        ang *= 1 - turn
    return cx, cy, ax, ay, ang


def blur_face(frame, d):
    H, W = frame.shape[:2]
    cx, cy, ax, ay, ang = face_ellipse(d)
    r = int(max(ax, ay)) + 4
    x0, y0, x1, y1 = int(max(0, cx - r)), int(max(0, cy - r)), int(min(W, cx + r)), int(min(H, cy + r))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return
    roi = frame[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 22), max(1, (y1 - y0) // 22)), interpolation=cv2.INTER_AREA)
    pix = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    k = max(15, ((x1 - x0) // 3) | 1)
    blurred = cv2.GaussianBlur(cv2.GaussianBlur(pix, (k, k), 0), (k, k), 0)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.ellipse(mask, (int(cx - x0), int(cy - y0)), (int(ax), int(ay)), ang, 0, 360, 255, -1)
    feather = max(5, int(min(ax, ay) * 0.12) | 1)
    mask = cv2.GaussianBlur(mask, (feather, feather), 0)[..., None] / 255.0
    frame[y0:y1, x0:x1] = (blurred * mask + roi * (1 - mask)).astype(np.uint8)


_EMOJI = {}


def overlay_emoji(frame, d, path, scale=1.12):
    """얼굴 타원을 완전히 덮도록 이모지(RGBA PNG)를 얹는다."""
    if path not in _EMOJI:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        ys, xs = np.where(img[..., 3] > 10)          # 투명 여백 제거
        _EMOJI[path] = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    em = _EMOJI[path]
    H, W = frame.shape[:2]
    cx, cy, ax, ay, ang = face_ellipse(d)
    size = int(2 * max(ax, ay) * scale)
    if size < 8:
        return
    eh, ew = em.shape[:2]
    sw, sh = int(size * ew / max(eh, ew)), int(size * eh / max(eh, ew))
    e = cv2.resize(em, (sw, sh), interpolation=cv2.INTER_LANCZOS4 if sw > ew else cv2.INTER_AREA)
    pad = int(max(sw, sh) * 0.3)
    e = cv2.copyMakeBorder(e, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    M = cv2.getRotationMatrix2D((e.shape[1] / 2, e.shape[0] / 2), -ang, 1.0)
    e = cv2.warpAffine(e, M, (e.shape[1], e.shape[0]), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    x0, y0 = int(round(cx - e.shape[1] / 2)), int(round(cy - e.shape[0] / 2))
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(W, x0 + e.shape[1]), min(H, y0 + e.shape[0])
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sub = e[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = sub[..., 3:4].astype(np.float32) / 255.0
    roi = frame[fy0:fy1, fx0:fx1]
    frame[fy0:fy1, fx0:fx1] = (sub[..., :3] * a + roi * (1 - a)).astype(np.uint8)


def blur_rect(frame, box):
    """수동 지정 영역(표지·번호 등) 사각형 블러, 가장자리만 살짝 부드럽게."""
    H, W = frame.shape[:2]
    x, y, w, h = [int(v) for v in box]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = frame[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), interpolation=cv2.INTER_AREA)
    pix = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    k = max(9, (min(x1 - x0, y1 - y0) // 2) | 1)
    blurred = cv2.GaussianBlur(cv2.GaussianBlur(pix, (k, k), 0), (k, k), 0)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    e = max(2, min(x1 - x0, y1 - y0) // 8)
    cv2.rectangle(mask, (e, e), (x1 - x0 - e, y1 - y0 - e), 255, -1)
    mask = cv2.GaussianBlur(mask, (2 * e + 1, 2 * e + 1), 0)[..., None] / 255.0
    frame[y0:y1, x0:x1] = (blurred * mask + roi * (1 - mask)).astype(np.uint8)


def blur_video(inp, output, model, manual=None, skip=None, cuts=None, score=0.5, cache=None, emoji=None):
    """skip: [(s,e)] 블러 제외 구간(초) / cuts: 컷 경계(초) 리스트 / manual: 수동 지정 박스."""
    W, H, fps = probe(inp)
    dets = detect_all(inp, model, W, H, score, cache)
    n = len(dets)
    skip = skip or []
    for i in range(n):
        if any(a <= i / fps < b for a, b in skip):
            dets[i] = []
    cut_frames = [int(round(c * fps)) for c in (cuts or [])]
    per_frame = build_tracks(dets, cut_frames, n)
    emoji_frames = build_tracks(dets, cut_frames, n, win=4) if emoji else None

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", f"{fps}", "-i", "-", "-i", inp, "-map", "0:v", "-map", "1:a?",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-movflags", "+faststart", output], stdin=subprocess.PIPE)
    for i, f in enumerate(frames(inp, W, H)):
        if i < n:
            for d in per_frame[i]:
                blur_face(f, d)
            if emoji:
                for d in emoji_frames[i]:
                    overlay_emoji(f, d, emoji)
        for m in manual or []:
            if m["start"] <= i / fps <= m["end"]:
                blur_rect(f, m["box"])
        enc.stdin.write(f.tobytes())
    enc.stdin.close()
    enc.wait()
    print(f"블러 완료: {output} ({n} frames)")
    return per_frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--model", required=True)
    ap.add_argument("--cuts", default="")
    ap.add_argument("--score", type=float, default=0.5)
    ap.add_argument("--cache")
    a = ap.parse_args()
    cuts = [float(c) for c in a.cuts.split(",") if c]
    blur_video(a.input, a.output, a.model, cuts=cuts, score=a.score, cache=a.cache)


if __name__ == "__main__":
    main()
