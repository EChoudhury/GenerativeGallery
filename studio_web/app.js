"use strict";

const $ = (id) => document.getElementById(id);
const templates = {
  mondrian: {
    title: "Victory Boogie Woogie", duration: 32,
    prompt: `A repeating 16-bar instrumental chamber-jazz loop in 4/4 at 120 BPM, approximately 32 seconds long, inspired by Piet Mondrian's Victory Boogie Woogie. Energetic yet spacious, combining boogie-woogie piano with interlocking minimalist patterns. Playful, alert, and rhythmically alive, with precise articulation and a human sense of swing.

A steady eight-to-the-bar left-hand piano bass establishes a clear rhythmic grid. Short syncopated right-hand figures enter, pause, and reappear with small variations. Muted trumpet contributes warm, compact accents; vibraphone adds bright, clearly defined points of sound. Keep these three instrumental colors distinct and in active conversation.

Create an asymmetrical balance of repeating cells, displaced accents, brief call-and-response phrases, and occasional cross-rhythms over the stable pulse. Alternate clusters of staccato notes with broader chords. Leave gaps between phrases so the arrangement remains open and breathable.

Use crisp attacks, short decays, lightly textured acoustic timbres, and a clear, intimate room sound. Maintain a stable tonal center with buoyant major and dominant harmonies and passing chromatic tensions. Evoke intersecting streams of city movement through musical rhythm, without literal traffic sounds.

Controlled dynamics and moderate bass, comfortable for gallery headphone listening. Instrumental, no vocals, no dramatic buildup, no heavy electronic beat.`
  },
  morandi: {
    title: "Still Life · Morandi", duration: 60,
    prompt: `An intimate, understated ambient chamber piece inspired by Giorgio Morandi's Still Life (1946), evoking quiet domestic objects, patient observation, and subtle differences within repetition.

Soft felt piano plays a small recurring motif with gently changing spacing and voicing. A muted cello sustains a calm middle-to-low register, creating a stable center beneath a few delicate upper-register piano notes. Occasional muted vibraphone tones add a faint, rounded luminosity.

A very slow, loosely felt pulse around 56 BPM, sparse musical events, generous silence, no percussion. Rounded melodic contours, softened attacks, restrained vibrato, and fine-grained bow texture. Warm, veiled timbres with gently subdued high frequencies reflect the muted ivory, grey-green, pale yellow, and dusty lilac palette.

Use a balanced arrangement with closely placed but distinct instrumental voices, suggesting separate objects sharing a small space. Repeated notes and softly undulating figures should vary almost imperceptibly. Mostly consonant, suspended harmonies with occasional mild dissonance create tenderness and a slight sense of distance, without overt melancholy.

An intimate room acoustic with soft, diffuse reverberation; quiet, even dynamics; stable instrumentation. Instrumental, no vocals, no cinematic swells, suitable for contemplative headphone listening in a gallery.`
  },
  blank: { title: "", duration: 32, prompt: "" }
};

const labels = { queued: "任务已排队", preparing: "正在截取 A/B 并拼接参考…", assembling: "正在接回参考音频并处理接缝…", submitting: "正在提交到 Stability…", generating: "音乐正在生成…", saving: "正在保存音频…", completed: "已完成", failed: "未完成" };
let loopInstructions = "";
let keyConfigured = false;
let allJobs = [];
let selectedId = null;
let activeId = null;
let submitting = false;
let timer = null;
let selectedJob = null;
let processingLoop = false;
let audioSources = [];

