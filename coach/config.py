"""Zentrale Einstellungen und Schwellwerte (Lastenheft FR-09).

Alle Werte lassen sich über Umgebungsvariablen bzw. .env überschreiben.
Die Standardwerte sind die Demo-Startwerte aus dem Lastenheft.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

WURZEL = Path(__file__).resolve().parent.parent
load_dotenv(WURZEL / ".env")


def _zahl(name: str, standard: float) -> float:
    return float(os.getenv(name, str(standard)))


@dataclass(frozen=True)
class Einstellungen:
    # Modelle
    # Sprecherspur (wer spricht wann) und Text (was wird gesagt) kommen aus zwei Modellen, siehe transkription.py
    transkriptions_modell: str = os.getenv("LMC_TRANSKRIPTION", "gpt-4o-transcribe-diarize")
    text_modell: str = os.getenv("LMC_TEXT", "gpt-4o-transcribe")
    analyse_modell: str = os.getenv("LMC_ANALYSE", "gpt-5.4-mini")  # 04.10.: genauer bei Agenda-Wechseln als gpt-5 minimal
    # Ohne feste Sprache hat das Modell deutsche Rede ins Englische übersetzt (02.10.2026)
    sprache: str = os.getenv("LMC_SPRACHE", "de")
    # Denkaufwand des Analysemodells: "minimal" ist am schnellsten, leer = Standard des Modells
    analyse_aufwand: str = os.getenv("LMC_ANALYSE_AUFWAND", "low")
    # Audio-Blocklänge: kürzer = schnellere Signale, länger = stabilere Sprechererkennung
    block_sekunden: int = int(_zahl("LMC_BLOCK_SEKUNDEN", 10))

    # FR-03 Monolog: Gelb ab dieser zusammenhängenden Redezeit
    monolog_sekunden: float = _zahl("LMC_MONOLOG_SEKUNDEN", 60)
    # FR-04 Zeit: Gelb bei Ablauf; Rot ab dieser Überziehung in Prozent (0 = kein Rot)
    zeit_rot_prozent: float = _zahl("LMC_ZEIT_ROT_PROZENT", 10)
    # FR-05 Fokus-Karenzzeit: so lange klar themenfremd, bis Gelb
    fokus_karenz_sekunden: float = _zahl("LMC_FOKUS_KARENZ_SEKUNDEN", 20)
    # FR-06 Überlappung: Mindestdauer gleichzeitigen Sprechens, und wie lange Gelb stehen bleibt
    ueberlappung_min_sekunden: float = _zahl("LMC_UEBERLAPPUNG_MIN_SEKUNDEN", 0.5)
    ueberlappung_halte_sekunden: float = _zahl("LMC_UEBERLAPPUNG_HALTE_SEKUNDEN", 30)
    # Die Diarisierung zerlegt Gleichzeitiges in schnelles Hin und Her: so viele Wechsel in so vielen Sekunden
    zickzack_wechsel: int = int(_zahl("LMC_ZICKZACK_WECHSEL", 4))
    zickzack_fenster_sekunden: float = _zahl("LMC_ZICKZACK_FENSTER_SEKUNDEN", 3)

    # --- Version 2: Ströme statt Blöcke (docs/archiv/spezifikation_v2.md, Abschnitt 5) ---
    # Strom 1 Live-Text
    # „schnell“: Streaming (gpt-live-transcribe, Teiltext beim Sprechen, Satz 0,7 s nach Ende, ~1,02 $/h)
    # „sparsam“: je Äußerung per REST (text_modell, Satz im Mittel 1,1 s / max. ~4 s nach Ende, ~0,36 $/h)
    live_art: str = os.getenv("LMC_LIVE_ART", "schnell")
    live_modell: str = os.getenv("LMC_LIVE_MODELL", "gpt-live-transcribe")
    live_delay: str = os.getenv("LMC_LIVE_DELAY", "low")  # minimal | low | medium | high | xhigh
    # Pausenerkennung (lokal, Silero VAD): Äußerungsgrenzen
    vad_modell: str = os.getenv("LMC_VAD_MODELL", "silero_vad.onnx")
    vad_pause_sekunden: float = _zahl("LMC_VAD_PAUSE_SEKUNDEN", 0.5)
    vad_max_sekunden: float = _zahl("LMC_VAD_MAX_SEKUNDEN", 10)  # kurz: Sprecher früher bekannt (Monolog-Benchmark 05.10.)
    # Strom 2 Wer spricht (lokal, Stimm-Fingerabdruck je Fenster); Modell und Schwelle am Benchmark 05.10. ermittelt
    stimm_modell: str = os.getenv(
        "LMC_STIMM_MODELL", "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")
    # Segmentierung (pyannote 3.0): Sprecherwechsel und Überlappung im Signal statt fester Fenster
    segmentierung: bool = os.getenv("LMC_SEGMENTIERUNG", "1") == "1"
    ueberlappung_schwelle: float = _zahl("LMC_UEBERLAPPUNG_SCHWELLE", 0.3)
    # „misch“: Personen aus festen Fenstern (bewährt), Überlappung aus der Segmentierung; „segmente“: alles daraus
    segmentierung_art: str = os.getenv("LMC_SEGMENTIERUNG_ART", "misch")
    # Vorstellungsrunde nach der Begrüßung: so viele Sekunden Namen sammeln (0 = keine Vorstellungsrunde)
    vorstellung_sekunden: float = _zahl("LMC_VORSTELLUNG_SEKUNDEN", 45)
    # unter dieser Ähnlichkeit „Person ?“ statt raten (Benchmark 06.10.: AMI weniger Fehlzuordnungen, saubere Proben gleich)
    stimm_unsicher: float = _zahl("LMC_STIMM_UNSICHER", 0.4)
    stimm_schwelle: float = _zahl("LMC_STIMM_SCHWELLE", 0.50)
    # Überlappung im Stimmstrom: Fenster passt zu keiner Person sicher, aber zu zweien mittelmäßig
    mischung_max: float = _zahl("LMC_MISCHUNG_MAX", 0.45)
    mischung_zweit_min: float = _zahl("LMC_MISCHUNG_ZWEIT_MIN", 0.25)
    # Strom 4 Kontext: so viel Gesprochenes wird je Themen-Zuordnung gesammelt
    abschnitt_sekunden: float = _zahl("LMC_ABSCHNITT_SEKUNDEN", 15)
    # Live-Bild als One-Pager (FR-10), gezeichnet von Claude über das Abo (claude -p)
    # Tests ohne API-Kosten: Text-KI über das ChatGPT-Abo (coach/ki_abo.py), Transkript aus dem Zwischenspeicher,
    # keine Sprachausgabe. Im echten Meeting bleiben alle drei aus.
    ki: str = os.getenv("LMC_KI", "openai")  # openai | codex
    codex_befehl: str = os.getenv("LMC_CODEX_BEFEHL", "ssh -o BatchMode=yes -o ConnectTimeout=10 pi codex")
    codex_aufwand: str = os.getenv("LMC_CODEX_AUFWAND", "low")
    text_cache: str = os.getenv("LMC_TEXT_CACHE", "")  # Ordner; leer = aus
    stimme_aus: bool = os.getenv("LMC_STIMME_AUS") == "1"
    claude_befehl: str = os.getenv("LMC_CLAUDE_BEFEHL", "ssh -o BatchMode=yes -o ConnectTimeout=10 buddyboard claude")
    # Live-Bild: „openai“ (GPT-5.4 + Bildgenerator, wie ChatGPT; Fortschreibung des letzten Bildes; ~8 ct/Bild)
    # oder „claude“ (SVG über das Claude-Abo per claude -p; kostenlos, Layout schwächer)
    bild_anbieter: str = os.getenv("LMC_BILD_ANBIETER", "openai")
    bild_modell: str = os.getenv("LMC_BILD_MODELL", "gpt-image-2")
    bild_text_modell: str = os.getenv("LMC_BILD_TEXT_MODELL", "gpt-5.4")
    bild_qualitaet: str = os.getenv("LMC_BILD_QUALITAET", "medium")
    onepager_analyse_modell: str = os.getenv("LMC_ONEPAGER_ANALYSE", "opus")
    onepager_zeichen_modell: str = os.getenv("LMC_ONEPAGER_ZEICHNEN", "sonnet")
    onepager_analyse_aufwand: str = os.getenv("LMC_ONEPAGER_ANALYSE_AUFWAND", "low")  # gemessen: halbiert die Zeit
    onepager_zeichen_aufwand: str = os.getenv("LMC_ONEPAGER_ZEICHNEN_AUFWAND", "low")
    onepager_minuten: float = _zahl("LMC_ONEPAGER_MINUTEN", 10)
    # Aufnahmen für den Abspielmodus (WAV, 24 kHz mono, daneben <name>.json mit Einrichtung)
    aufnahmen: str = os.getenv("LMC_AUFNAHMEN", str(WURZEL / "testbibliothek" / "audio"))

    # Sprachassistent (docs/sprachassistent.md): Ansprache per Name, Antworten per Sprachausgabe
    assistent_name: str = os.getenv("LMC_ASSISTENT_NAME", "Nestor")
    # Schreibweisen, die die Texterkennung für den Namen liefern kann (Regex, ohne Wortgrenzen);
    # Abspieltest 05.10.: am Satzanfang kam „Nestor“ 3 von 4 Mal als „Mestor“ an
    # 08.10. (Voxtral, Basis): einmal „Westor“ → w dazu
    assistent_muster: str = os.getenv("LMC_ASSISTENT_MUSTER", r"[nmw][eä]st[oeu]h?r")
    assistent_modell: str = os.getenv("LMC_ASSISTENT_MODELL", "gpt-5.4-mini")
    assistent_aufwand: str = os.getenv("LMC_ASSISTENT_AUFWAND", "low")  # gemessen: erster Satz nach ~1,2 s
    stimme_modell: str = os.getenv("LMC_STIMME_MODELL", "gpt-4o-mini-tts")
    stimme: str = os.getenv("LMC_STIMME", "cedar")  # gemessen: erster Ton nach ~0,5 s
    # „gespraech“ = Realtime-Sprachmodell wie der ChatGPT-Sprachmodus (natürlich, unterbrechbar, ~5–10 Cent je
    # Gespräch); „text“ = Sprachmodell + Sprachausgabe (günstiger, ~1 Cent je Frage, nicht unterbrechbar)
    assistent_modus: str = os.getenv("LMC_ASSISTENT_MODUS", "gespraech")
    realtime_modell: str = os.getenv("LMC_REALTIME_MODELL", "gpt-realtime")
    gespraech_ende_sekunden: float = _zahl("LMC_GESPRAECH_ENDE_SEKUNDEN", 20)  # so lange Ruhe → Sitzung zu
    # Recherche auf Zuruf (Websuche über die Responses-API)
    recherche_modell: str = os.getenv("LMC_RECHERCHE_MODELL", "gpt-5.4-mini")
    recherche_aufwand: str = os.getenv("LMC_RECHERCHE_AUFWAND", "low")
    nachfrage_sekunden: float = _zahl("LMC_NACHFRAGE_SEKUNDEN", 15)  # Rückfrage ohne Namen möglich
    einwand_sekunden: float = _zahl("LMC_EINWAND_SEKUNDEN", 7)  # so lange wartet die Begrüßung auf ein „Nein“

    # Entscheider: gleicher Hinweis frühestens nach so vielen Sekunden erneut
    cooldown_sekunden: float = _zahl("LMC_COOLDOWN_SEKUNDEN", 90)
    # Regel „Alle kommen zu Wort“: ab wann stille Angemeldete gemeldet werden; Dominanz im gleitenden Fenster
    alle_still_minuten: float = _zahl("LMC_ALLE_STILL_MINUTEN", 10)
    dominanz_anteil: float = _zahl("LMC_DOMINANZ_ANTEIL", 0.5)
    dominanz_fenster_minuten: float = _zahl("LMC_DOMINANZ_FENSTER_MINUTEN", 10)
    port: int = int(_zahl("LMC_PORT", 8000))
    # Meeting-Ablage (nur Server): Ordner je Meeting; Audio dazu, solange wir testen (Einstellungen, abschaltbar)
    archiv: str = os.getenv("LMC_ARCHIV", str(WURZEL / "meetings"))
    aufnahme_speichern: bool = os.getenv("LMC_AUFNAHME", "1") == "1"
    # Abschluss (Lastenheft 2 Schritt 5, 4.4–4.6): Paket, Unterstützung, Datenspende
    eur_je_usd: float = _zahl("LMC_EUR_JE_USD", 0.92)
    # Standard wahr = heutiges Verhalten (Ordner bleibt liegen); in der Cloud auf falsch gesetzt
    ablage_behalten: bool = os.getenv("LMC_ABLAGE_BEHALTEN", "1") == "1"
    spenden: str = os.getenv("LMC_SPENDEN", str(WURZEL / "spenden"))

    # --- Startseite (Lastenheft Abschnitt 2/3/6): Kostenrichtwerte, Unterstützung, Rechtstexte ---
    # Richtwerte für die Startseite (Lastenheft Abschnitt 3). "Knopfdruck" gemessen Ticket #7
    # (docs/messung_knopfdruck.md): ~0,3-0,4 $/h bei 4 Knopfdrücken im echten Betrieb (API statt Codex).
    richtwert_live_eur: float = _zahl("LMC_RICHTWERT_LIVE_EUR", 2.0)
    richtwert_knopfdruck_eur: float = _zahl("LMC_RICHTWERT_KNOPFDRUCK_EUR", 0.4)
    paypal_me: str = os.getenv("LMC_PAYPAL_ME", "")  # leer = noch kein PayPal.me-Link, Unterstützung entfällt
    impressum_name: str = os.getenv("LMC_IMPRESSUM_NAME", "")
    impressum_anschrift: str = os.getenv("LMC_IMPRESSUM_ANSCHRIFT", "")
    impressum_mail: str = os.getenv("LMC_IMPRESSUM_MAIL", "")

    # --- Cloud-Betrieb (Ticket #5): Nestor als Container bei Cloudflare, ein Worker je Kunde/Meeting davor ---
    # "lokal" (Standard, Laptop) oder "cloud" (hinter dem Cloudflare-Worker, siehe cloudflare/README.md)
    betrieb: str = os.getenv("LMC_BETRIEB", "lokal")
    # Gemeinsames Geheimnis mit dem Worker (Secret WORKER_GEHEIMNIS dort): beweist, dass eine Anfrage wirklich
    # über ihn kam (Kopfzeile X-Nestor-Geheimnis), und schützt umgekehrt den Aufruf des Coachs beim Worker
    # (POST /intern/... für die Datenspende, siehe coach/ablage_r2.py).
    worker_geheimnis: str = os.getenv("LMC_WORKER_GEHEIMNIS", "")
    # Basisadresse des Worker (für den Rückruf aus dem Container, z. B. https://nestor.<konto>.workers.dev)
    worker_url: str = os.getenv("LMC_WORKER_URL", "")

    # --- Stufen (Ticket #13, Lastenheft 3): „basis“ = nur Mistral (EU), „premium“ = OpenAI wie bisher ---
    # Die Startseite wählt die Stufe je Meeting (POST /api/stufe); lokal gilt LMC_STUFE als Vorgabe.
    stufe: str = os.getenv("LMC_STUFE", "premium")
    basis_text_modell: str = os.getenv("LMC_BASIS_TEXT_MODELL", "mistral-medium-latest")  # Probe 08.10.: 12/12 Aktionen
    # Zuordnung alle ~15 s (größter Posten der Textaufrufe, mit Medium ~0,37 $/h): Small war im Vergleich gleich gut
    # (21/21 Zuordnung, 21/21 Ton, Demo-Wiederholung identisch; docs/messung_basis.md) und kostet ein Zehntel
    basis_zuordnung_modell: str = os.getenv("LMC_BASIS_ZUORDNUNG_MODELL", "mistral-small-latest")
    zuordnung_modell: str = os.getenv("LMC_ZUORDNUNG_MODELL", "")  # leer = analyse_modell
    basis_live_modell: str = os.getenv("LMC_BASIS_LIVE_MODELL", "voxtral-mini-transcribe-realtime-2602")
    basis_live_delay_ms: int = int(_zahl("LMC_BASIS_LIVE_DELAY_MS", 240))  # Text der Frage ~0,6 s nach Sprechende
    basis_transkription: str = os.getenv("LMC_BASIS_TRANSKRIPTION", "voxtral-mini-latest")  # Batch (Knopfdruck)
    basis_stimme_modell: str = os.getenv("LMC_BASIS_STIMME_MODELL", "voxtral-mini-tts-latest")
    basis_stimme: str = os.getenv("LMC_BASIS_STIMME", "01a1188b-54f4-71a8-86df-df69e318948c")  # Thorsten (voice_id)
    richtwert_basis_eur: float = _zahl("LMC_RICHTWERT_BASIS_EUR", 0.7)  # 10 Fragen + 2 Recherchen ≈ 0,72 $/h (#15)
    richtwert_premium_eur: float = _zahl("LMC_RICHTWERT_PREMIUM_EUR", 2.0)

    def __post_init__(self) -> None:
        # Cloud: Abo-Wege (Codex/Claude über den Pi) sind nur für eigene Tests gedacht und in der Cloud nicht
        # erreichbar – unabhängig davon, was LMC_KI/LMC_BILD_ANBIETER versehentlich mitbekommen.
        if self.betrieb == "cloud":
            if self.ki != "openai":
                object.__setattr__(self, "ki", "openai")
            if self.bild_anbieter not in ("openai", "text"):
                object.__setattr__(self, "bild_anbieter", "openai")


EINST = Einstellungen()


# --- Stufen: Nestor Basis (Mistral) und Nestor Premium (OpenAI) -------------------------------------------------------
# Eine Stufe ist ein Satz Einstellungen. Premium = was beim Start aus Umgebung/.env kam (wie bisher); Basis tauscht
# jedes Modell gegen sein Mistral-Gegenstück. Der Coach baut danach seinen Client neu (pipeline.Coach.stufe_setzen).
STUFEN = ("basis", "premium")
_STUFEN_FELDER = ("live_modell", "text_modell", "transkriptions_modell", "analyse_modell", "analyse_aufwand",
                  "zuordnung_modell",
                  "assistent_modell", "assistent_aufwand", "recherche_modell", "recherche_aufwand", "stimme_modell",
                  "stimme", "assistent_modus", "bild_anbieter", "nachfrage_sekunden")
_PREMIUM = {f: getattr(EINST, f) for f in _STUFEN_FELDER}


def basis_werte() -> dict:
    e = EINST
    return {
        "live_modell": e.basis_live_modell, "text_modell": e.basis_transkription,
        "transkriptions_modell": e.basis_transkription,
        "analyse_modell": e.basis_text_modell, "assistent_modell": e.basis_text_modell,
        "recherche_modell": e.basis_text_modell, "zuordnung_modell": e.basis_zuordnung_modell,
        "analyse_aufwand": "", "assistent_aufwand": "", "recherche_aufwand": "",  # Mistral kennt „low“ nicht
        "stimme_modell": e.basis_stimme_modell, "stimme": e.basis_stimme,
        # Nestor antwortet über Text + Sprachausgabe (kein Realtime-Gespräch): keine Rückfragen ohne Namen,
        # kein Ins-Wort-Fallen (Ticket #13); statt des Live-Bilds der Überblick als Text (kein Bildmodell)
        "assistent_modus": "text", "bild_anbieter": "text", "nachfrage_sekunden": 0.0,
    }


def stufe_setzen(stufe: str) -> None:
    """Einstellungen der Stufe übernehmen. Was in Premium zur Laufzeit geändert wurde (Stimme, Gesprächsart …),
    bleibt für die Rückkehr nach Premium gemerkt."""
    if stufe not in STUFEN:
        raise ValueError(f"Unbekannte Stufe: {stufe}")
    if EINST.stufe == "premium":
        _PREMIUM.update({f: getattr(EINST, f) for f in _STUFEN_FELDER})
    for k, v in (basis_werte() if stufe == "basis" else _PREMIUM).items():
        object.__setattr__(EINST, k, v)
    object.__setattr__(EINST, "stufe", stufe)


if EINST.stufe == "basis":
    object.__setattr__(EINST, "stufe", "premium")  # Ausgangswerte oben sind die von Premium
    stufe_setzen("basis")
elif EINST.stufe not in STUFEN:
    object.__setattr__(EINST, "stufe", "premium")


# --- OpenAI-Schlüssel ----------------------------------------------------------
# Jede Person trägt ihren eigenen Schlüssel im Dashboard ein. Er liegt dann nur auf diesem Rechner, außerhalb
# des Repos, in einer Datei im Benutzerordner – nie im Browser, nie im Log, nie in einer Antwort des Servers.
# Ohne Eintrag gilt OPENAI_API_KEY aus der Umgebung bzw. .env.
SCHLUESSEL_DATEI = Path(os.getenv("LMC_SCHLUESSEL_DATEI", str(Path.home() / ".live-meeting-coach" / "openai_schluessel")))
_gespeichert: str | None = None
_gelesen = False


def _datei_schluessel() -> str | None:
    global _gespeichert, _gelesen
    if not _gelesen:
        _gelesen = True
        try:
            _gespeichert = SCHLUESSEL_DATEI.read_text(encoding="utf-8").strip() or None
        except OSError:
            _gespeichert = None
    return _gespeichert


def openai_schluessel() -> str | None:
    return _datei_schluessel() or os.getenv("OPENAI_API_KEY") or None


def schluessel_info() -> dict:
    """Für das Dashboard: woher der Schlüssel kommt und seine letzten vier Zeichen – nie der Schlüssel selbst."""
    s = openai_schluessel()
    quelle = "dashboard" if _datei_schluessel() else ("umgebung" if s else None)
    return {"vorhanden": bool(s), "quelle": quelle, "ende": s[-4:] if s and len(s) > 12 else None,
            "offline": os.getenv("LMC_OFFLINE") == "1"}


def schluessel_speichern(schluessel: str | None) -> None:
    """None entfernt den im Dashboard eingetragenen Schlüssel (dann gilt wieder die Umgebung)."""
    global _gespeichert, _gelesen
    if schluessel:
        SCHLUESSEL_DATEI.parent.mkdir(parents=True, exist_ok=True)
        SCHLUESSEL_DATEI.write_text(schluessel, encoding="utf-8")
        try:
            os.chmod(SCHLUESSEL_DATEI, 0o600)
        except OSError:
            pass
    else:
        SCHLUESSEL_DATEI.unlink(missing_ok=True)
    _gespeichert, _gelesen = (schluessel or None), True


def hat_openai_schluessel() -> bool:
    """LMC_OFFLINE=1 schaltet alle KI-Aufrufe ab (Demo ohne Kosten)."""
    return bool(openai_schluessel()) and os.getenv("LMC_OFFLINE") != "1"


def mistral_schluessel() -> str | None:
    """Nestor Basis: Niclas' Mistral-Schlüssel aus der Umgebung (Secret im Cloud-Betrieb). Kein Eintrag im Dashboard –
    der eigene Schlüssel auf der Startseite ist ein OpenAI-Schlüssel und gilt nur für Premium."""
    return os.getenv("LMC_MISTRAL_SCHLUESSEL") or os.getenv("MISTRAL_API_KEY") or None


def ki_verfuegbar() -> bool:
    """Gibt es für die gewählte Stufe einen Schlüssel (und ist der Offline-Modus aus)?"""
    if os.getenv("LMC_OFFLINE") == "1":
        return False
    return bool(mistral_schluessel() if EINST.stufe == "basis" else openai_schluessel())
