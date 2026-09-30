FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY probe.py .
COPY health.py .

RUN mkdir -p /data \
    && chown -R 1000:1000 /app /data

ENV PYTHONUNBUFFERED=1
ENV PROBE_DATA_DIR=/data
ENV PROBE_INTERVAL_SECONDS=300
ENV PORT=8080

VOLUME ["/data"]

EXPOSE 8080

USER 1000:1000

CMD ["sh", "-c", "python -u health.py & exec python -u probe.py"]