function stored(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } }
function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Private browsing may disable storage. */ } }
function formValues() {
  return { title: $("title").value.trim() || "Untitled study", prompt: $("prompt").value.trim(), duration: Number($("duration").value), output_format: $("format").value, loop: $("loop").checked };
}
function refreshPrompt() {
  const values = formValues();
  $("char-count").textContent = `${$("prompt").value.length} / 9000`;
  $("effective-prompt").textContent = values.prompt + (values.loop && loopInstructions ? `\n\n${loopInstructions}` : "");
  document.querySelectorAll("[data-duration]").forEach(button => button.classList.toggle("selected", Number(button.dataset.duration) === values.duration));
  save("gallery-studio-draft", values);
}
function applyForm(values) {
  $("title").value = values.title || "";
  $("prompt").value = values.prompt || "";
  $("duration").value = values.duration || 32;
  $("format").value = values.output_format || "wav";
  $("loop").checked = values.loop !== false;
  refreshPrompt();
}
function networkNote(message) {
  $("network-note").hidden = !message;
  $("network-note").textContent = message || "";
}
function updateButton() {
  const busy = submitting || Boolean(activeId);
  $("generate-button").disabled = !keyConfigured || busy;
  $("generate-button").textContent = busy ? "Generating…" : "Generate music ↗";
  $("bridge-button").disabled = !keyConfigured || busy || audioSources.length < 2;
  $("bridge-button").textContent = busy ? "Generating…" : "Generate transition ↗";
}
async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "输入无效，请检查提示词、时长和格式。";
    throw new Error(detail);
  }
  return data;
}
function renderHistory() {
  const container = $("history");
  container.replaceChildren();
  $("study-count").textContent = allJobs.length;
  if (!allJobs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "你的音乐实验，会保存在这里。";
    container.append(empty);
    return;
  }
  for (const job of allJobs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `history-item${job.id === selectedId ? " selected" : ""}`;
    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = job.title;
    const meta = document.createElement("span");
    meta.className = "history-meta";
    meta.textContent = `${job.duration}s · ${job.output_format.toUpperCase()} · ${labels[job.status] || job.status}`;
    button.append(title, meta);
    button.addEventListener("click", () => { selectJob(job); });
    container.append(button);
  }
}
function selectJob(job) {
  const changed = selectedId !== job.id;
  selectedId = job.id;
  selectedJob = job;
  const completed = job.status === "completed";
  const failed = job.status === "failed";
  $("output-empty").hidden = true;
  $("job-progress").hidden = completed || failed;
  $("job-error").hidden = !failed;
  $("result").hidden = !completed;
  $("bridge-result").hidden = !completed || job.kind !== "bridge";
  $("output-badge").textContent = completed ? "READY TO LISTEN" : failed ? "PLEASE CHECK" : "IN PROGRESS";
  $("job-error").textContent = job.error || "本次生成未完成。";
  if (!completed) $("audio").pause();
  if (completed) {
    $("result-title").textContent = job.title;
    $("result-meta").textContent = `${job.output_format.toUpperCase()} / ${job.duration} SECONDS / STABLE AUDIO 3`;
    $("result-date").textContent = new Date(job.created_at).toLocaleString("zh-CN");
    const audio = $("audio");
    if (audio.getAttribute("src") !== job.audio_url) {
      audio.pause();
      audio.src = job.audio_url;
      audio.load();
    }
    if (changed) $("preview-loop").checked = job.kind !== "bridge";
    audio.loop = $("preview-loop").checked;
    $("download").href = `${job.audio_url}?download=true`;
    if (job.kind === "bridge" && job.transition_report) {
      const report = job.transition_report;
      $("bridge-report").textContent = `完整连接段 ${report.duration.toFixed(2)} 秒 · 中间段 ${report.bridge_seconds.toFixed(2)} 秒 · 每端 ${Math.round(report.seam_overlap_seconds * 1000)}ms 淡化。${report.warnings.join(" ")}`;
      $("download-bridge").href = `${job.bridge_url}?download=true`;
    }
  } else if (!failed) {
    $("progress-title").textContent = labels[job.status] || "正在生成…";
    updateElapsed();
  }
  configureLoopEditor(job, changed);
  renderHistory();
}

