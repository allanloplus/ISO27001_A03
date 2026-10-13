#!/usr/bin/env python3
"""從 characters/ 的人物設定圖切出講師與助教的表情素材，輸出到 img/*.webp。

步驟：裁切 → 去除白色背景 → 製作講話用的嘴形（講師：微笑圖加上張嘴；阿拉蕾：興奮圖修成閉嘴）→ 轉 WebP。
需要：pip install pillow numpy scipy opencv-python-headless
用法：python3 tools/make_sprites.py
若更換設定圖，請同步調整下方 BOX 的裁切座標，以及嘴巴位置（curve 參數）。
"""
import os, tempfile
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "characters")
DST = os.path.join(ROOT, "img")
WORK = tempfile.mkdtemp()
D = WORK

# ── 1. 裁切與去背
BOX = {
 'allan_sheet.jpg': {'allan_full':(40,80,772,1480),
   'allan_smile':(765,790,1025,1125),'allan_laugh':(1070,790,1335,1125),'allan_think':(1380,790,1645,1125),'allan_scratch':(1635,790,1972,1125),
   'allan_surprise':(765,1130,1025,1470),'allan_point':(1040,1130,1335,1470),'allan_wink':(1380,1130,1645,1470),'allan_explain':(1700,1130,1960,1470)},
 'arale_sheet.jpg': {'arale_full':(80,120,450,765),'arale_full2':(70,800,405,1475),
   'arale_laugh':(441,811,792,1112),'arale_think':(826,811,1179,1112),'arale_surprise':(1213,811,1565,1112),'arale_confused':(1598,811,1950,1112),
   'arale_explain':(441,1146,792,1449),'arale_sad':(826,1146,1179,1449),'arale_wink':(1213,1146,1565,1449),'arale_excited':(1598,1146,1950,1449)},
}
for f, boxes in BOX.items():
    src = Image.open(os.path.join(SRC, f)).convert('RGB')
    for name, b in boxes.items():
        im = np.asarray(src.crop(b)).astype(int)
        mx, mn = im.max(2), im.min(2)
        white = (mn > 222) & (mx - mn < 26)
        if 'full' in name:  # 全身圖：分隔線等淺灰也視為背景
            white |= (mn > 165) & (mx - mn < 18)
        lab, n = ndimage.label(white)
        edge = set(np.unique(np.concatenate([lab[0], lab[:, 0], lab[:, -1], lab[-1] if 'full' in name else lab[0]])))
        edge.discard(0)
        bg = np.isin(lab, list(edge))
        # 被手臂圍住的大塊白色空隙（例如抓頭動作）也去掉；眼白等小區塊保留
        sizes = ndimage.sum(np.ones_like(lab), lab, range(n + 1))
        bg |= np.isin(lab, [k for k in range(1, n + 1) if sizes[k] > 2500])
        # 只保留最大的人物區塊，清除鄰圖殘線
        fg_lab, fn = ndimage.label(~bg)
        if fn > 1:
            fs = ndimage.sum(np.ones_like(fg_lab), fg_lab, range(fn + 1)); fs[0] = 0
            bg |= fg_lab != fs.argmax()
        # 去掉孤立雜點，並柔化邊緣
        bg = ndimage.binary_opening(bg, iterations=1) | (bg & ~ndimage.binary_dilation(~bg, iterations=1))
        alpha = np.where(bg, 0, 255).astype(np.uint8)
        alpha = np.asarray(Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(0.8)))
        rgba = np.dstack([im.astype(np.uint8), alpha])
        out = Image.fromarray(rgba, 'RGBA')
        out = out.crop(out.getbbox())
        out.save(os.path.join(WORK, name + '.png'))

# ── 2. 嘴形

def load(n): return Image.open(f'{D}/{n}.png').convert('RGBA')

def curve(x0, x1, ytop, ymid, n=24):
    """拋物線：兩端 ytop、中點 ymid"""
    xs = np.linspace(x0, x1, n); c = (x0 + x1) / 2; h = (x1 - x0) / 2
    return [(x, ytop + (ymid - ytop) * (1 - ((x - c) / h) ** 2)) for x in xs]

