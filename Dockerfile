# WEOS — Railway / production image (explicit Docker avoids flaky Nixpacks)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Cairo / Pango: required by rlpycairo (pulled in by svglib). gcc/pkg-config for any wheel builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Ensure start script is executable (Windows checkouts may drop +x).
RUN chmod +x /app/start.sh

EXPOSE 8000

# Use start.sh so PORT is expanded by /bin/sh (never pass literal "$PORT" to uvicorn).
CMD ["/bin/sh", "/app/start.sh"]