function syncCrossfade(value) {
  const number = Number(value);
  $("crossfade").value = value;
  $("crossfade-seconds").value = value;
  if (!Number.isFinite(number) || number <= 0) return;
  if (selectedJob?.loop_version) {
    const previous = selectedJob.loop_version.crossfade_seconds;
    $("loop-status").textContent = Math.abs(number - previous) > 0.001
      ? "参数已修改。点击「处理并准备试听」更新循环文件，下方仍是上次处理结果。"
      : "处理完成，可以对比原始文件和循环版本。";
  }
}

function showLoopVersion(loop) {
  $("loop-result").hidden = false;
  $("loop-meta").textContent = `原始 ${loop.source_duration.toFixed(2)} 秒 → 循环 ${loop.duration.toFixed(2)} 秒 · 重叠 ${loop.crossfade_seconds.toFixed(2)} 秒 · ${loop.sample_rate} Hz · ${loop.channels} 声道 · WAV 24-bit`;
  if ($("loop-audio").getAttribute("src") !== loop.audio_url) {
    $("loop-audio").pause();
    $("loop-audio").src = loop.audio_url;
    $("loop-audio").load();
  }
  $("loop-audio").loop = $("processed-loop-toggle").checked;
  $("download-loop").href = `${loop.audio_url}?download=true`;
}

function configureLoopEditor(job, changed) {
  const ready = job.status === "completed";
  $("loop-controls").disabled = !ready || processingLoop;
  if (changed) {
    $("loop-audio").pause();
    $("loop-result").hidden = true;
    $("crossfade").max = "10";
    $("crossfade-seconds").max = "10";
    syncCrossfade(job.loop_version?.crossfade_seconds || 1);
  }
  if (job.loop_version && ready) showLoopVersion(job.loop_version);
  if (!processingLoop) {
    $("loop-status").textContent = !ready
      ? "请先等待音乐生成完成，或选择一段已完成的记录。"
      : job.loop_version ? "处理完成，可以对比原始文件和循环版本。"
      : "选择重叠时长后点击处理。只在本地运算，不会重新生成音乐。";
  }
}

