# ---- Frontend build ----
FROM node:22-alpine AS frontend
WORKDIR /app/dashboard/frontend
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ .
# VITE_* are baked into the bundle at build time
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_BASE="/api/v1"
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ---- Backend ----
FROM python:3.13-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt pyproject.toml ./
COPY src/ src/
RUN pip install . && pip install -r requirements.txt

COPY data/ data/
COPY requirements-dashboard.txt ./
RUN pip install -r requirements-dashboard.txt

COPY dashboard/backend/ dashboard/backend/
COPY --from=frontend /app/dashboard/frontend/dist /app/dashboard/frontend/dist

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "dashboard.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
