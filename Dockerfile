FROM python:3.12-slim

# ffmpeg for media probing and reel assembly; git is only needed by optional packs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY workflows ./workflows
COPY dependencies.json ./

ENV PYTHONUNBUFFERED=1 \
    OPENGENJUTSU_PORT=8000

EXPOSE 8000

# The bind is 0.0.0.0 inside the container on purpose: docker-compose publishes it
# on 127.0.0.1 only, because the app has no authentication of its own.
CMD ["python", "-m", "uvicorn", "src.app:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8000"]
