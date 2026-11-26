FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services services
COPY worker worker
COPY scripts scripts
COPY docs docs
COPY alembic.ini .
ENV PYTHONPATH=/app/services/api:/app
RUN useradd -m careguide && mkdir -p /app/data/uploads /app/data/embedding-models && chown -R careguide:careguide /app
USER careguide
