FROM python:3.12-slim

WORKDIR /app

COPY rsscord.py /app/rsscord.py

RUN python -m venv /opt/rsscord-venv \
    && /opt/rsscord-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/rsscord-venv/bin/pip install --no-cache-dir \
        'feedparser>=6.0.11' \
        'httpx>=0.27.0' \
        'PyYAML>=6.0.1' \
    && useradd --system --uid 10001 --create-home --home-dir /home/rsscord rsscord \
    && mkdir -p /config /data \
    && chown -R rsscord:rsscord /app /config /data /home/rsscord

USER rsscord

ENTRYPOINT ["/opt/rsscord-venv/bin/python", "/app/rsscord.py"]
CMD ["--config", "/config/config.yaml"]
