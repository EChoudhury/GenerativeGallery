"""Local HTTP integration checks with mocked Stability responses; no API credits."""

import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import uuid
import wave
import numpy as np
import soundfile as sf

import uvicorn
import studio
from generate_assets import StabilityAudioClient


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 800)
    return output.getvalue()


class StudioHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.patches = [patch.object(studio, "OUTPUT_DIR", Path(cls.temp.name)),
                       patch.object(studio, "jobs", {}),
                       patch.object(studio, "api_key", return_value="test-key-never-sent")]
        for item in cls.patches:
            item.start()
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(studio.app, log_level="error"))
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[cls.sock]), daemon=True)
        cls.thread.start()
        for _ in range(200):
            if cls.server.started:
                return
            time.sleep(0.01)
        raise RuntimeError("Test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.sock.close()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        with studio.job_lock:
            studio.jobs.clear()

    def call(self, path, body=None, headers=None):
        request_headers = {"Origin": self.base, "X-Studio-Request": "1"}
        request_headers.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=request_headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def body(self, **overrides):
        return {"request_id": str(uuid.uuid4()), "prompt": "A quiet repeating piano texture.",
                "duration": 32, "output_format": "wav", "loop": True, **overrides}

    def test_page_config_and_secret_files(self):
        self.assertEqual(self.call("/")[0], 200)
        self.assertEqual(self.call("/static/app.js")[0], 200)
        config = json.loads(self.call("/api/config")[2])
        self.assertTrue(config["key_configured"])
        self.assertNotIn("test-key-never-sent", json.dumps(config))
        self.assertEqual(self.call("/.env")[0], 404)

    def test_rejects_cross_origin_paid_requests(self):
        with patch.object(studio.executor, "submit") as submit:
            self.assertEqual(self.call("/api/generate", self.body(), {"Origin": "https://example.com"})[0], 403)
            self.assertEqual(self.call("/api/generate", self.body(), {"X-Studio-Request": ""})[0], 403)
            submit.assert_not_called()

    def test_missing_key_and_invalid_inputs_do_not_generate(self):
        with patch.object(studio.executor, "submit") as submit:
            with patch.object(studio, "api_key", return_value=""):
                self.assertEqual(self.call("/api/generate", self.body())[0], 503)
            for overrides in [{"prompt": "   "}, {"duration": 0}, {"duration": 381},
                              {"duration": 3.5}, {"output_format": "exe"}]:
                self.assertEqual(self.call("/api/generate", self.body(**overrides))[0], 422)
            submit.assert_not_called()

    def test_idempotency_and_one_job_at_a_time(self):
        body = self.body()
        with patch.object(studio.executor, "submit") as submit:
            status, _, content = self.call("/api/generate", body)
            self.assertEqual(status, 202)
            job = json.loads(content)
            self.assertIn(studio.LOOP_INSTRUCTIONS, job["effective_prompt"])
            self.assertEqual(self.call("/api/generate", body)[0], 202)
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(self.call("/api/generate", self.body())[0], 409)

    def test_complete_generation_polling_download_and_restore(self):
        body = self.body()
        audio = wav_bytes()
        post = Mock(status_code=202)
        post.json.return_value = {"id": "provider-job"}
        pending = Mock(status_code=202)
        finished = Mock(status_code=200, content=audio)
        with patch("generate_assets.requests.post", return_value=post) as request, \
             patch("generate_assets.requests.get", side_effect=[pending, finished]), \
             patch("generate_assets.time.sleep"):
            self.assertEqual(self.call("/api/generate", body)[0], 202)
            for _ in range(100):
                job = json.loads(self.call(f"/api/jobs/{body['request_id']}")[2])
                if job["status"] in studio.TERMINAL:
                    break
                time.sleep(0.01)
            self.assertEqual(job["status"], "completed")
            self.assertEqual(request.call_args.kwargs["data"]["output_format"], "wav")
            self.assertEqual(request.call_args.kwargs["data"]["duration"], 32)
        status, headers, result = self.call(job["audio_url"])
        self.assertEqual(status, 200)
        self.assertIn("audio/wav", headers["Content-Type"])
        self.assertEqual(result, audio)
        self.assertIn("attachment", self.call(job["audio_url"] + "?download=true")[1]["Content-Disposition"])
        self.assertEqual(self.call(job["audio_url"], headers={"Range": "bytes=0-3"})[2], b"RIFF")
        with studio.job_lock:
            studio.jobs.clear()
        studio.restore_history()
        self.assertEqual(studio.jobs[job["id"]]["status"], "completed")

    def test_provider_failure_is_safe_and_persisted(self):
        body = self.body(loop=False)
        response = Mock(status_code=402, text="private response including test-key-never-sent")
        with patch("generate_assets.requests.post", return_value=response):
            self.call("/api/generate", body)
            for _ in range(100):
                job = json.loads(self.call(f"/api/jobs/{body['request_id']}")[2])
                if job["status"] == "failed":
                    break
                time.sleep(0.01)
        self.assertEqual(job["status"], "failed")
        self.assertIn("余额不足", job["error"])
        self.assertNotIn("test-key-never-sent", json.dumps(job))
        self.assertEqual(job["effective_prompt"], body["prompt"])
        self.assertEqual(self.call(f"/api/audio/{body['request_id']}")[0], 404)

    def test_mp3_cli_behavior_preserved(self):
        client = StabilityAudioClient(api_key="test")
        with patch("generate_assets.requests.post", return_value=Mock()) as request, \
             patch.object(client, "_wait_for_result", return_value=Path("output.mp3")):
            client.generate("A piano loop")
        self.assertEqual(request.call_args.kwargs["data"]["output_format"], "mp3")
        with self.assertRaises(ValueError):
            client.generate("A piano loop", output="not-audio.txt")
        client.session.close()

    def test_local_loop_processing_download_and_history(self):
        body = self.body()
        with patch.object(studio.executor, "submit"):
            self.assertEqual(self.call("/api/generate", body)[0], 202)
        job_id = body["request_id"]
        source = studio.recording_path(studio.jobs[job_id])
        original = wav_bytes()
        source.write_bytes(original)
        studio.update_job(job_id, status="completed", audio_url=f"/api/audio/{job_id}")
        with patch("generate_assets.requests.post") as provider:
            status, _, content = self.call(f"/api/jobs/{job_id}/loop", {"crossfade_seconds": 0.02})
            provider.assert_not_called()
        self.assertEqual(status, 200)
        result = json.loads(content)
        self.assertAlmostEqual(result["duration"], 0.08)
        self.assertEqual(result["overlap_frames"], 160)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotIn(job_id, result["filename"])
        library = json.loads(self.call("/api/sources")[2])
        chosen = next(item for item in library if item["id"] == result["source_id"])
        self.assertIn("Loop", chosen["title"])
        self.assertEqual(chosen["variant"], "loop")
        # A processed loop can be submitted directly as one inpainting anchor.
        with patch.object(studio.executor, "submit"):
            request = {"request_id": str(uuid.uuid4()), "source_a": result["source_id"],
                       "source_b": f"generated:{source.name}", "context_seconds": 1, "bridge_seconds": 4}
            self.assertEqual(self.call("/api/bridge", request)[0], 202)
            studio.update_job(request["request_id"], status="failed")
        status, headers, content = self.call(result["audio_url"] + "?download=true")
        self.assertEqual(status, 200)
        self.assertIn("audio/wav", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        with wave.open(io.BytesIO(content)) as audio:
            self.assertEqual(audio.getnframes(), 640)
            self.assertEqual(audio.getsampwidth(), 3)
        for seconds in [0, -1, 11, 0.06]:
            self.assertEqual(self.call(f"/api/jobs/{job_id}/loop", {"crossfade_seconds": seconds})[0], 422)
        self.assertEqual(studio.get_job(uuid.UUID(job_id))["loop_version"]["audio_url"], result["audio_url"])
        with studio.job_lock:
            studio.jobs.clear()
        studio.restore_history()
        self.assertEqual(studio.jobs[job_id]["loop_version"]["duration"], result["duration"])
        self.assertEqual(self.call(f"/api/jobs/{uuid.uuid4()}/loop", {"crossfade_seconds": 1})[0], 404)

    def test_artwork_numbering_safe_names_and_workflow_order(self):
        with patch.object(studio.executor, "submit"):
            first = json.loads(self.call("/api/generate", self.body(title="Test artwork / 花"))[2])
            self.assertEqual(first["filename"], "Test artwork - 花-001.wav")
            studio.update_job(first["id"], status="failed")
            second = json.loads(self.call("/api/generate", self.body(title="Test artwork / 花"))[2])
            self.assertEqual(second["filename"], "Test artwork - 花-002.wav")
        page = self.call("/")[2].decode()
        self.assertLess(page.index('id="loop-heading"'), page.index('id="bridge-heading"'))
        self.assertIn('id="loop-to-a"', page)
        self.assertIn('id="loop-to-b"', page)

    def test_bridge_sources_validation_idempotency_and_async_export(self):
        a = studio.OUTPUT_DIR / "test-anchor-a.wav"
        b = studio.OUTPUT_DIR / "test-anchor-b.wav"
        sf.write(a, np.full(16000, 0.1), 8000)
        sf.write(b, np.full(16000, 0.2), 8000)
        sources = json.loads(self.call("/api/sources")[2])
        self.assertIn("generated:test-anchor-a.wav", {source["id"] for source in sources})
        body = {"request_id": str(uuid.uuid4()), "source_a": "generated:test-anchor-a.wav",
                "source_b": "generated:test-anchor-b.wav", "context_seconds": 1, "bridge_seconds": 4}
        # Fill the HTTP result from the posted reference without making any remote request.
        def post_response(*args, **kwargs):
            data = kwargs["data"]
            reference, rate = sf.read(kwargs["files"]["audio"], dtype="float32", always_2d=True)
            reference[round(data["mask_start"]*rate):round(data["mask_end"]*rate)] = 0.15
            output = io.BytesIO()
            sf.write(output, reference, rate, format="WAV", subtype="FLOAT")
            finished.content = output.getvalue()
            return response
        response = Mock(status_code=202)
        response.json.return_value = {"id": "fake-inpaint"}
        finished = Mock(status_code=200)
        with patch("generate_assets.requests.post", side_effect=post_response) as provider, \
             patch("generate_assets.requests.get", return_value=finished), \
             patch("generate_assets.time.sleep"):
            self.assertEqual(self.call("/api/bridge", body)[0], 202)
            for _ in range(200):
                job = json.loads(self.call(f"/api/jobs/{body['request_id']}")[2])
                if job["status"] in studio.TERMINAL:
                    break
                time.sleep(0.01)
            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertEqual(job["duration"], 6)
            self.assertEqual(self.call("/api/bridge", body)[0], 202)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.call(job["audio_url"])[0], 200)
        status, headers, data = self.call(job["bridge_url"] + "?download=true")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertAlmostEqual(sf.info(io.BytesIO(data)).duration, 4.1)
        self.assertEqual(self.call("/api/bridge", {**body, "request_id": str(uuid.uuid4()), "source_a": "../.env"})[0], 422)
        self.assertEqual(self.call("/api/bridge", {**body, "request_id": str(uuid.uuid4()), "source_a": body["source_b"]})[0], 422)


if __name__ == "__main__":
    unittest.main()
