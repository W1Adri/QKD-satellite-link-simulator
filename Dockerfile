# ---------------------------------------------------------------------------
# SimulCTTC — QKD Satellite Link Simulator
# Single-container build with Python 3.12, SQLite, and all dependencies.
# Usage:
#   docker build -t simulcttc .
#   docker run -p 8000:8000 simulcttc
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output for logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed by numpy/scipy wheels and bcrypt
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY run_app.py .

# Create data directory for SQLite (will be auto-created but explicit is better)
RUN mkdir -p /app/app/data

# Override SERVER_HOST so uvicorn binds to all interfaces inside container
ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    LOG_LEVEL=INFO

EXPOSE 8000

# Use uvicorn directly (not run_app.py) for production — no reload, single worker
CMD ["uvicorn", "app.backend:app", "--host", "0.0.0.0", "--port", "8000"]
