#!/usr/bin/env python3
"""把 video/chapters.json 的章節寫入 MP4（不重新編碼），並輸出 YouTube 章節時間表。

用法：python3 tools/add_chapters.py [影片路徑]
chapters.json 格式：[{"start": 秒數, "title": "章節名稱", "group": "大章節"}, ...]
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "video", "ISO27001_資訊保護生命週期.mp4")
CH_JSON = os.path.join(os.path.dirname(VIDEO), "chapters.json")


def hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def esc(s: str) -> str:
    return "".join("\\" + c if c in "=;#\\\n" else c for c in s)


def main():
    chapters = json.load(open(CH_JSON, encoding="utf-8"))
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", VIDEO],
        capture_output=True, text=True, check=True).stdout)

    meta = [";FFMETADATA1", "title=ISO 27001:2022 資訊保護生命週期", "artist=Allan Lo", ""]
    for i, c in enumerate(chapters):
        end = chapters[i + 1]["start"] if i + 1 < len(chapters) else dur
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}",
                 f"END={int(end * 1000)}", f"title={esc(c['title'])}", ""]
    with tempfile.TemporaryDirectory() as tmp:
        mf = os.path.join(tmp, "meta.txt")
        out = os.path.join(tmp, "out.mp4")
        open(mf, "w", encoding="utf-8").write("\n".join(meta))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", VIDEO, "-i", mf, "-map", "0",
                        "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
                        "-movflags", "+faststart", out], check=True)
        os.replace(out, VIDEO)

    # YouTube 章節：第一個必須是 00:00，以大章節為單位
    lines, seen = [], set()
    for c in chapters:
        g = c.get("group", c["title"])
        if g not in seen:
            seen.add(g)
            lines.append(f"{hms(c['start'])} {g}")
    txt = os.path.join(os.path.dirname(VIDEO), "youtube_chapters.txt")
    open(txt, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{len(chapters)} chapters written to {os.path.basename(VIDEO)}; YouTube list → {txt}")


if __name__ == "__main__":
    main()
