FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app
COPY static ./static
COPY ota ./ota

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV TV_STRETCH_DATABASE_URL=sqlite:////data/tv_stretch.db

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
