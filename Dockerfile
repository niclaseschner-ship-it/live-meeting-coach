# Nestor im Cloud-Betrieb (Ticket #5, mehrstufig seit Ticket #65). Ein Image mit Code und Modellen – lokal
# läuft dasselbe mit `python -m coach` oder `docker run` (Lastenheft §6). Cloudflare Containers brauchen
# linux/amd64; dieses Dockerfile selbst ist plattformneutral, siehe cloudflare/README.md für den Bau-Hinweis.
# `deploy/deploy.sh` erzeugt vor dem Bau `coach/version.json` (gitignored) – GIT_SHA und Bauzeit landen so im
# Image, ohne dass wrangler selbst Build-Args an dieses Dockerfile reichen müsste (geprüft: `containers[].
# image_vars` existiert zwar, braucht aber einen pro Deploy veränderten `wrangler.jsonc`-Wert; die Datei ist
# der einfachere, deterministische Weg – siehe GIT_SHA in coach/config.py:versionsinfo()).

# --- Stufe 1: Bauen -------------------------------------------------------------------------------------------
# Build-Werkzeuge nur hier für sherpa-onnx (hat keine Rad-Datei für jede Plattform). Sie landen NICHT im
# fertigen Image (Befund R2 Abschnitt 2.6: "build-essential cmake git bleiben entgegen dem Kommentar im
# Image" – das war der Bug im einstufigen Dockerfile, hier behoben durch die zweite Stufe unten).
FROM python:3.13-slim AS bauen

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.lock (Ticket #65) statt requirements.txt: exakte Versionen, reproduzierbar. Ohne pytest – das
# Image braucht keine Testbibliothek. `pip install --user`, damit sich Stufe 2 nur die reinen Pakete holt,
# ohne apt-Metadaten oder den Compiler-Cache mitzuschleppen.
COPY requirements.lock .
RUN grep -v '^pytest' requirements.lock > requirements.cloud.lock \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --user -r requirements.cloud.lock

# Nur das eine Skript, das zum Bauen gebraucht wird – nicht der ganze scripts/-Ordner (Labor-/Messskripte,
# zur Laufzeit ungenutzt, siehe R2 Abschnitt 1.5 "scripts/" und 2.6).
COPY scripts/modelle_laden.py scripts/modelle_laden.py
# Modelle beim Bau laden (Pausenerkennung, Stimm-Fingerabdruck, Segmentierung – ~35 MB), damit der Container
# selbst keinen Netzzugriff mehr braucht und schnell startet.
RUN PATH="/root/.local/bin:$PATH" PYTHONPATH="/root/.local/lib/python3.13/site-packages" \
    python scripts/modelle_laden.py

# --- Stufe 2: Laufzeit -----------------------------------------------------------------------------------------
# Schlank: kein Compiler, kein scripts/, kein szenarien/ (nur fürs lokale Demo-Formular "Testen ohne Runde" –
# die zugehörigen Endpunkte antworten im Cloud-Betrieb ohnehin mit 404, siehe coach/server.py). ca-certificates
# und libgomp1 bleiben: TLS zu OpenAI/Mistral/Worker bzw. OpenMP-Threads in onnxruntime/sherpa-onnx brauchen sie
# auch ohne den Compiler.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=bauen /root/.local /usr/local
COPY --from=bauen /app/modelle ./modelle

# Code (siehe .dockerignore für den Ausschluss von testbibliothek/, meetings/, logs/, demo/, .git/, node_modules/)
COPY coach ./coach
COPY static ./static

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
