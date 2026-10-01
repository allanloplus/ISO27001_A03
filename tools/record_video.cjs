// 將 index.html 的動畫簡報錄成 MP4（含台灣男聲旁白）。
// 用法：node tools/record_video.cjs [輸出檔]   需要 playwright 與 ffmpeg。
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
let pw;
try { pw = require("playwright"); } catch { pw = require("/opt/node-tools/node_modules/playwright"); }

const ROOT = path.resolve(__dirname, "..");
const OUT = path.resolve(process.argv[2] || path.join(ROOT, "video", "ISO27001_資訊保護生命週期.mp4"));
const TMP = fs.mkdtempSync(path.join(require("os").tmpdir(), "rec-"));

(async () => {
  const browser = await pw.chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: TMP, size: { width: 1280, height: 720 } },
  });
  const page = await ctx.newPage();
  // 字型經由 Node 取得（適用於有 TLS 代理的環境）
  await page.route(/fonts\.(googleapis|gstatic)\.com/, async (r) => {
    try { await r.fulfill({ response: await r.fetch() }); } catch { await r.abort(); }
  });
  await page.goto("file://" + path.join(ROOT, "index.html") + "#record");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.__startRecord());
  const t0 = await page.evaluate(() => window.__t0);
  const total = await page.evaluate(() => DATA.slides.reduce((a, s) => a + s.segs.reduce((b, g) => b + g.dur, 0), 0));
  console.log(`recording ~${(total / 60).toFixed(1)} min of narration…`);
  await page.waitForFunction(() => window.__done === true, null, { timeout: 0, polling: 1000 });
  const log = await page.evaluate(() => window.__log);
  const slides = await page.evaluate(() => DATA.slides.map((s) => ({ label: s.label, chapter: s.chapter })));
  const video = page.video();
  await ctx.close();
  await browser.close();
  const webm = await video.path();

  // 以黑幕結束的時間點校正影片與旁白的時間軸
  let blackEnd = 0;
  try {
    const err = execFileSync("sh", ["-c", `ffmpeg -hide_banner -i "${webm}" -vf blackdetect=d=0.3:pix_th=0.05 -an -f null - 2>&1 | grep -o 'black_end:[0-9.]*' | head -1`]).toString();
    blackEnd = parseFloat(err.split(":")[1]) || 0;
  } catch {}
  console.log("curtain lifted at", blackEnd, "s in raw video");

  const inputs = [], filters = [];
  log.forEach((e, i) => {
    inputs.push("-i", path.join(ROOT, e.audio));
    const ms = Math.max(0, Math.round(e.t - t0));
    filters.push(`[${i + 1}:a]adelay=${ms}|${ms}[a${i}]`);
  });
  const mix = log.map((_, i) => `[a${i}]`).join("") + `amix=inputs=${log.length}:normalize=0:dropout_transition=0[aout]`;
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  execFileSync("ffmpeg", [
    "-y", "-hide_banner", "-loglevel", "error",
    "-ss", String(blackEnd), "-i", webm, ...inputs,
    "-filter_complex", filters.join(";") + ";" + mix,
    "-map", "0:v", "-map", "[aout]",
    "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-tune", "animation", "-pix_fmt", "yuv420p", "-r", "20",
    "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", OUT,
  ], { stdio: "inherit" });
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log("saved", OUT);

  // 每頁第一段旁白的時間（換頁動畫約提前 0.6 秒）→ 章節
  const chapters = [];
  log.forEach((e) => {
    const si = +path.basename(e.audio).slice(1, 3) - 1;
    if (chapters.some((c) => c.si === si)) return;
    const { label, chapter } = slides[si];
    chapters.push({ si, start: si ? Math.max(0, (e.t - t0) / 1000 - 0.6) : 0, group: chapter,
      title: label.startsWith(chapter) ? label : `${chapter}｜${label}` });
  });
  fs.writeFileSync(path.join(path.dirname(OUT), "chapters.json"),
    JSON.stringify(chapters.map(({ si, ...c }) => ({ ...c, start: +c.start.toFixed(2) })), null, 1));
  execFileSync("python3", [path.join(__dirname, "add_chapters.py"), OUT], { stdio: "inherit" });
})().catch((e) => { console.error(e); process.exit(1); });