# ── 講師：微笑 → 張嘴（兩段開合）
for tag, depth in (('o1', 12), ('o2', 20)):
    S = 4  # 先放大繪製再縮小，邊緣較平滑
    im = load('allan_smile'); big = im.resize((im.width * S, im.height * S), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    top = curve(92, 162, 190.5, 199.5)
    bot = curve(162, 92, 191.5, 199.5 + depth)
    poly = [(x * S, y * S) for x, y in top + bot]
    d.polygon(poly, fill=(92, 30, 32, 255))
    # 舌頭
    tx = 127; ty = 199.5 + depth - 3
    d.ellipse([(tx - 17) * S, (ty - depth * .42) * S, (tx + 17) * S, (ty + 3) * S], fill=(222, 108, 112, 255))
    # 上排牙齒
    teeth = curve(97, 157, 192.5, 201) + curve(157, 97, 194.5, 201 + min(5, depth * .45))
    d.polygon([(x * S, y * S) for x, y in teeth], fill=(250, 250, 248, 255))
    # 重新描嘴型外框，蓋住多出來的舌頭
    mask = Image.new('L', big.size, 0); ImageDraw.Draw(mask).polygon(poly, fill=255)
    base = im.resize(big.size, Image.LANCZOS); base.paste(big, (0, 0), mask); big = base
    ImageDraw.Draw(big).line(poly + [poly[0]], fill=(38, 22, 22, 255), width=int(2.6 * S), joint='curve')
    big.resize(im.size, Image.LANCZOS).save(f'{D}/allan_talk_{tag}.png')

# ── 阿拉蕾：興奮（張嘴）→ 閉嘴微笑
im = load('arale_excited'); arr = np.asarray(im).copy()
rgb = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2BGR)
m = np.zeros(rgb.shape[:2], np.uint8)
cv2.ellipse(m, (113, 182), (27, 19), 0, 0, 360, 255, -1)
fill = cv2.inpaint(rgb, m, 9, cv2.INPAINT_TELEA)
fill = cv2.cvtColor(fill, cv2.COLOR_BGR2RGB)
out = arr.copy(); out[..., :3] = fill
S = 4; big = Image.fromarray(out).resize((im.width * S, im.height * S), Image.LANCZOS)
pts = [(x * S, y * S) for x, y in curve(97, 131, 177, 187)]
ImageDraw.Draw(big).line(pts, fill=(60, 28, 30, 255), width=int(2.8 * S), joint='curve')
big.resize(im.size, Image.LANCZOS).save(f'{D}/arale_talk_c.png')
# 半開：在閉嘴圖上畫小一點的開口
big = Image.open(f'{D}/arale_talk_c.png').resize((im.width * S, im.height * S), Image.LANCZOS)
d = ImageDraw.Draw(big)
poly = [(x * S, y * S) for x, y in curve(99, 129, 178, 184) + curve(129, 99, 179, 194)]
d.polygon(poly, fill=(110, 36, 44, 255))
d.ellipse([105 * S, 186 * S, 123 * S, 195 * S], fill=(236, 120, 134, 255))
mask = Image.new('L', big.size, 0); ImageDraw.Draw(mask).polygon(poly, fill=255)
base = Image.open(f'{D}/arale_talk_c.png').resize(big.size, Image.LANCZOS); base.paste(big, (0, 0), mask); big = base
ImageDraw.Draw(big).line(poly + [poly[0]], fill=(50, 24, 26, 255), width=int(2.4 * S), joint='curve')
big.resize(im.size, Image.LANCZOS).save(f'{D}/arale_talk_o1.png')

# ── 3. 輸出 WebP（檔名對應 template.html 的 FACES）
EXPORT = {
    "allan_full": "allan_full", "allan_smile": "allan_smile", "allan_talk_o1": "allan_talk1", "allan_talk_o2": "allan_talk2",
    "allan_laugh": "allan_laugh", "allan_think": "allan_think", "allan_scratch": "allan_scratch",
    "allan_surprise": "allan_surprise", "allan_point": "allan_point", "allan_wink": "allan_wink",
    "arale_full2": "arale_full", "arale_talk_c": "arale_smile", "arale_talk_o1": "arale_talk1", "arale_excited": "arale_talk2",
    "arale_laugh": "arale_laugh", "arale_think": "arale_think", "arale_surprise": "arale_surprise",
    "arale_confused": "arale_confused", "arale_sad": "arale_sad", "arale_wink": "arale_wink",
}
os.makedirs(DST, exist_ok=True)
for src, dst in EXPORT.items():
    im = Image.open(os.path.join(WORK, src + ".png"))
    if "full" in src and im.height > 560:
        im = im.resize((im.width * 560 // im.height, 560), Image.LANCZOS)
    im.save(os.path.join(DST, dst + ".webp"), "WEBP", quality=88, method=6)
print(f"{len(EXPORT)} sprites → {DST}")
