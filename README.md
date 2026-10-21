# Living Gallery — audio engine starter

## Music generation UI / 音乐生成界面

在 macOS 上双击 **`打开音乐工作室.command`**，浏览器会打开本地工作室。
首次使用会安装所需的 Python 网页依赖；关闭运行服务的终端会停止服务。

在项目根目录创建 `.env`（不要提交到 GitHub）：

```dotenv
STABILITY_API_KEY=your_stability_api_key
```

输入英文音乐提示词、选择时长（1–380 秒）和 WAV/MP3，点击 **Generate music**。
每次生成会使用 Stability API credits。生成完成后可试听、循环播放、下载或复用提示词。
“Loop-oriented” 会追加循环结构提示，不保证生成文件首尾无缝；循环试听仅重复原始文件。
试听区的 **循环接缝处理** 可设置首尾重叠时长（0.05–10 秒，且小于原音频一半），
在本地交叉淡化后导出 24-bit WAV。可对比原始与处理版本，并从接缝前开始重复试听。
该操作不调用 Stability API、不消耗 credits、不覆盖原文件。处理结果和参数随历史保存。
输出时长会缩短一个重叠长度，不自动匹配节拍或和声；有节奏的素材需额外试听和对齐。
音频及其提示词历史保存在 `assets/generated/`，该目录已忽略，不会进入 Git 提交。
历史与输入草稿可在刷新后恢复。只允许一个生成任务同时运行；不会自动重试付费请求。
若生成超时或服务在生成时重启，请先检查 Stability 账户记录，避免重复生成产生费用。

手动启动：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python studio.py
```

默认地址是 `http://127.0.0.1:7860`。API key 只由本地后端读取，不发送给浏览器。
该界面独立于 `server.py` 的位置混音服务，也不修改现有音频素材。

---

A small first milestone for the ADE hackathon prototype:
- continuously plays looping WAV layers
- smoothly crossfades between `storm`, `machine`, and `dream`
- lets you switch artworks from the terminal
- includes generated placeholder audio so you can test before using Stable Audio

## 1. Requirements

Use Python 3.10+ if possible. On Windows, run these commands in PowerShell from this folder.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, you can use the venv Python directly:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate`.

## 2. Create placeholder sounds

```powershell
python make_demo_assets.py
```

This creates loopable test WAV files in `assets/`. They are synthesized placeholders, not the final generative audio.

## 3. Run the mixer

```powershell
python gallery_engine.py
```

Type `storm`, `machine`, or `dream` and press Enter to switch. Type `q` to quit.
Use headphones or start with low volume.

If you get an audio-device error, run:
```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```
Then share the error and device list. On Windows, make sure the intended output device is enabled in Sound settings.

## 4. Replace placeholders with Stable Audio

Keep the filenames the same, or update `gallery.json` to match your generated WAV filenames. The mixer loads WAV files at startup, so stop and restart it after replacing assets.

Stable Audio 3's official repo and CLI instructions:
https://github.com/Stability-AI/stable-audio-3

Once Stable Audio is installed, generate clips offline rather than inside the real-time audio callback. Example CLI command from the official repo:
```bash
stable-audio --model small-music -p "Atmospheric dark ambient soundscape, slow evolving low drone, no vocals, no percussion" --duration 30 -o assets/storm_drone.wav
```

Generate distinct layers for each artwork, for example:
- storm: low drone + sparse granular/rain texture
- machine: pulsing mechanical ambience + metallic texture
- dream: warm sustained pad + airy shimmer

The mixer currently loops each file. If a generated clip has a noticeable seam, try a different generation or we can add loop-point/crossfade processing next.
