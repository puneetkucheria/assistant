# Build stage for the React SPA.
# Emits the production bundle into /app/backend/static so the FastAPI
# process (built from backend/Dockerfile) can serve it at a single origin.
FROM node:20-alpine AS build

WORKDIR /app/frontend

# Install deps first for better layer caching.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Copy the rest of the frontend source and build.
COPY frontend/ ./
RUN npm run build

# Thin final image containing only the compiled static assets.
# This image is meant to be consumed as a build stage by backend/Dockerfile,
# not run directly.
FROM alpine:3.20 AS dist
COPY --from=build /app/backend/static /static
