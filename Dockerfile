# Nestor im Cloud-Betrieb (Ticket #5). Ein Image mit Code und Modellen – lokal läuft dasselbe mit
# `python -m coach` oder `docker run` (Lastenheft §6). Cloudflare Containers brauchen linux/amd64;
# dieses Dockerfile selbst ist plattformneutral, siehe cloudflare/README.md für den Bau-Hinweis.
FROM python:3.13-slim

# Build-Werkzeuge nur für sherpa-onnx (hat keine Rad-Datei für jede Plattform) – danach wieder weg, sonst
# bläht es das Image unnötig auf.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements ohne pytest – das Image braucht keine Testbibliothek (Ticket #5, "Darf anfassen" erlaubt nur
# dieses Dockerfile, nicht requirements.txt selbst).
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > requirements.cloud.txt \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.cloud.txt

# Code (siehe .dockerignore für den Ausschluss von testbibliothek/, meetings/, logs/, demo/, .git/, node_modules/)
COPY coach ./coach
COPY scripts ./scripts
COPY static ./static
COPY szenarien ./szenarien

# Modelle beim Bau laden (Pausenerkennung, Stimm-Fingerabdruck, Segmentierung – ~35 MB), damit der Container
# selbst keinen Netzzugriff mehr braucht und schnell startet.
RUN python scripts/modelle_laden.py

# Nicht-root: eigener Nutzer, eigenes Verzeichnis für die Ablage (Lastenheft §5: nur bis zum Abschluss).
RUN useradd --create-home --uid 10001 nestor \
    && mkdir -p /tmp/nestor \
    && chown -R nestor:nestor /app /tmp/nestor
USER nestor

ENV LMC_BETRIEB=cloud \
    LMC_ARCHIV=/tmp/nestor \
    LMC_ABLAGE_BEHALTEN=0 \
    LMC_AUFNAHMEN=/tmp/nestor/aufnahmen \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Nicht "python -m coach" (lauscht fest auf 127.0.0.1, siehe coach/__main__.py – das Ticket darf die Datei
# nicht anfassen): uvicorn direkt auf 0.0.0.0:8080, wie die Abnahme es verlangt.
CMD ["python", "-m", "uvicorn", "coach.server:app", "--host", "0.0.0.0", "--port", "8080"]