$("crossfade").addEventListener("input", () => syncCrossfade($("crossfade").value));
$("crossfade-seconds").addEventListener("input", () => {
  $("crossfade").value = $("crossfade-seconds").value;
  if (selectedJob?.loop_version) $("loop-status").textContent = "参数已修改，请重新处理试听；下方仍是上次处理结果。";
});
$("audio").addEventListener("loadedmetadata", () => {
  const duration = $("audio").duration;
  if (!Number.isFinite(duration) || duration <= 0) return;
  const maximum = Math.min(10, Math.floor((duration / 2 - 0.001) * 20) / 20);
  $("crossfade").max = String(Math.max(0.05, maximum));
  $("crossfade-seconds").max = String(Math.max(0.05, maximum));
  if (maximum < 0.05) {
    $("loop-controls").disabled = true;
    $("loop-status").textContent = "这段音频过短，无法进行首尾交叉淡化。";
  } else if (Number($("crossfade-seconds").value) > maximum) syncCrossfade(maximum);
});
$("audio").addEventListener("play", () => $("loop-audio").pause());
$("loop-audio").addEventListener("play", () => $("audio").pause());
$("loop-audio").addEventListener("error", () => {
  if ($("loop-audio").getAttribute("src")) $("loop-status").textContent = "循环文件无法加载，请重新处理或下载后试听。";
});
$("processed-loop-toggle").addEventListener("change", () => {
  $("loop-audio").loop = $("processed-loop-toggle").checked;
});
$("audition-seam").addEventListener("click", async () => {
  const audio = $("loop-audio");
  if (!Number.isFinite(audio.duration)) {
    $("loop-status").textContent = "音频还在加载，请稍后再试听。";
    return;
  }
  audio.currentTime = Math.max(0, audio.duration - Math.min(3, audio.duration / 2));
  audio.loop = true;
  $("processed-loop-toggle").checked = true;
  try { await audio.play(); }
  catch { $("loop-status").textContent = "播放未启动，请点击播放器的播放按钮。"; }
});
$("process-loop").addEventListener("click", async () => {
  if (!selectedJob || selectedJob.status !== "completed" || processingLoop) return;
  const input = $("crossfade-seconds");
  if (!input.reportValidity()) return;
  const seconds = Number(input.value);
  if (!Number.isFinite(seconds) || seconds <= 0) return;
  const job = selectedJob;
  processingLoop = true;
  $("loop-controls").disabled = true;
  $("process-loop").textContent = "正在处理…";
  $("loop-status").textContent = "正在混合首尾并导出 WAV…";
  try {
    const loop = await api(`/api/jobs/${job.id}/loop`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
      body: JSON.stringify({ crossfade_seconds: seconds })
    });
    const updated = { ...job, loop_version: loop };
    upsert(updated);
    if (selectedId === job.id) {
      selectedJob = updated;
      showLoopVersion(loop);
      $("loop-status").textContent = "处理完成。点击「从接缝前开始试听」检查连接处，也可以对比原始文件。";
    }
    renderHistory();
    await loadSources();
  } catch (error) {
    if (selectedId === job.id) $("loop-status").textContent = `处理未完成：${error.message}`;
  } finally {
    processingLoop = false;
    $("loop-controls").disabled = selectedJob?.status !== "completed";
    $("process-loop").textContent = "处理并准备试听 ↻";
  }
});
function updateElapsed() {
  if (!selectedJob || ["completed", "failed"].includes(selectedJob.status)) return;
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(selectedJob.created_at)) / 1000));
  $("elapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function upsert(job) {
  allJobs = [job, ...allJobs.filter(item => item.id !== job.id)].sort((a, b) => b.created_at.localeCompare(a.created_at));
}
async function poll() {
  if (!activeId) return;
  try {
    const job = await api(`/api/jobs/${activeId}`);
    networkNote("");
    upsert(job);
    if (selectedId === job.id) selectJob(job);
    if (["completed", "failed"].includes(job.status)) {
      activeId = null;
      if (job.status === "completed") loadSources();
    }
    renderHistory();
  } catch {
    networkNote("暂时无法读取任务状态，正在重新连接。请勿重复提交生成请求。");
  }
  updateButton();
  if (activeId) timer = setTimeout(poll, 3000);
}

$("generation-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (submitting || activeId || !keyConfigured) return;
  const values = formValues();
  if (!values.prompt) { $("prompt").focus(); return; }
  if (!Number.isInteger(values.duration) || values.duration < 1 || values.duration > 380) { $("duration").reportValidity(); return; }
  submitting = true;
  updateButton();
  networkNote("");
  const pending = stored("gallery-studio-pending");
  const body = pending && JSON.stringify(pending.values) === JSON.stringify(values)
    ? { ...values, request_id: pending.id }
    : { ...values, request_id: crypto.randomUUID() };
  save("gallery-studio-pending", { values, id: body.request_id });
  try {
    const job = await api("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Studio-Request": "1" }, body: JSON.stringify(body)
    });
    save("gallery-studio-pending", null);
    upsert(job);
    activeId = ["completed", "failed"].includes(job.status) ? null : job.id;
    selectJob(job);
    if (timer) clearTimeout(timer);
    if (activeId) timer = setTimeout(poll, 1500);
  } catch (error) {
    networkNote(`${error.message} 如果提交后连接中断，请先刷新查看历史；相同输入重试会复用任务编号。`);
    // Recover a task which may have been accepted before the response was lost.
    try {
      const recovered = await api("/api/jobs");
      allJobs = recovered;
      const running = recovered.find(job => !["completed", "failed"].includes(job.status));
      if (running) { activeId = running.id; selectJob(running); timer = setTimeout(poll, 3000); }
      renderHistory();
    } catch { /* Keep the original error and the pending id for a safe retry. */ }
  } finally { submitting = false; updateButton(); }
});

