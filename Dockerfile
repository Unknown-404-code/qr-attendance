# Attendance app as one Docker container (Render free plan, Cloud Run or Hugging Face). See DEPLOY.md.
# Secrets come from the host's environment settings: DATABASE_URL, GA_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD.
FROM python:3.11-slim

# OpenCV and MediaPipe need these system libraries
# tzdata: set the TZ secret (e.g. Asia/Dubai) so Excel times and default class titles use campus time
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2 tzdata \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs the container as user 1000
RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

COPY --chown=user configs ./configs
COPY --chown=user src ./src
COPY --chown=user scripts/run_app.py scripts/_common.py ./scripts/

ENV PYTHONPATH=/app/src \
    GA_CACHE_DIR=/app/model-cache \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# Download the face and gesture models now, so the first check-in after a restart doesn't wait for them
RUN mkdir -p /app/model-cache /app/data && chown -R user /app/model-cache /app/data
USER user
# (download only: starting MediaPipe inside some build sandboxes aborts because it can't read the CPU count)
RUN python -c "from gesture_attendance.vision.downloads import arcface_dir; from gesture_attendance.vision.mediapipe_gesture import gesture_model; arcface_dir(); gesture_model()" \
    && ls -la /app/model-cache /app/model-cache/buffalo_s

EXPOSE 7860
# Hosts like Render and Cloud Run tell the app which port to use in $PORT; 7860 otherwise
CMD python scripts/run_app.py --hosted --preload --port ${PORT:-7860}
