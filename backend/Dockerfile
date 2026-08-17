# Produces a single deployable image: FastAPI serving the built React SPA
# from backend/static on one origin (the app's production layout).
#
# Build from the project root so the frontend stage can access frontend/ and
# this stage can access backend/ and requirements.txt:
#
#   docker build -f backend/Dockerfile -t assistant .
#   docker run --env-file .env -p 8000:8000 assistant
#
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build        # -> /app/backend/static

# --- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend package (without static/ — it's gitignored & empty here).
COPY backend/ ./backend/

# Overlay the static assets built by the frontend stage. mountStatic in
# main.py keys off backend/static/index.html, so this is what enables the SPA.
COPY --from=frontend-build /app/backend/static ./backend/static

# Optional: keep a non-root user for runtime.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# run.sh sources .env and execs uvicorn; here we run uvicorn directly so the
# container respects env vars passed via `docker run --env-file .env`.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
