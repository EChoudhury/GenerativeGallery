# Share the curator platform

## Free one-day event

The current setup uses a Cloudflare Quick Tunnel. It gives the Python platform a public HTTPS URL while the app, database and music stay on the host computer. Visitors can open it in Safari or Chrome on their phones.

The host computer must stay powered on, awake and connected to the internet. A Quick Tunnel is a temporary demo service with no uptime guarantee; stopping it removes the link, and restarting it gives a new URL. API generation still costs credits. Everyone with the link shares the same artwork and music library. Up to three generation jobs run at once; each browser follows its own request. Additional submissions are asked to retry once a slot is free.

### Start a new event

1. Install the official `cloudflared` client for the host computer: https://developers.cloudflare.com/tunnel/downloads/
2. In one terminal, run `cloudflared tunnel --url http://127.0.0.1:7870 --no-autoupdate` and copy its HTTPS URL.
3. Stop the existing gallery server after any active generation finishes. Start exactly one server from the repository root, substituting the new URL:

```bash
export CURATOR_PUBLIC_URL=https://your-new-url.trycloudflare.com
export CURATOR_PUBLIC_GENERATION=true
python -X utf8 -m curator_platform.app --port 7870
```

Use your activated Python environment, or `.venv/bin/python`. Keep both terminal processes running. On a Mac, `caffeinate -i -t 86400` prevents idle sleep for 24 hours; it does not keep a closed laptop awake or automatically stop the public link. Stop the tunnel with Ctrl+C when the event ends.

`CURATOR_PUBLIC_GENERATION=true` deliberately permits everyone with the link to view the shared library, upload artworks, rename saved music and use the configured generation API credits. Keys stay on the server. For an invited-only event, unset that option and set `CURATOR_PASSWORD` to a random password of at least 16 characters; the browser will prompt for username `curator` and the password.

Open the public link, not `localhost`, on phones. Tap **Start listening** to enable audio. If the phone pauses playback after a call or backgrounding, tap **Resume listening**. Use headphones for the listening field.

### End the event

Stop the tunnel process first. Stop the app and restart normally to return to local-only use:

```bash
unset CURATOR_PUBLIC_URL CURATOR_PUBLIC_GENERATION CURATOR_PASSWORD
python -m curator_platform.app --port 7870
```

## Optional permanent hosting

The root `Dockerfile` and `render.yaml` prepare a single-instance Render service with persistent storage. **This option is paid and has not been deployed.** The free one-day tunnel does not use Render.

Push the code to GitHub and create a Render Blueprint using that branch. Review the plan and disk cost before deploying. Set the Stability and image-interpretation API keys when prompted. Render creates a random `CURATOR_PASSWORD`; retrieve it privately in its environment settings. The username is `curator`. To intentionally allow open event access instead, remove that password and set `CURATOR_PUBLIC_GENERATION=true`.

Render provides `RENDER_EXTERNAL_URL` automatically. For a custom domain, set `CURATOR_PUBLIC_URL` to its HTTPS origin. Storage is configured as:

- `CURATOR_DATA_DIR=/var/data/curator`: SQLite records, uploads, saved audio and jobs.
- `CURATOR_EXPORT_DIR=/var/data/audio`: exported MP3 sets.

The Docker image excludes local data, secrets and unrelated repository assets. To migrate the existing library, stop generation and copy the complete `curator_platform/data/` directory to the persistent data directory before starting the service. Copy `audio/` separately if the exported MP3 folders are needed. A fresh deployment starts with an empty library.

Run one process and one instance: the queue, SQLite access and startup recovery are designed for a small shared workspace. Automatic deploys are disabled to reduce interrupted generation. Wait for jobs to finish before deploying; a restart marks unfinished jobs failed and does not automatically repeat paid requests.

## Checks and limits

Backend tests cover password/public access, HTTPS-origin validation, saved data, MP3 export and provider workflows using mocked providers. Frontend checks cover initialization and generation feedback. Mobile CSS targets narrow phone layouts with labeled navigation, 16px form controls and 44px touch targets. Actual iOS/Android visual and playback checks still need to be performed on a device; automated browser QA was unavailable in this session.

Concurrency: `CURATOR_MAX_CONCURRENT_JOBS` defaults to `3` (allowed range 1–8). Keep one server process; it uses a thread pool for concurrent jobs.