document.querySelectorAll("[data-template]").forEach(button => button.addEventListener("click", () => {
  applyForm(templates[button.dataset.template]);
  $("prompt").focus();
}));
document.querySelectorAll("[data-duration]").forEach(button => button.addEventListener("click", () => {
  $("duration").value = button.dataset.duration;
  refreshPrompt();
}));
for (const id of ["title", "prompt", "duration", "format", "loop"]) $(id).addEventListener("input", refreshPrompt);
$("clear-prompt").addEventListener("click", () => { $("prompt").value = ""; refreshPrompt(); $("prompt").focus(); });
$("preview-loop").addEventListener("change", () => { $("audio").loop = $("preview-loop").checked; });
$("audio").addEventListener("error", () => { if ($("audio").getAttribute("src")) networkNote("音频无法加载或浏览器不支持该文件，请尝试下载后播放。"); });
$("reuse").addEventListener("click", () => {
  if (selectedJob?.kind === "bridge") {
    $("source-a").value = selectedJob.source_a;
    $("source-b").value = selectedJob.source_b;
    $("bridge-context").value = selectedJob.context_seconds;
    $("bridge-length").value = selectedJob.bridge_seconds;
    $("bridge-direction").value = selectedJob.prompt;
    updateBridgeTimeline();
    $("bridge-form").scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (selectedJob) { applyForm(selectedJob); $("prompt").focus(); $("generation-form").scrollIntoView({ behavior: "smooth", block: "start" }); }
});

function bridgeValues() {
  return { source_a: $("source-a").value, source_b: $("source-b").value,
    context_seconds: Number($("bridge-context").value), bridge_seconds: Number($("bridge-length").value),
    prompt: $("bridge-direction").value.trim() };
}
function updateBridgeTimeline() {
  const value = bridgeValues();
  const a = audioSources.find(source => source.id === value.source_a);
  const b = audioSources.find(source => source.id === value.source_b);
  const left = Math.min(a?.duration || value.context_seconds, value.context_seconds);
  const right = Math.min(b?.duration || value.context_seconds, value.context_seconds);
  $("bridge-timeline").textContent = `A 最后 ${left.toFixed(1)} 秒 → 新音乐 ${value.bridge_seconds} 秒 → B 最前 ${right.toFixed(1)} 秒 · 合计 ${(left + right + value.bridge_seconds).toFixed(1)} 秒`;
  save("gallery-studio-bridge", value);
}
async function loadSources() {
  try {
    const previous = $("source-a").value ? bridgeValues() : stored("gallery-studio-bridge");
    audioSources = await api("/api/sources");
    for (const [id, preferred] of [["source-a", "audio:song_a.mp3"], ["source-b", "audio:song_b.mp3"]]) {
      const select = $(id);
      select.replaceChildren();
      for (const source of audioSources) {
        const option = document.createElement("option");
        option.value = source.id;
        option.textContent = `${source.title} · ${source.duration.toFixed(1)}s · ${source.group}`;
        select.append(option);
      }
      const old = previous?.[id.replace("-", "_")];
      if (audioSources.some(source => source.id === old)) select.value = old;
      else if (audioSources.some(source => source.id === preferred)) select.value = preferred;
      else select.selectedIndex = id === "source-a" ? 0 : Math.min(1, audioSources.length - 1);
    }
    if (previous) {
      $("bridge-context").value = previous.context_seconds || 8;
      $("bridge-length").value = previous.bridge_seconds || 12;
      $("bridge-direction").value = previous.prompt || "";
    }
    $("bridge-note").textContent = audioSources.length >= 2 ? "默认取 A 的结尾和 B 的开头。原文件不会修改。" : "请将至少两段 WAV/MP3 放入项目 audio/ 或 assets/ 目录，或先生成音乐，然后刷新素材。";
    updateBridgeTimeline();
    updateButton();
  } catch { $("bridge-note").textContent = "素材列表加载失败，请点击刷新素材重试。"; }
}
async function useAsSource(side, processed) {
  const job = selectedJob;
  if (!job || job.status !== "completed") return;
  await loadSources();
  const filename = processed
    ? job.loop_version?.filename || `${job.id}-loop-${job.loop_version?.overlap_frames}.wav`
    : job.filename || `${job.id}.${job.output_format}`;
  const sourceId = processed && job.loop_version?.source_id || `generated:${filename}`;
  if (!audioSources.some(source => source.id === sourceId)) {
    $("bridge-note").textContent = "找不到这段素材，请刷新后重试。";
    return;
  }
  $(`source-${side}`).value = sourceId;
  updateBridgeTimeline();
  $("bridge-note").textContent = `已将${processed ? "循环版本" : "原始文件"}设为 ${side.toUpperCase()}，选择另一端后即可生成过渡。`;
  $("bridge-heading").scrollIntoView({behavior:"smooth", block:"start"});
}
for (const side of ["a", "b"]) {
  $(`original-to-${side}`).addEventListener("click", () => useAsSource(side, false));
  $(`loop-to-${side}`).addEventListener("click", () => useAsSource(side, true));
}
$("refresh-sources").addEventListener("click", loadSources);
for (const id of ["source-a", "source-b", "bridge-context", "bridge-length", "bridge-direction"]) $(id).addEventListener("input", updateBridgeTimeline);
$("bridge-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!keyConfigured || submitting || activeId) return;
  const values = bridgeValues();
  if (values.source_a === values.source_b) { $("bridge-note").textContent = "请选择不同的 A 和 B。"; return; }
  submitting = true;
  updateButton();
  const pending = stored("gallery-studio-bridge-pending");
  const requestId = pending && JSON.stringify(pending.values) === JSON.stringify(values) ? pending.id : crypto.randomUUID();
  save("gallery-studio-bridge-pending", { id: requestId, values });
  try {
    const job = await api("/api/bridge", {method:"POST",
      headers:{"Content-Type":"application/json", "X-Studio-Request":"1"},
      body:JSON.stringify({...values, request_id:requestId})});
    save("gallery-studio-bridge-pending", null);
    upsert(job);
    activeId = ["completed", "failed"].includes(job.status) ? null : job.id;
    selectJob(job);
    $("bridge-note").textContent = "自动流程已启动。可在上方试听区查看状态；请勿重复提交。";
    $("job-progress").scrollIntoView({behavior:"smooth", block:"center"});
    if (timer) clearTimeout(timer);
    if (activeId) timer = setTimeout(poll, 1500);
  } catch (error) {
    $("bridge-note").textContent = `${error.message} 若提交后连接中断，请先刷新查看历史；相同输入重试会复用任务编号。`;
    try {
      allJobs = await api("/api/jobs");
      const running = allJobs.find(job => !["completed", "failed"].includes(job.status));
      if (running) {activeId = running.id; selectJob(running); timer = setTimeout(poll, 3000);}
      renderHistory();
    } catch { /* Retain the pending id rather than automatically repeating a paid request. */ }
  } finally {submitting = false; updateButton();}
});

async function initialize() {
  updateButton();
  applyForm(stored("gallery-studio-draft") || templates.mondrian);
  try {
    const [config, history] = await Promise.all([api("/api/config"), api("/api/jobs")]);
    keyConfigured = config.key_configured;
    loopInstructions = config.loop_instructions;
    $("key-status").textContent = keyConfigured ? "Stability API key 已配置" : "需要配置 API key";
    $("key-status").className = `key-status ${keyConfigured ? "connected" : "missing"}`;
    $("setup-note").hidden = keyConfigured;
    allJobs = history;
    const running = history.find(job => !["completed", "failed"].includes(job.status));
    if (running) { activeId = running.id; selectJob(running); timer = setTimeout(poll, 1500); }
    else if (history.length) selectJob(history[0]);
    renderHistory();
    refreshPrompt();
    updateButton();
    await loadSources();
  } catch {
    $("key-status").textContent = "本地服务未连接";
    networkNote("无法连接本地服务，请重新打开「打开音乐工作室.command」后刷新页面。");
  }
}
setInterval(updateElapsed, 1000);
initialize();
