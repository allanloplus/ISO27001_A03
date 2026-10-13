// 將 index.html 的動畫簡報錄成 MP4（含講師與助教旁白、章節標記）。
// 用法：node tools/record_video.cjs [輸出檔]   需要 playwright 與 ffmpeg。
//
// Playwright 錄下的畫面時間軸會比實際時間長（主機忙碌時更明顯），若直接把旁白依實際時間放入，
// 聲音會越來越超前畫面。因此錄影模式會在畫面右下角顯示「段落編號碼」，錄完後讀出每段在影片中
// 出現的時間，逐段把畫面校正回實際時間，再抹除編號碼並合成旁白。
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync, spawnSync } = require("child_process");
let pw;
try { pw = require("playwright"); } catch { pw = require("/opt/node-tools/node_modules/playwright"); }

const ROOT = path.resolve(__dirname, "..");
const OUT = path.resolve(process.argv[2] || path.join(ROOT, "video", "ISO27001_資訊保護生命週期.mp4"));
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "rec-"));
const FPS = 20;
const CODE = { x: 1198, y: 712, step: 10, bits: 8 };   // 與 template.html 的 #reccode 位置一致
const ff = (args) => execFileSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", ...args], { stdio: "inherit" });

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
  await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0));
  await page.waitForTimeout(2500);
  // REC_SLIDES=n 只錄前 n 頁（測試用）
  if (process.env.REC_SLIDES) await page.evaluate((n) => { DATA.slides.length = n; }, +process.env.REC_SLIDES);
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

  // 1. 讀出每一格畫面的段落編號（固定 FPS 取樣）
  const W = CODE.step * CODE.bits;
  const raw = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-i", webm,
    "-vf", `fps=${FPS},scale=1280:720,crop=${W}:1:${CODE.x - CODE.step / 2}:${CODE.y},format=gray`,
    "-f", "rawvideo", "-"], { maxBuffer: 1 << 30 }).stdout;
  const frames = raw.length / W;
  const codes = [];
  for (let f = 0; f < frames; f++) {
    let n = 0;
    for (let b = 0; b < CODE.bits; b++) if (raw[f * W + b * CODE.step + CODE.step / 2] > 128) n |= 1 << b;
    codes.push(n);
  }
  // 錨點：影片時間 v → 實際時間 w（以開始講課為 0）；依序往後找，避開開頭的空白頁
  const anchors = [];
  let cur = codes.indexOf(1);
  log.forEach((e, i) => {
    const code = e.audio ? i + 1 : 255;
    const f = cur < 0 ? -1 : codes.indexOf(code, cur);
    if (f >= 0) { anchors.push({ v: f / FPS, w: (e.t - t0) / 1000 }); cur = f; }
  });
  if (anchors.length < log.length * 0.9) throw new Error(`only ${anchors.length}/${log.length} segment codes found`);
  const last = anchors[anchors.length - 1];
  const vEnd = frames / FPS, wEnd = last.w + (vEnd - last.v);
  const lead = Math.min(1.2, anchors[0].v);          // 開始講課前保留的一小段畫面
  const pts = [{ v: anchors[0].v - lead, w: anchors[0].w - lead }, ...anchors, { v: vEnd, w: wEnd }];
  const stretch = (last.v - anchors[0].v) / (last.w - anchors[0].w);
  console.log(`${anchors.length}/${log.length} anchors; raw video runs ×${stretch.toFixed(3)} of real time — retiming`);

  // 2. 逐段重新計時（每段格數依累計時間計算，避免誤差累積），並抹除編號碼
  const base = pts[0].w;
  const list = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i], b = pts[i + 1];
    const n = Math.round((b.w - base) * FPS) - Math.round((a.w - base) * FPS);
    if (n <= 0 || b.v <= a.v) continue;
    const piece = path.join(TMP, `p${String(i).padStart(4, "0")}.mp4`);
    const k = (n / FPS) / (b.v - a.v);
    ff(["-ss", a.v.toFixed(3), "-t", (b.v - a.v + 0.5).toFixed(3), "-i", webm,
      "-vf", `scale=1280:720,setsar=1,setpts=(PTS-STARTPTS)*${k.toFixed(6)},fps=${FPS},delogo=x=${CODE.x - 10}:y=${CODE.y - 8}:w=${W + 8}:h=15`,
      "-frames:v", String(n), "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-tune", "animation",
      "-pix_fmt", "yuv420p", piece]);
    list.push(`file '${piece}'`);
  }
  fs.writeFileSync(path.join(TMP, "list.txt"), list.join("\n"));
  const silent = path.join(TMP, "video.mp4");
  ff(["-f", "concat", "-safe", "0", "-i", path.join(TMP, "list.txt"), "-c", "copy", silent]);

  // 3. 旁白依實際時間放入
  const inputs = [], filters = [];
  log.filter((e) => e.audio).forEach((e, i) => {
    inputs.push("-i", path.join(ROOT, e.audio));
    const ms = Math.max(0, Math.round(((e.t - t0) / 1000 - base) * 1000));
    filters.push(`[${i + 1}:a]adelay=${ms}|${ms}[a${i}]`);
  });
  const nA = filters.length;
  const mix = Array.from({ length: nA }, (_, i) => `[a${i}]`).join("") + `amix=inputs=${nA}:normalize=0:dropout_transition=0[aout]`;
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  ff(["-i", silent, ...inputs, "-filter_complex", filters.join(";") + ";" + mix,
    "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k", "-ac", "1",
    "-movflags", "+faststart", OUT]);
  console.log("saved", OUT);

  // 4. 章節：每頁第一段旁白的時間（換頁動畫約提前 0.6 秒）
  const chapters = [];
  log.forEach((e) => {
    if (!e.audio) return;
    const si = +path.basename(e.audio).slice(1, 3) - 1;
    if (chapters.some((c) => c.si === si)) return;
    const { label, chapter } = slides[si];
    chapters.push({ si, start: si ? Math.max(0, (e.t - t0) / 1000 - base - 0.6) : 0, group: chapter,
      title: label.startsWith(chapter) ? label : `${chapter}｜${label}` });
  });
  fs.writeFileSync(path.join(path.dirname(OUT), "chapters.json"),
    JSON.stringify(chapters.map(({ si, ...c }) => ({ ...c, start: +c.start.toFixed(2) })), null, 1));
  // 對位紀錄，供日後檢查
  fs.writeFileSync(path.join(TMP, "..", path.basename(TMP) + "-anchors.json"), JSON.stringify({ base, anchors }));
  execFileSync("python3", [path.join(__dirname, "add_chapters.py"), OUT], { stdio: "inherit" });
  fs.rmSync(TMP, { recursive: true, force: true });
})().catch((e) => { console.error(e); process.exit(1); });
