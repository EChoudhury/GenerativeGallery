"""Run with: python -m curator_platform.app --port 7870."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import re
import shutil
import sqlite3
from pathlib import Path
import threading
import tempfile
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
import numpy as np
import requests
import soundfile as sf
from PIL import Image, ImageOps, UnidentifiedImageError

from . import audio, providers

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
EXPORT_ROOT = ROOT.parent / 'audio'
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)
TERMINAL = {'completed', 'failed'}
app = FastAPI(title="Curator's Gallery", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise HTTPException(404, 'Record not found.') from None


@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATA/'gallery.sqlite')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def put(kind, value):
    with connect() as db:
        db.execute('INSERT INTO records(kind,id,body) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                   (kind, value['id'], json.dumps(value, ensure_ascii=False)))
    return value


def records(kind):
    with connect() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT body FROM records WHERE kind=?', (kind,))]


def find(kind, key):
    key = identifier(key)
    with connect() as db:
        row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
    if not row:
        raise HTTPException(404, 'Record not found.')
    return json.loads(row[0])


def safe_name(name):
    return re.sub(r'[^\w .-]+', '-', name).strip(' .-')[:90] or 'Untitled'


def numbered_name(name, directory):
    stem = safe_name(name)
    index = 1
    while (directory/f'{stem}-{index:03d}.wav').exists():
        index += 1
    return f'{stem}-{index:03d}.wav'


def asset(path):
    candidate = (DATA/path).resolve()
    if not candidate.is_relative_to(DATA.resolve()) or not candidate.is_file():
        raise HTTPException(404, 'File not found.')
    return candidate


def public_music(record):
    return {**record, 'audio_url': '/api/music/'+record['id']+'/audio',
            'image_url': '/api/artworks/'+record['artwork_id']+'/image' if record.get('artwork_id') else None}


def initialize(seed=True):
    for folder in ['images', 'jobs', 'music', 'grids']:
        (DATA/folder).mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(kind,id))')
    for job in records('job'):
        if job['status'] not in TERMINAL:
            job.update(status='failed', error='The service restarted before the result was confirmed. Check provider records before submitting again.')
            put('job', job)
    if seed and not records('music'):
        originals = [
            ('Mondrian · Boogie Revival', 'Piet Mondrian', 'Victory Boogie Woogie', 'Mondrian-Boogie-Revival-loop-44100.wav'),
            ('Morandi · Still Life', 'Giorgio Morandi', 'Still Life', '754b73fa-411e-46c2-806d-26a3dcbd94ad-loop-220500.wav')]
        for name, artist, title, file in originals:
            source = ROOT.parent/'assets/generated'/file
            if not source.is_file():
                continue
            destination = DATA/'music'/numbered_name(name, DATA/'music')
            shutil.copy2(source, destination)
            prompt = ''
            metadata = ROOT.parent/'assets/generated'/('754b73fa-411e-46c2-806d-26a3dcbd94ad.json' if artist.startswith('Giorgio') else 'cb89007a-07e8-4474-97c0-c052795e4105.json')
            if metadata.exists():
                prompt = json.loads(metadata.read_text()).get('prompt', '')
            put('music', {'id': str(uuid.uuid4()), 'name': name, 'artist': artist, 'artwork_title': title,
                'artwork_id': None, 'filename': 'music/'+destination.name, 'duration': sf.info(destination).duration,
                'prompt': prompt, 'is_loop': True, 'imported': True, 'created_at': now()})


@app.on_event('startup')
def startup():
    initialize()


@app.middleware('http')
async def local_requests(request: Request, call_next):
    if request.method in {'POST', 'PATCH', 'DELETE'}:
        if request.headers.get('origin') != str(request.base_url).rstrip('/') or request.headers.get('x-curator-request') != '1':
            return JSONResponse({'detail': 'Please make changes from the local curator workbench.'}, status_code=403)
        if int(request.headers.get('content-length', '0')) > 15_000_000:
            return JSONResponse({'detail': 'Upload is too large. Choose an image under 8 MB.'}, status_code=413)
        if len(await request.body()) > 15_000_000:
            return JSONResponse({'detail': 'Request is too large.'}, status_code=413)
    result = await call_next(request)
    result.headers['X-Content-Type-Options'] = 'nosniff'
    if request.url.path.startswith('/api/'):
        result.headers['Cache-Control'] = 'no-store'
    return result


class ArtworkInput(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    artist: str = Field(min_length=1, max_length=150)
    notes: str = Field(default='', max_length=5000)
    image: str = Field(min_length=10, max_length=12_000_000)

    @field_validator('title', 'artist')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Enter a title and artist.')
        return value.strip()


class TaskInput(BaseModel):
    request_id: uuid.UUID
    kind: str
    artwork_id: uuid.UUID | None = None
    source_job_id: uuid.UUID | None = None
    a_id: uuid.UUID | None = None
    b_id: uuid.UUID | None = None
    prompt: str = Field(default='', max_length=9000)
    duration: int = Field(default=32, ge=6, le=380)
    overlap: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    start: float = Field(default=0, ge=0, allow_inf_nan=False)
    end: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    context: float = Field(default=8, ge=1, le=20, allow_inf_nan=False)
    bridge: float = Field(default=12, ge=4, le=120, allow_inf_nan=False)
    name: str = Field(default='', max_length=150)
    method: Literal['hybrid', 'inpaint'] = 'hybrid'


class SaveInput(BaseModel):
    request_id: uuid.UUID
    source_job_id: uuid.UUID
    name: str = Field(min_length=1, max_length=150)

    @field_validator('name')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Please enter a music name.')
        return value.strip()


class RenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)

    @field_validator('name')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Please enter a music name.')
        return value.strip()


@app.get('/api/config')
def config():
    return {'providers': providers.configured(), 'version': 1}


@app.post('/api/artworks', status_code=201)
def create_artwork(body: ArtworkInput):
    try:
        prefix, content = body.image.split(',', 1)
        if prefix not in {'data:image/jpeg;base64', 'data:image/png;base64', 'data:image/webp;base64'}:
            raise ValueError('Unsupported image format')
        raw = base64.b64decode(content, validate=True)
        if len(raw) > 8_000_000:
            raise ValueError('Image exceeds 8 MB')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width*image.height > 24_000_000:
                raise ValueError('Image is too large')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1600, 1600))
            key = str(uuid.uuid4())
            image.save(DATA/'images'/f'{key}.jpg', quality=90)
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, 'Choose a valid JPEG, PNG or WebP image under 8 MB and 24 megapixels.') from None
    result = {'id': key, 'title': body.title, 'artist': body.artist, 'notes': body.notes,
              'image': 'images/'+key+'.jpg', 'prompt': '', 'analysis': None, 'created_at': now()}
    return put('artwork', result)


@app.get('/api/artworks/{artwork_id}/image')
def artwork_image(artwork_id: uuid.UUID):
    return FileResponse(asset(find('artwork', artwork_id)['image']), media_type='image/jpeg')


@app.get('/api/artworks/{artwork_id}')
def get_artwork(artwork_id: uuid.UUID):
    return find('artwork', artwork_id)


@app.get('/api/music')
def library():
    return [public_music(x) for x in sorted(records('music'), key=lambda x: x['created_at'], reverse=True)]


@app.post('/api/music', status_code=201)
def save_music(body: SaveInput):
    key = str(body.request_id)
    with LOCK:
        existing = next((x for x in records('music') if x['id'] == key), None)
        if existing:
            return public_music(existing)
        job = find('job', body.source_job_id)
        if job['status'] != 'completed' or job['kind'] not in {'music', 'loop'}:
            raise HTTPException(422, 'Finish generating or processing the music before saving.')
        artwork = find('artwork', job['result']['artwork_id'])
        destination = DATA/'music'/numbered_name(body.name, DATA/'music')
        shutil.copy2(asset(job['result']['file']), destination)
        result = {'id': key, 'name': body.name, 'filename': 'music/'+destination.name, 'duration': job['result']['duration'],
            'artwork_id': artwork['id'], 'artwork_title': artwork['title'], 'artist': artwork['artist'],
            'prompt': job['result']['prompt'], 'is_loop': job['kind'] == 'loop',
            'source_job_id': job['id'], 'created_at': now()}
        return public_music(put('music', result))


@app.patch('/api/music/{music_id}')
def rename_music(music_id: uuid.UUID, body: RenameInput):
    with LOCK:
        record = find('music', music_id)
        if record['name'] != body.name:
            destination = DATA/'music'/numbered_name(body.name, DATA/'music')
            asset(record['filename']).replace(destination)
            record.update(name=body.name, filename='music/'+destination.name)
            put('music', record)
        return public_music(record)


@app.get('/api/music/{music_id}/audio')
def music_audio(music_id: uuid.UUID, download: bool = False):
    record = find('music', music_id)
    return FileResponse(asset(record['filename']), media_type='audio/wav',
        filename=Path(record['filename']).name if download else None)


@app.get('/api/jobs')
def job_history():
    return sorted(records('job'), key=lambda x: x['created_at'], reverse=True)


@app.get('/api/jobs/{job_id}')
def get_job(job_id: uuid.UUID):
    return find('job', job_id)


def update_job(job_id, **changes):
    with LOCK:
        job = find('job', job_id)
        job.update(changes)
        put('job', job)
        return job


def advance(job_id, stage, message, progress):
    update_job(job_id, status='running', stage=stage, message=message, progress=progress)


def bridge_prompts(a, b, direction=''):
    a_text = (a.get('prompt') or f"Instrumental music inspired by {a['artwork_title']} by {a['artist']}.")[:2500]
    b_text = (b.get('prompt') or f"Instrumental music inspired by {b['artwork_title']} by {b['artist']}.")[:2500]
    base = ('An instrumental connecting passage in the masked interval. Continue the opening reference and approach the ending reference naturally. '
        'Preserve harmonic and acoustic continuity. Gradually reduce rhythmic density before changing the pulse. '
        'Use a sparse shared texture when the grooves differ. No abrupt stylistic cut, vocals, dramatic build or final cadence. ')
    loop = ('A stable repeating instrumental texture for gallery headphones. Begin within the established music, no intro, ending, fade or vocals. '
            'Maintain recognizable material from the supplied audio reference, avoiding a sudden switch between two styles. ')
    return {'bridge': base+'\nOpening musical world: '+a_text+'\nEnding musical world: '+b_text+'\nCurator direction: '+direction[:2000],
        'left': loop+'A texture leaning toward the opening painting while retaining the shared middle character. Target musical world: '+a_text,
        'right': loop+'A texture leaning toward the ending painting while retaining the shared middle character. Target musical world: '+b_text}


def do_bridge(job, directory, provider):
    a, b = find('music', job['payload']['a_id']), find('music', job['payload']['b_id'])
    prompts = bridge_prompts(a, b, job['payload']['prompt'])
    (directory/'prompts.json').write_text(json.dumps(prompts, indent=2))
    plan = audio.prepare_bridge(asset(a['filename']), asset(b['filename']), directory,
                                job['payload']['context'], job['payload']['bridge'])
    advance(job['id'], 'bridge', 'Generating the bridge from both audio anchors…', 12)
    provider.inpaint(plan['path'], prompts['bridge'], directory/'generated.wav', plan['duration'], plan['start'], plan['end'])
    report = audio.finish_bridge(directory, plan)
    return {'file': str((directory/'transition.wav').relative_to(DATA)),
            'bridge_file': str((directory/'bridge.wav').relative_to(DATA)), **report,
            'a_id': a['id'], 'b_id': b['id'], 'prompts': prompts}


def export_grid_mp3(grid):
    """Export a complete five-cell set under the two artwork titles, without overwriting other takes."""
    a, b = find('music', grid['a_id']), find('music', grid['b_id'])
    title_a = a.get('artwork_title') or a['name']
    title_b = b.get('artwork_title') or b['name']
    stem = safe_name(title_a + ' - ' + title_b)
    with LOCK:
        EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
        destination = EXPORT_ROOT/stem
        index = 2
        while destination.exists():
            manifest = destination/'manifest.json'
            try:
                existing = json.loads(manifest.read_text())
            except (OSError, ValueError):
                existing = {}
            if existing.get('grid_id') == grid['id'] and all((destination/f'cell_{i}.mp3').is_file() for i in range(5)):
                return {'directory': str(destination.relative_to(ROOT.parent)) if destination.is_relative_to(ROOT.parent) else str(destination),
                        'artwork_titles': [title_a, title_b], 'files': [f'cell_{i}.mp3' for i in range(5)]}
            destination = EXPORT_ROOT/f'{stem}-{index:03d}'
            index += 1
        with tempfile.TemporaryDirectory(prefix='.grid-export-', dir=EXPORT_ROOT) as temporary:
            staging = Path(temporary)/'complete'
            staging.mkdir()
            for i in range(5):
                source = asset(grid['files'][str(i)]['file'])
                samples, rate = sf.read(source, dtype='float32', always_2d=True)
                target = staging/f'cell_{i}.mp3'
                sf.write(target, samples, rate, format='MP3', subtype='MPEG_LAYER_III')
                info = sf.info(target)
                if info.format != 'MP3' or abs(info.duration-len(samples)/rate) > 0.15:
                    raise ValueError('An MP3 export did not pass validation; original WAV files were retained.')
            report = {'grid_id': grid['id'], 'gallery_name': grid['name'], 'artwork_titles': [title_a, title_b],
                      'method': grid.get('method', 'hybrid'), 'created_at': grid['created_at'],
                      'cells': [{'file': f'cell_{i}.mp3', 'label': grid['files'][str(i)]['label'],
                                 'duration': grid['files'][str(i)]['duration']} for i in range(5)]}
            (staging/'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            staging.rename(destination)
        return {'directory': str(destination.relative_to(ROOT.parent)) if destination.is_relative_to(ROOT.parent) else str(destination),
                'artwork_titles': [title_a, title_b], 'files': [f'cell_{i}.mp3' for i in range(5)]}


def do_grid(job, directory, provider):
    payload = job['payload']
    if payload.get('source_job_id'):
        previous = find('job', payload['source_job_id'])
        result = previous['result']
        source = audio.read(asset(result['file']))
        start = payload['start']
        end = payload['end'] if payload['end'] is not None else result['end']
    else:
        result = do_bridge(job, directory, provider)
        update_job(job['id'], bridge_result=result)
        source = audio.read(asset(result['file']))
        start, end = result['start'], result['end']
    if not result['start'] <= start < end <= result['end'] or end-start < 4:
        raise ValueError('Choose at least 4 seconds within the bridge recording for the middle cell.')
    center = source[round(start*audio.RATE):round(end*audio.RATE)]
    reference = directory/'middle-original.wav'
    audio.write(reference, center)
    duration = len(center)/audio.RATE
    files = {}
    for index, prompt_key, percent in [(1, 'left', 45), (3, 'right', 70)]:
        method = payload.get('method', 'hybrid')
        advance(job['id'], f'cell-{index}', f'Generating cell {index+1} of 5: '+('A-leaning' if index==1 else 'B-leaning')+(' inpainting…' if method == 'inpaint' else ' variation…'), percent)
        raw = directory/f'cell_{index}-raw.wav'
        if method == 'inpaint':
            # Real audio on both sides, rather than restyling the middle with audio-to-audio.
            endpoint_id = result['a_id'] if index == 1 else result['b_id']
            endpoint = find('music', endpoint_id)
            endpoint_path = asset(endpoint['filename'])
            left, right = (endpoint_path, reference) if index == 1 else (reference, endpoint_path)
            child = directory/f'cell_{index}-inpaint'
            child.mkdir(parents=True, exist_ok=True)
            plan = audio.prepare_bridge(left, right, child, payload['context'], duration)
            plan['prompt'] = ('An instrumental connecting passage between the supplied opening and ending audio references. '
                'Continue the opening phrasing and gradually approach the ending timbre, harmony and rhythmic density. '
                'Preserve a consistent acoustic space and perceived loudness. Avoid an abrupt style switch, '
                'vocals, dramatic build, final cadence or fade to silence. '
                'This connection sits between '+('artwork A and the curated shared middle.' if index == 1 else 'the curated shared middle and artwork B.')+
                '\nCurator direction: '+payload.get('prompt', '')[:2000])
            (child/'plan.json').write_text(json.dumps(plan, indent=2))
            provider.inpaint(plan['path'], plan['prompt'], child/'generated.wav', plan['duration'], plan['start'], plan['end'])
            audio.finish_bridge(child, plan)
            assembled = audio.read(child/'transition.wav')
            data = assembled[round(plan['start']*audio.RATE):round(plan['end']*audio.RATE)]
            audio.write(raw, data)
        else:
            provider.variation(reference, result['prompts'][prompt_key], raw, duration, strength=.4)
            data = audio.read(raw)
        if abs(len(data)/audio.RATE-duration) > .1:
            raise ValueError('A generated cell has an unexpected duration; the new grid was not activated.')
        if np.sqrt(np.mean(data.astype('float64')**2)) < 1e-5:
            raise ValueError('A generated cell is effectively silent; the new grid was not activated.')
        audio.write(directory/f'cell_{index}.wav', audio.circular_loop(data, .25))
    advance(job['id'], 'assemble', 'Preparing loops and saving the five-cell gallery…', 94)
    audio.write(directory/'cell_2.wav', audio.circular_loop(center, .25))
    for index, source_id in [(0, result['a_id']), (4, result['b_id'])]:
        music = find('music', source_id)
        shutil.copy2(asset(music['filename']), directory/f'cell_{index}.wav')
    a, b = find('music', result['a_id']), find('music', result['b_id'])
    for index, label in enumerate([a['name'], 'Toward '+a['name'], 'Shared middle', 'Toward '+b['name'], b['name']]):
        path = directory/f'cell_{index}.wav'
        info = sf.info(path)
        files[str(index)] = {'file': str(path.relative_to(DATA)), 'label': label, 'duration': info.duration}
    grid = {'id': job['id'], 'name': payload['name'].strip() or a['name']+' → '+b['name'],
            'a_id': a['id'], 'b_id': b['id'], 'a_name': a['name'], 'b_name': b['name'],
            'files': files, 'middle_interval': [start, end], 'loop_overlap': .25,
            'method': payload.get('method', 'hybrid'),
            'created_at': now(), 'bridge_job_id': payload.get('source_job_id') or job['id']}
    grid['mp3_export'] = export_grid_mp3(grid)
    (directory/'manifest.json').write_text(json.dumps(grid, indent=2))
    put('grid', grid)
    return {'grid_id': grid['id'], 'bridge': result}


def run_task(job_id):
    job = find('job', job_id)
    payload = job['payload']
    directory = DATA/'jobs'/job_id
    directory.mkdir(parents=True, exist_ok=True)
    def status(state):
        if state.startswith('remote:'):
            current = find('job', job_id)
            remote = current.get('remote_requests', [])
            remote.append({'stage': current.get('stage'), 'id': state[7:]})
            update_job(job_id, remote_requests=remote)
    try:
        if job['kind'] == 'prompt':
            advance(job_id, 'vision', 'Reading the artwork and composing a music prompt…', 20)
            artwork = find('artwork', payload['artwork_id'])
            result = providers.artwork_prompt(artwork, asset(artwork['image']), payload['duration'])
            artwork.update(prompt=result['music_prompt'], analysis=result)
            put('artwork', artwork)
        elif job['kind'] == 'music':
            advance(job_id, 'music', 'Generating your artwork’s music…', 15)
            artwork = find('artwork', payload['artwork_id'])
            artwork.update(prompt=payload['prompt'])
            put('artwork', artwork)
            provider = providers.AudioProvider(status)
            provider.generate(payload['prompt'], directory/'original.wav', payload['duration'])
            data = audio.read(directory/'original.wav')
            if np.max(np.abs(data)) < 1e-6:
                raise ValueError('The generated music is silent. Choose another candidate.')
            if abs(len(data)/audio.RATE-payload['duration']) > .2:
                raise ValueError('The provider returned an unexpected duration. The raw file was retained for inspection.')
            result = {'file': str((directory/'original.wav').relative_to(DATA)), 'duration': len(data)/audio.RATE,
                      'prompt': payload['prompt'], 'artwork_id': artwork['id']}
        elif job['kind'] == 'loop':
            advance(job_id, 'loop', 'Overlapping the ending and beginning locally…', 30)
            previous = find('job', payload['source_job_id'])['result']
            report = audio.make_loop(asset(previous['file']), directory/'loop.wav', payload['overlap'], payload['start'], payload['end'])
            result = {**previous, **report, 'file': str((directory/'loop.wav').relative_to(DATA))}
        elif job['kind'] == 'bridge':
            result = do_bridge(job, directory, providers.AudioProvider(status))
        elif job['kind'] == 'grid':
            result = do_grid(job, directory, providers.AudioProvider(status))
        else:
            raise ValueError('Unknown task')
        update_job(job_id, status='completed', progress=100, message='Ready', result=result, completed_at=now())
    except (providers.ProviderError, ValueError) as exc:
        update_job(job_id, status='failed', error=str(exc), message='This task did not complete.')
    except requests.RequestException:
        update_job(job_id, status='failed', error='The provider connection was interrupted. Check your provider account before submitting again; no automatic retry was made.')
    except Exception:
        update_job(job_id, status='failed', error='The task could not be completed. Its files were retained; no automatic paid retry was made.')


@app.post('/api/jobs', status_code=202)
def create_task(body: TaskInput):
    key = str(body.request_id)
    payload = body.model_dump(mode='json')
    with LOCK:
        existing = next((x for x in records('job') if x['id'] == key), None)
        if existing:
            return existing
        if body.kind not in {'prompt', 'music', 'loop', 'bridge', 'grid'}:
            raise HTTPException(422, 'Unknown task type.')
        availability = providers.configured()
        if body.kind == 'prompt' and not availability['deepseek']:
            raise HTTPException(503, 'Add DEEPSEEK_API_KEY to the root .env to generate a prompt, or write one yourself.')
        if body.kind in {'music', 'bridge', 'grid'} and not availability['stability']:
            raise HTTPException(503, 'Add STABILITY_API_KEY to the root .env to generate audio.')
        if any(x['status'] not in TERMINAL for x in records('job')):
            raise HTTPException(409, 'Another task is running. Wait for it to finish before starting this one.')
        if body.kind in {'prompt', 'music'}:
            if not body.artwork_id:
                raise HTTPException(422, 'Add the artwork first.')
            find('artwork', body.artwork_id)
            if body.kind == 'music' and not body.prompt.strip():
                raise HTTPException(422, 'Write or generate a music prompt first.')
        if body.kind == 'loop':
            previous = find('job', body.source_job_id)
            if previous['status'] != 'completed' or previous['kind'] != 'music':
                raise HTTPException(422, 'Choose a completed music generation.')
            end = previous['result']['duration'] if body.end is None else body.end
            if not 0 <= body.start < end <= previous['result']['duration'] or body.overlap*2 >= end-body.start:
                raise HTTPException(422, 'Choose a valid excerpt and an overlap shorter than half its duration.')
        if body.kind in {'bridge', 'grid'}:
            if body.kind == 'grid' and body.source_job_id:
                previous = find('job', body.source_job_id)
                if previous['kind'] != 'bridge' or previous['status'] != 'completed':
                    raise HTTPException(422, 'Choose a completed bridge preview.')
                payload['a_id'], payload['b_id'] = previous['result']['a_id'], previous['result']['b_id']
                if 'start' not in body.model_fields_set:
                    payload['start'] = previous['result']['start']
                if body.end is None:
                    payload['end'] = previous['result']['end']
                if not previous['result']['start'] <= payload['start'] < payload['end'] <= previous['result']['end'] or payload['end']-payload['start'] < 4:
                    raise HTTPException(422, 'Select at least 4 seconds within the generated middle; the two reference ends are excluded.')
            else:
                if not body.a_id or not body.b_id or body.a_id == body.b_id:
                    raise HTTPException(422, 'Choose two different saved tracks.')
                for music_id in [body.a_id, body.b_id]:
                    music = find('music', music_id)
                    if not music['is_loop']:
                        raise HTTPException(422, 'Use saved loops for the gallery endpoints.')
        job = {'id': key, 'kind': body.kind, 'status': 'queued', 'stage': 'queued', 'progress': 0,
               'message': 'Preparing your task…', 'payload': payload, 'created_at': now(), 'error': None, 'result': None}
        put('job', job)
        EXECUTOR.submit(run_task, key)
        return job


@app.get('/api/jobs/{job_id}/audio')
def task_audio(job_id: uuid.UUID, part: str = 'full', download: bool = False):
    job = find('job', job_id)
    result = job.get('result') if job['status'] == 'completed' else job.get('bridge_result')
    if job['kind'] == 'grid' and job.get('result'):
        result = job['result'].get('bridge')
    if not result or not result.get('file'):
        raise HTTPException(404, 'Audio is not ready yet.')
    if part not in {'full', 'bridge'}:
        raise HTTPException(404, 'Audio part not found.')
    path = result.get('bridge_file') if part == 'bridge' else result['file']
    if not path:
        raise HTTPException(404, 'Audio part not found.')
    title = safe_name(job['payload'].get('name') or job['kind'])
    return FileResponse(asset(path), media_type='audio/wav', filename=title+'-'+part+'.wav' if download else None)


@app.get('/api/grids')
def grid_history():
    return sorted(records('grid'), key=lambda x: x['created_at'], reverse=True)


@app.get('/api/grids/{grid_id}')
def get_grid(grid_id: uuid.UUID):
    return find('grid', grid_id)


@app.get('/api/grids/{grid_id}/audio/{column}')
def grid_audio(grid_id: uuid.UUID, column: int, download: bool = False):
    grid = find('grid', grid_id)
    entry = grid['files'].get(str(column))
    if not entry:
        raise HTTPException(404, 'Cell not found.')
    return FileResponse(asset(entry['file']), media_type='audio/wav',
                        filename=safe_name(grid['name'])+f'-cell-{column+1}.wav' if download else None)


app.mount('/static', StaticFiles(directory=ROOT/'web'), name='static')


@app.get('/')
def index():
    return FileResponse(ROOT/'web/index.html', media_type='text/html', headers={'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=7870)
    arguments = parser.parse_args()
    uvicorn.run(app, host='127.0.0.1', port=arguments.port)
