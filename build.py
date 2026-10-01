#!/usr/bin/env python3
"""產生旁白語音（台灣男聲）並組出 index.html。

用法：
    pip install edge-tts
    python3 build.py            # 只重新產生有變動的語音
    python3 build.py --force    # 全部重新產生
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys

import certifi

# 在有 TLS 代理的環境中，使用代理的 CA bundle
_CA = os.environ.get("SSL_CERT_FILE")
if _CA and os.path.exists(_CA):
    certifi.where = lambda: _CA

import edge_tts  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(ROOT, "audio")
DIGITS = "零一二三四五六七八九"

SPOKEN = [
    (r"ISO 27001:2022", "ISO 二七零零一，二零二二年版"),
    (r"27701", "二七七零一"),
    (r"2022年", "二零二二年"),
    (r"PII", "P I I"),
    (r"BYOD", "B Y O D"),
    (r"SFTP", "S F T P"),
]


def spoken(text: str) -> str:
    """把顯示文字轉成較好念的旁白文字（控制措施編號念成「五點一二」）。"""
    for pat, rep in SPOKEN:
        text = re.sub(pat, rep, text)
    return re.sub(
        r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d.])",
        lambda m: "".join(DIGITS[int(c)] for c in m.group(1)) + "點"
        + "".join(DIGITS[int(c)] for c in m.group(2)),
        text,
    )


def sentences(text: str):
    return [s for s in re.findall(r"[^。！？]+[。！？]?", text) if s.strip()]


def duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


async def synth(text, voice, rate, path):
    comm = edge_tts.Communicate(text, voice, rate=rate)
    marks = []
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                marks.append(chunk["offset"] / 1e7)
    return marks


async def main(force: bool):
    with open(os.path.join(ROOT, "content.json"), encoding="utf-8") as f:
        data = json.load(f)
    meta = data["meta"]
    os.makedirs(AUDIO_DIR, exist_ok=True)
    cache_path = os.path.join(AUDIO_DIR, "cache.json")
    cache = {}
    if os.path.exists(cache_path) and not force:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

    used = set()
    for si, slide in enumerate(data["slides"]):
        for gi, seg in enumerate(slide["segs"]):
            name = f"s{si + 1:02d}_{gi + 1:02d}.mp3"
            path = os.path.join(AUDIO_DIR, name)
            used.add(name)
            say = spoken(seg["say"])
            key = hashlib.sha1(f"{meta['voice']}|{meta['rate']}|{say}".encode()).hexdigest()
            hit = cache.get(name)
            if not (hit and hit["key"] == key and os.path.exists(path)):
                print("TTS", name, seg["say"][:24], flush=True)
                for attempt in range(4):
                    try:
                        marks = await synth(say, meta["voice"], meta["rate"], path)
                        break
                    except Exception as e:  # 網路不穩時重試
                        print("  retry", attempt + 1, e)
                        await asyncio.sleep(2 ** attempt)
                else:
                    sys.exit(f"TTS failed: {name}")
                hit = {"key": key, "marks": marks, "dur": duration(path)}
                cache[name] = hit
            disp = sentences(seg["say"])
            marks = hit["marks"]
            if len(marks) != len(disp):  # 斷句數不一致時，以字數比例估算
                total, acc, marks = sum(len(s) for s in disp), 0, []
                for s in disp:
                    marks.append(hit["dur"] * acc / total)
                    acc += len(s)
            seg["audio"] = f"audio/{name}"
            seg["dur"] = round(hit["dur"], 3)
            seg["cues"] = [[round(t, 3), s] for t, s in zip(marks, disp)]

    for fn in os.listdir(AUDIO_DIR):
        if fn.endswith(".mp3") and fn not in used:
            os.remove(os.path.join(AUDIO_DIR, fn))
            cache.pop(fn, None)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)

    with open(os.path.join(ROOT, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    body = tpl.replace("/*__DATA__*/null", payload)
    html = ('<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + body + "\n</html>\n")
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    total = sum(s["dur"] for sl in data["slides"] for s in sl["segs"])
    print(f"index.html built · {len(used)} clips · {total / 60:.1f} min narration")


if __name__ == "__main__":
    asyncio.run(main("--force" in sys.argv))
