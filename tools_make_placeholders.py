"""샘플 프로젝트용 플레이스홀더(촬영 가이드 카드) 생성. 실제 촬영본으로 교체할 것."""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont
proj = sys.argv[1]
base = os.path.dirname(proj)
P = json.load(open(proj, encoding="utf-8"))
font = ImageFont.truetype("assets/fonts/Pretendard-Bold.otf", 58)
small = ImageFont.truetype("assets/fonts/Pretendard-Medium.otf", 40)
pal = [((245,236,228),(221,204,190)), ((232,226,240),(200,190,220)), ((228,238,236),(190,214,208)), ((244,230,232),(222,196,200))]
for i, c in enumerate(P["clips"]):
    a, b = pal[i % len(pal)]
    im = Image.new("RGB", (1080, 1920))
    d = ImageDraw.Draw(im)
    for y in range(1920):
        t = y / 1919
        d.line([(0, y), (1080, y)], fill=tuple(int(a[k]*(1-t)+b[k]*t) for k in range(3)))
    d.rounded_rectangle([90, 560, 990, 900], 40, outline=(120,110,100), width=4)
    d.text((540, 640), f"CUT {os.path.splitext(os.path.basename(c['src']))[0]}", font=small, fill=(120,110,100), anchor="mm")
    d.multiline_text((540, 760), c.get("shot", ""), font=font, fill=(80,70,60), anchor="mm", align="center", spacing=14)
    path = os.path.join(base, c["src"]); os.makedirs(os.path.dirname(path), exist_ok=True); im.save(path, quality=92)
print("ok")
