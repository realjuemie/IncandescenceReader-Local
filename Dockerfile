FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8787 \
    DATA_DIR=/data \
    NO_BROWSER=1 \
    TWS_HTTP_BACKEND=curl \
    TWS_TELEMETRY=0

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY incandescence ./incandescence
COPY public ./public

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8787
CMD ["python", "app.py"]
