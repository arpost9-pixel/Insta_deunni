#!/usr/bin/env python3
"""임신 기록(브이로그형) 인스타 릴스 자동 편집기.

project.json 에 컷(사진/영상)·자막·후킹 문구를 적으면
1080x1920 / 30fps / H.264 MP4 로 렌더링한다.

사용법:
    python3 make_reel.py projects/sample/project.json
    python3 make_reel.py projects/sample/project.json --preview   # 저화질 빠른 확인

필요: ffmpeg (libass, libx264 포함 빌드)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

W, H, FPS = 1080, 1920, 30
ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}

# ---------------------------------------------------------------------------
# 스타일 프리셋 (ASS 색상은 &HAABBGGRR)
#  - vlog : 레퍼런스1 톤. 상단 노란 하이라이트 후킹 + 하단 작은 흰 자막
#  - cute : 레퍼런스3 톤. 핑크 글자 + 흰 외곽선 자막
# ---------------------------------------------------------------------------
PRESETS = {
    "vlog": {
        "caption": "Pretendard SemiBold,46,&H00FFFFFF,&H50000000,&H78000000,0,1,2.2,2,2,90,90,560",
        "caption_box": False,
    },
    "cute": {
        "caption": "Pretendard Bold,50,&H00B469FF,&H00FFFFFF,&H50000000,-1,1,5,1.5,2,90,90,520",
        "caption_box": False,
    },
}
COMMON_STYLES = [
    # name, font, size, primary, outline, back, bold, borderstyle, outline, shadow, align, mL, mR, mV
    "HookTop,Pretendard Bold,50,&H00000000,&H0000E5FF,&H0000E5FF,-1,3,10,0,8,90,90,250",
    "HookMain,Pretendard Bold,72,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,3,14,0,8,90,90,330",
    "Emphasis,Pretendard Bold,120,&H00FFFFFF,&H00000000,&H64000000,-1,1,7,3,5,60,60,0",
    "Ending,Pretendard Medium,76,&H00FFFFFF,&H00000000,&H78000000,0,1,0,4,8,60,60,330",
]


def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_style_line(spec):
    name, font, size, prim, outc, back, bold, bs, ol, sh, al, ml, mr, mv = spec.split(",")
    return (f"Style: {name},{font},{size},{prim},{prim},{outc},{back},{bold},0,0,0,100,100,"
            f"{'6' if name == 'Ending' else '0'},0,{bs},{ol},{sh},{al},{ml},{mr},{mv},1")


def build_ass(project, timeline, path):
    preset = PRESETS[project.get("style", "vlog")]
    styles = [build_style_line("Caption," + preset["caption"])] + [build_style_line(s) for s in COMMON_STYLES]
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ev(start, end, style, text, extra="", layer=0):
        lines.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{extra}{ass_escape(text)}")

    total = timeline[-1][1] if timeline else 0
    hook = project.get("hook")
    if hook:
        hs, he = hook.get("start", 0), hook.get("end", 3)
        if hook.get("top"):
            ev(hs, he, "HookTop", f" {hook['top']} ", layer=1)
        if hook.get("main"):
            ev(hs, he, "HookMain", hook["main"], layer=1)

    for (start, end, clip) in timeline:
        if clip.get("caption"):
            ev(start, end, "Caption", clip["caption"], "{\\fad(80,80)}")
        if clip.get("emphasis"):
            # 살짝 튀어나오는 팝 효과
            ev(start, end, "Emphasis", clip["emphasis"],
               "{\\fscx70\\fscy70\\t(0,140,\\fscx108\\fscy108)\\t(140,240,\\fscx100\\fscy100)}", layer=2)
        if clip.get("ending"):
            ev(start + 0.3, end, "Ending", clip["ending"], "{\\fad(600,300)}", layer=2)

    for extra in project.get("texts", []):  # 컷과 무관한 자유 텍스트
        ev(extra["start"], extra.get("end", total), extra.get("style", "Caption"), extra["text"])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def render_clip(clip, base, out, preview):
    src = os.path.join(base, clip["src"])
    if not os.path.exists(src):
        sys.exit(f"[오류] 소스 파일 없음: {src}")
    dur = float(clip["dur"])
    is_img = os.path.splitext(src)[1].lower() in IMG_EXT
    if is_img:
        frames = int(round(dur * FPS))
        zoom = clip.get("zoom", 0.06)  # 사진은 은은한 줌인(켄번즈)
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='1+{zoom}*on/{max(frames,1)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},setsar=1")
        inp = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", src,
               "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo"]
        af = "anull"
    else:
        speed = float(clip.get("speed", 1.0))
        # 가로 영상 → 세로 크롭. crop_x / crop_y = 프레임 내 중심 위치(0~1), vzoom = 추가 확대 배율
        cx, cy, vz = clip.get("crop_x", 0.5), clip.get("crop_y", 0.5), clip.get("vzoom", 1.0)
        vf = (f"scale='if(gt(a,{W}/{H}),-2,{int(W*vz)})':'if(gt(a,{W}/{H}),{int(H*vz)},-2)',"
              f"crop={W}:{H}:'max(0,min(iw-{W},iw*{cx}-{W//2}))':'max(0,min(ih-{H},ih*{cy}-{H//2}))',setsar=1")
        vf += (f",setpts=PTS/{speed}" if speed != 1.0 else "") + f",fps={FPS}"
        inp = ["-ss", str(clip.get("start", 0)), "-t", f"{dur * speed}", "-i", src,
               "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo"]
        vol = 0 if clip.get("mute") else clip.get("volume", 1.0)
        af = f"volume={vol}" + (f",atempo={speed}" if speed != 1.0 else "")
    vf += ",format=yuv420p"
    has_audio = (not is_img) and subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", src],
        capture_output=True, text=True).stdout.strip() != ""
    amap = "0:a" if has_audio else "1:a"
    fc = f"[0:v]{vf}[v];[{amap}]{af if has_audio else 'anull'},aresample=48000,aformat=channel_layouts=stereo,apad[a]"
    cmd = ["ffmpeg", "-v", "error", "-y", *inp, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-t", f"{dur}", "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium", "-crf", "18",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--preview", action="store_true", help="빠른 저화질 렌더")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg 가 필요합니다.")
    with open(args.project, encoding="utf-8") as f:
        project = json.load(f)
    base = os.path.dirname(os.path.abspath(args.project))
    out = args.output or os.path.join(base, project.get("output", "reel.mp4"))

    tmp = tempfile.mkdtemp(prefix="reel_")
    try:
        timeline, parts, t = [], [], 0.0
        for i, clip in enumerate(project["clips"]):
            p = os.path.join(tmp, f"c{i:03d}.mp4")
            print(f"  컷 {i+1}/{len(project['clips'])}: {clip['src']} ({clip['dur']}s)")
            render_clip(clip, base, p, args.preview)
            parts.append(p)
            timeline.append((t, t + float(clip["dur"]), clip))
            t += float(clip["dur"])

        listf = os.path.join(tmp, "list.txt")
        with open(listf, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        joined = os.path.join(tmp, "joined.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listf,
                        "-c", "copy", joined], check=True)

        bf = project.get("blur_faces")
        if bf:  # 자막 입히기 전에 얼굴 블러 (자막이 블러에 묻히지 않도록)
            from blur_faces import blur_video
            skip = [(a, b) for (a, b, c) in timeline
                    if os.path.splitext(c["src"])[1].lower() in IMG_EXT or c.get("no_blur")]
            blurred = os.path.join(tmp, "blurred.mp4")
            blur_video(joined, blurred, os.path.join(ROOT, bf.get("model", "assets/models/yunet.onnx")),
                       manual=bf.get("manual"), skip=skip, score=bf.get("score", 0.5))
            joined = blurred

        ass = os.path.join(tmp, "subs.ass")
        build_ass(project, timeline, ass)

        total = t
        bgm = project.get("bgm")
        if bgm:
            bgm_path = os.path.join(base, bgm["src"])
            vol = bgm.get("volume", 0.5)
            audio_in = ["-ss", str(bgm.get("start", 0)), "-i", bgm_path]
            fa = (f"[1:a]volume={vol},afade=t=in:d=0.3,afade=t=out:st={max(total-1.5,0)}:d=1.5,apad[b];"
                  f"[0:a][b]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5[a]")
        else:
            audio_in = []
            fa = "[0:a]loudnorm=I=-16:TP=-1.5[a]"
        amap = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]

        fa = f"[0:v]ass='{ass}':fontsdir='{FONT_DIR}'[v];" + fa
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, *audio_in,
                        "-filter_complex", fa, *amap,
                        "-c:v", "libx264", "-preset", "veryfast" if args.preview else "slow",
                        "-crf", "26" if args.preview else "18", "-pix_fmt", "yuv420p",
                        "-t", f"{total}", "-movflags", "+faststart", out], check=True)
        print(f"완료: {out}  ({total:.1f}s)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
