"""Local prompt-to-music studio. Run with .venv/bin/python studio.py."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import re
import shutil
from pathlib import Path
import threading
import uuid
import webbrowser

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
import requests

from generate_assets import StabilityAudioClient
from loop_processing import export_loop
from transition_builder import build_transition, DEFAULT_PROMPT, BridgeError
import soundfile as sf

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "assets" / "generated"
WEB_DIR = ROOT / "studio_web"
LOOP_INSTRUCTIONS = (
    "Design this as a repeating musical cycle with consistent instrumentation, "
    "energy, perceived loudness, and tonal center. Use recurring motifs with subtle "
    "internal variation. Begin directly in the established texture or groove. "
    "Let the final phrase lead naturally back into the opening phrase. "
    "No intro, outro, fade-in, fade-out, dramatic buildup, final resolving chord, "
    "or trailing silence."
)

app = FastAPI(title="Living Gallery · Sound Studio", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
jobs = {}
job_lock = threading.Lock()
loop_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-generation")
TERMINAL = {"completed", "failed"}


def api_key():
    """Read credentials locally, including edits made after the app started."""
    return (os.environ.get("STABILITY_API_KEY") or
            dotenv_values(ROOT / ".env").get("STABILITY_API_KEY") or "").strip()


class Generation(BaseModel):
    request_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=9000)
    title: str = Field(default="Untitled study", max_length=100)
    duration: int = Field(default=32, ge=1, le=380, strict=True)
    output_format: str = "wav"
    loop: bool = True

    @field_validator("prompt", "title")
    @classmethod
    def strip_text(cls, value):
        if not value.strip():
            raise ValueError("Please enter text.")
        return value.strip()

    @field_validator("output_format")
    @classmethod
    def valid_format(cls, value):
        if value not in {"wav", "mp3"}:
            raise ValueError("Choose WAV or MP3.")
        return value


class LoopProcessing(BaseModel):
    crossfade_seconds: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)


class BridgeGeneration(BaseModel):
    request_id: uuid.UUID
    source_a: str = Field(min_length=1, max_length=300)
    source_b: str = Field(min_length=1, max_length=300)
    context_seconds: float = Field(default=8, ge=1, le=20, allow_inf_nan=False)
    bridge_seconds: float = Field(default=12, ge=1, le=120, allow_inf_nan=False)
    prompt: str = Field(default="", max_length=8000)


def safe_title(title):
    """Keep artwork names readable while excluding filesystem separators."""
    return re.sub(r'[^\w .-]+', '-', title, flags=re.UNICODE).strip(' .-')[:80] or "Untitled study"


def recording_filename(title, extension):
    """Reserve an artwork-scoped number; call while holding job_lock."""
    stem = safe_title(title)
    number = 1
    reserved = {f"{recording_label(job)}.{extension}" for job in jobs.values()}
    while True:
        name = f"{stem}-{number:03d}.{extension}"
        if name not in reserved and not (OUTPUT_DIR / name).exists():
            return name
        number += 1


def recording_path(job):
    return OUTPUT_DIR / job.get("filename", f"{job['id']}.{job['output_format']}")


def recording_label(job):
    if job.get("filename"):
        return Path(job["filename"]).stem
    # Give historical downloads readable, stable names without moving old files.
    siblings = sorted((j for j in jobs.values() if safe_title(j["title"]) == safe_title(job["title"])),
                      key=lambda j: (j["created_at"], j["id"]))
    number = next((i + 1 for i, j in enumerate(siblings) if j["id"] == job["id"]), 1)
    return f"{safe_title(job['title'])}-{number:03d}"


def loop_path(job, frames):
    named = OUTPUT_DIR / f"{recording_label(job)}-loop-{frames}.wav"
    return named if named.is_file() else OUTPUT_DIR / f"{job['id']}-loop-{frames}.wav"


def source_files():
    """Allow only audio files in the three known library directories."""
    roots = {"audio": ROOT / "audio", "assets": ROOT / "assets", "generated": OUTPUT_DIR}
    return {f"{group}:{path.name}": path for group, directory in roots.items()
            if directory.is_dir() for path in sorted(directory.iterdir())
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".wav", ".mp3"}}


def generate_bridge(job_id, key, source_a, source_b):
    with job_lock:
        job = dict(jobs[job_id])
    client = None
    try:
        client = StabilityAudioClient(api_key=key, poll_interval=3)
        directory = OUTPUT_DIR / f"{job_id}-transition"
        result = build_transition(
            source_a, source_b, directory, job["context_seconds"], job["bridge_seconds"],
            prompt=job["prompt"], client=client,
            on_status=lambda state: update_job(job_id, status=state),
        )
        shutil.copyfile(directory / "transition.wav", recording_path(job))
        update_job(job_id, status="completed", audio_url=f"/api/audio/{job_id}",
                   duration=result["report"]["duration"], transition_report=result["report"],
                   bridge_url=f"/api/audio/{job_id}/bridge",
                   completed_at=datetime.now(timezone.utc).isoformat())
    except BridgeError as exc:
        update_job(job_id, status="failed", error=str(exc))
    except Exception as exc:
        update_job(job_id, status="failed", error=friendly_error(exc))
    finally:
        if client is not None:
            client.session.close()


def persist(job):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{job['id']}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def update_job(job_id, **changes):
    with job_lock:
        jobs[job_id].update(changes)
        persist(jobs[job_id])


def restore_history():
    if not OUTPUT_DIR.exists():
        return
    for path in OUTPUT_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if str(uuid.UUID(job["id"])) != path.stem:
                continue
            if job["status"] not in TERMINAL:
                job.update(status="failed", error="服务已重启；上次任务结果未确认，请先检查 Stability 账户记录再重新生成。")
            jobs[job["id"]] = job
        except (ValueError, KeyError, TypeError, OSError):
            continue


restore_history()


def friendly_error(exc):
    # Never forward provider response bodies or credentials to the browser.
    message = str(exc)
    if "(401)" in message:
        return "API key 无效，请检查项目 .env 中的 STABILITY_API_KEY。"
    if "(402)" in message:
        return "Stability 账户余额不足，请充值后再试。"
    if "(403)" in message:
        return "Stability 拒绝了这次请求，请调整提示词或检查账户权限。"
    if "(429)" in message:
        return "请求过于频繁，请稍后再试。"
    if isinstance(exc, (TimeoutError, requests.Timeout)):
        return "等待结果超时；任务可能仍在 Stability 运行，请先检查账户记录，避免重复付费。"
    if isinstance(exc, requests.RequestException):
        return "连接 Stability 失败。若请求已提交，任务可能仍在运行；重新生成前请先检查账户记录。"
    return "本次生成未完成。请检查网络、API 账户及提示词后再试。"


def generate(job_id, key):
    with job_lock:
        job = dict(jobs[job_id])
    client = None
    try:
        update_job(job_id, status="submitting")
        client = StabilityAudioClient(api_key=key, poll_interval=3)
        destination = recording_path(job)
        client.generate(
            job["effective_prompt"], output=destination, duration=job["duration"],
            on_status=lambda state: update_job(job_id, status=state),
        )
        update_job(job_id, status="completed", audio_url=f"/api/audio/{job_id}",
                   completed_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        update_job(job_id, status="failed", error=friendly_error(exc))
    finally:
        if client is not None:
            client.session.close()


@app.middleware("http")
async def local_requests_only(request: Request, call_next):
    if request.method == "POST":
        # A different website must not be able to spend this local API key.
        from fastapi.responses import JSONResponse
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin != expected or request.headers.get("x-studio-request") != "1":
            return JSONResponse({"detail": "请从本地工作室页面提交请求。"}, status_code=403)
    return await call_next(request)


@app.get("/")
def home():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def config():
    return {"key_configured": bool(api_key()), "max_duration": 380,
            "loop_instructions": LOOP_INSTRUCTIONS}


@app.get("/api/jobs")
def history():
    with job_lock:
        return sorted((dict(job) for job in jobs.values()),
                      key=lambda job: job["created_at"], reverse=True)


@app.get("/api/sources")
def sources():
    with job_lock:
        completed = [dict(job) for job in jobs.values() if job["status"] == "completed"]
        labels = {}
        for job in completed:
            label = recording_label(job)
            labels[recording_path(job).name] = (label + " · Original", "original")
            for path in OUTPUT_DIR.glob(f"{job['id']}-loop-*.wav"):
                frames = path.stem.rsplit("-", 1)[-1]
                if frames.isdigit():
                    try:
                        rate = sf.info(path).samplerate
                    except (OSError, RuntimeError):
                        continue
                    labels[path.name] = (f"{label} · Loop · {int(frames)/rate:g}s crossfade", "loop")
            for path in OUTPUT_DIR.glob(f"{label}-loop-*.wav"):
                frames = path.stem.rsplit("-", 1)[-1]
                if frames.isdigit():
                    try:
                        rate = sf.info(path).samplerate
                    except (OSError, RuntimeError):
                        continue
                    labels[path.name] = (f"{label} · Loop · {int(frames)/rate:g}s crossfade", "loop")
    result = []
    for source_id, path in source_files().items():
        try:
            info = sf.info(path)
        except (OSError, RuntimeError):
            continue
        label, variant = labels.get(path.name, (path.stem, "file"))
        result.append({"id": source_id, "title": label, "variant": variant,
                       "group": source_id.split(":", 1)[0], "duration": info.duration})
    return result


@app.post("/api/bridge", status_code=202)
def create_bridge(body: BridgeGeneration):
    key = api_key()
    if not key:
        raise HTTPException(503, "请先配置 STABILITY_API_KEY。")
    job_id = str(body.request_id)
    with job_lock:
        if job_id in jobs:
            return dict(jobs[job_id])
    available = source_files()
    if body.source_a not in available or body.source_b not in available:
        raise HTTPException(422, "找不到选取的音频，请刷新素材列表后重选。")
    if body.source_a == body.source_b:
        raise HTTPException(422, "请选择不同的 A、B 音频。")
    a, b = available[body.source_a], available[body.source_b]
    source_labels = {item["id"]: item["title"] for item in sources()}
    title = f"{source_labels.get(body.source_a, a.stem).split(' · ')[0]} to {source_labels.get(body.source_b, b.stem).split(' · ')[0]}"
    job = {
        "id": job_id, "kind": "bridge", "title": title,
        "source_a": body.source_a, "source_b": body.source_b,
        "context_seconds": body.context_seconds, "bridge_seconds": body.bridge_seconds,
        "prompt": body.prompt.strip(), "effective_prompt": DEFAULT_PROMPT + (
            "\n\nAdditional musical direction: " + body.prompt.strip() if body.prompt.strip() else ""),
        "duration": 2 * body.context_seconds + body.bridge_seconds, "output_format": "wav",
        "loop": False, "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(),
        "audio_url": None, "error": None,
    }
    with job_lock:
        if job_id in jobs:
            return dict(jobs[job_id])
        if any(item["status"] not in TERMINAL for item in jobs.values()):
            raise HTTPException(409, "已有生成任务在运行，请等待完成后再提交。")
        job["filename"] = recording_filename(job["title"], job["output_format"])
        persist(job)
        jobs[job_id] = job
        executor.submit(generate_bridge, job_id, key, a, b)
        return dict(job)


@app.post("/api/generate", status_code=202)
def create_generation(body: Generation):
    key = api_key()
    if not key:
        raise HTTPException(503, "请先在项目 .env 中填写 STABILITY_API_KEY，保存后刷新页面。")
    job_id = str(body.request_id)
    with job_lock:
        if job_id in jobs:
            return dict(jobs[job_id])
        if any(job["status"] not in TERMINAL for job in jobs.values()):
            raise HTTPException(409, "已有任务正在生成，请等待完成后再提交。")
        effective = body.prompt
        if body.loop:
            effective += "\n\n" + LOOP_INSTRUCTIONS
        job = {
            "id": job_id, "title": body.title, "prompt": body.prompt,
            "effective_prompt": effective, "duration": body.duration,
            "output_format": body.output_format, "loop": body.loop,
            "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(),
            "audio_url": None, "error": None,
        }
        job["filename"] = recording_filename(job["title"], job["output_format"])
        persist(job)
        jobs[job_id] = job
        executor.submit(generate, job_id, key)
        return dict(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: uuid.UUID):
    with job_lock:
        job = jobs.get(str(job_id))
        if job is None:
            raise HTTPException(404, "找不到该任务。")
        return dict(job)


@app.get("/api/audio/{job_id}")
def audio(job_id: uuid.UUID, download: bool = False):
    with job_lock:
        job = dict(jobs.get(str(job_id), {}))
    if job.get("status") != "completed":
        raise HTTPException(404, "音频尚未生成。")
    extension = job["output_format"]
    path = recording_path(job)
    if not path.is_file():
        raise HTTPException(404, "音频文件不存在。")
    return FileResponse(path, media_type="audio/wav" if extension == "wav" else "audio/mpeg",
                        filename=f"{recording_label(job)}.{extension}" if download else None)


@app.post("/api/jobs/{job_id}/loop")
def process_loop(job_id: uuid.UUID, body: LoopProcessing):
    with job_lock:
        job = dict(jobs.get(str(job_id), {}))
    if job.get("status") != "completed":
        raise HTTPException(404, "请先选择一段已生成的音频。")
    source = recording_path(job)
    if not source.is_file():
        raise HTTPException(404, "原始音频文件不存在。")
    # This is local audio processing only: no API call, no additional credits.
    with loop_lock:
        try:
            loop = export_loop(source, OUTPUT_DIR, str(job_id), body.crossfade_seconds)
            raw = OUTPUT_DIR / f"{job_id}-loop-{loop['overlap_frames']}.wav"
            named = OUTPUT_DIR / f"{recording_label(job)}-loop-{loop['overlap_frames']}.wav"
            raw.replace(named)
            loop["filename"] = named.name
            loop["source_id"] = f"generated:{named.name}"
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, "无法读取或导出音频，请确认原文件可播放后再试。") from exc
        update_job(str(job_id), loop_version=loop)
    return loop


@app.get("/api/audio/{job_id}/loop/{frames}")
def loop_audio(job_id: uuid.UUID, frames: int, download: bool = False):
    if frames <= 0:
        raise HTTPException(404, "循环文件不存在。")
    with job_lock:
        job = dict(jobs.get(str(job_id), {}))
        ready = job.get("status") == "completed"
    path = loop_path(job, frames) if ready else OUTPUT_DIR / "missing"
    if not ready or not path.is_file():
        raise HTTPException(404, "循环文件不存在，请先处理接缝。")
    return FileResponse(path, media_type="audio/wav",
                        filename=f"{recording_label(job)}-loop-{frames}.wav" if download else None)


@app.get("/api/audio/{job_id}/bridge")
def bridge_audio(job_id: uuid.UUID, download: bool = False):
    with job_lock:
        job = dict(jobs.get(str(job_id), {}))
    path = OUTPUT_DIR / f"{job_id}-transition" / "bridge.wav"
    if job.get("status") != "completed" or job.get("kind") != "bridge" or not path.is_file():
        raise HTTPException(404, "中间段尚未准备好。")
    return FileResponse(path, media_type="audio/wav",
                        filename=f"{recording_label(job)}-bridge.wav" if download else None)


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args()
    if not options.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{options.port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=options.port)
