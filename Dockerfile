FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Dependencias mínimas para Chromium (sin fuentes obsoletas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libgtk-3-0 libx11-xcb1 libxshmfence1 libx11-6 libxext6 libxcb1 \
    fonts-liberation ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Instalar Chromium sin --with-deps (las dependencias ya están)
RUN python -m playwright install chromium

COPY . .

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

