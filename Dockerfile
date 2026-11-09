FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY curator_platform/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt
COPY curator_platform /app/curator_platform
# Fail the build if this runtime cannot export the platform's MP3 files.
RUN python -c "import soundfile as sf; assert 'MP3' in sf.available_formats(), 'MP3 codec unavailable'"
EXPOSE 7870
CMD ["python", "-m", "curator_platform.app", "--host", "0.0.0.0"]
