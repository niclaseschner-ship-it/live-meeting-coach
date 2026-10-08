r"""HTML-Testbericht für einen Cloud-Testlauf (Ticket #19): eine einzige, eigenständige HTML-Seite zum
Präsentieren – Audiospieler (Meeting-Ton gemischt mit Nestors Stimme, Testaufnahme um den gemessenen Versatz
verschoben, damit beides zur Meetinguhr passt; Nestor etwas lauter), darunter ein Zeitstrahl mit einer Marke
für jeden Dashboard-Screenshot (Vorschaubild beim Überfahren, Klick springt im Audio dorthin) und farbigen
Marken für jedes Ereignis/jede Nestor-Anweisung/jeden Grenzfall aus der Prüfliste (✅/❌/📝/⏭️). Beim Abspielen
wechselt der große Screenshot automatisch zum zuletzt erreichten Zeitpunkt. Kopf mit den Kennzahlen und
Urteilen aus bewertung.md. Alles eingebettet (Audio als MP3 ~96 kbit/s, Screenshots als WebP verkleinert,
beides base64) – funktioniert offline und am Handy, hell/dunkel.

    ~/.venvs/lmc/bin/python scripts/cloudtest_bericht.py logs/cloudtest/<lauf>

Braucht <lauf>/bericht.json (immer) und, für Zeitstrahl-Marken + Versatz-Korrektur, <lauf>/ws.jsonl plus die
referenz.json aus bericht.json["messwerte"]["referenz_datei"] – dieselbe Logik wie scripts/cloudtest_bewerten.py
(keine zweite Berechnung). <lauf>/bewertung.md liefert die Kennzahlen/Urteile für den Kopf, wenn vorhanden
(sonst nur Ablauf/Screenshots, ohne Kennzahlen-Kopf). cloudtest_bewerten.py ruft dieses Skript selbst am Ende
auf – ein bericht.html ist seitdem Standard für jeden Lauf.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
import cloudtest as ct  # noqa: E402 – dieselbe Auswertungslogik wie Live-Lauf/Bewertung, hier nicht verdoppeln
import cloudtest_bewerten as cb  # noqa: E402 – nur für nur_knopfdruck_aus_bericht(), keine Codex-Aufrufe hier

FFMPEG = "/usr/bin/ffmpeg"
FFPROBE = "/usr/bin/ffprobe"
BILD_BREITE = 640  # px – Screenshots sind 1280x720, für Zeitstrahl-Vorschau/Ansicht reicht das (Ticket #19)
BILD_QUALITAET = 68
AUDIO_KBIT = "96k"
NESTOR_LAUTER_DB = "4dB"  # "Nestor etwas lauter" (Ticket #19)


# ---------- Kennzahlen/Urteile aus bewertung.md (vorhandene Datei, keine zweite Codex-Berechnung) ----------
def bewertung_md_parsen(pfad: Path) -> dict | None:
    if not pfad.exists():
        return None
    text = pfad.read_text(encoding="utf-8")
    abschnitte = {}
    aktuell = "_kopf"
    for zeile in text.splitlines():
        m = re.match(r"^##\s+(.+)$", zeile)
        if m:
            aktuell = m.group(1).strip()
            abschnitte[aktuell] = []
            continue
        abschnitte.setdefault(aktuell, []).append(zeile)

    def tabellenzeilen(zeilen: list[str], spalten: int) -> list[tuple[str, ...]]:
        aus = []
        for z in zeilen:
            z = z.strip()
            if not z.startswith("|") or set(z.replace("|", "").strip()) <= {"-", " "}:
                continue
            teile = [t.strip() for t in z.strip("|").split("|")]
            if len(teile) == spalten and teile[0] not in ("Kennzahl", "Kriterium"):
                aus.append(tuple(teile))
        return aus

    kennzahlen = tabellenzeilen(abschnitte.get("Messbare Kennzahlen", []), 2)
    urteile_zeilen = tabellenzeilen(abschnitte.get("Urteile (1–5)", []), 3)
    urteile_text = None
    if not urteile_zeilen:
        for z in abschnitte.get("Urteile (1–5)", []):
            if z.strip():
                urteile_text = z.strip()
                break

    schlimmste = []
    for z in abschnitte.get("Die schlimmsten Stellen", []):
        z = z.strip()
        if z.startswith("- "):
            schlimmste.append(z[2:].strip())

    kopf_zeile = next((z for z in abschnitte.get("_kopf", []) if z.strip().startswith("Lauf:")), "")
    return {"kennzahlen": kennzahlen, "urteile": urteile_zeilen, "urteile_text": urteile_text,
           "schlimmste": schlimmste, "kopf": kopf_zeile.strip()}


# ---------- Zeitstrahl-Marken: dieselbe Prüfliste wie cloudtest_bewerten.py, hier mit Zeitstempeln gezippt ----------
def marken_und_versatz(bericht: dict, frames: list[dict]) -> tuple[list[dict], float | None]:
    referenz_roh = ct.referenz_laden(bericht["messwerte"])
    if not frames or referenz_roh is None:
        return [], bericht["messwerte"].get("versatz_s")
    zustaende = ct.zustaende_aus_frames(frames)
    if not zustaende:
        return [], None
    hinweise = ct._hinweise_dedup(zustaende)
    karten = ct._karten_dedup(zustaende)
    stimme = ct.nachrichten_aus_frames(frames, "stimme")
    offline_lauf = bool((zustaende[-1].get("schluessel") or {}).get("offline"))
    nur_knopfdruck = cb.nur_knopfdruck_aus_bericht(bericht)
    plan, uhr = ct.meeting_plan(bericht["messwerte"], zustaende)
    pruefliste, versatz = ct.pruefpunkte_berechnen(referenz_roh, zustaende, hinweise, karten, stimme,
                                                   offline_lauf, nur_knopfdruck, plan)
    if plan:  # #25: Referenzzeiten mit den Pausen auf der Meetinguhr
        referenz_roh = ct.takt.referenz_auf_meetinguhr(referenz_roh, plan)
    referenz = ct.referenz_verschieben(referenz_roh, versatz or 0.0)

    # Die Prüfliste ist in Referenz-Reihenfolge (Ereignisse, Anweisungen, Grenzfälle); Kennzahl-Punkte dazwischen
    # (#24: „Kennzahl Verzug Abschweifung …“) haben keine eigene Referenzzeile und würden sonst alles verrücken.
    pruefliste = [p for p in pruefliste if not p["name"].startswith("Kennzahl")]
    marken: list[dict] = []
    i = 0
    for e in referenz.get("ereignisse", []):
        p = pruefliste[i]; i += 1
        marken.append({"t": e["zeit_s"], "art": "ereignis", "label": f"Ereignis „{e['ereignis']}“",
                      "status": p["status"], "detail": p["detail"]})
    for n in referenz.get("nestor", []):
        p = pruefliste[i]; i += 1
        kurz = n["text"][:60] + ("…" if len(n["text"]) > 60 else "")
        marken.append({"t": n["start"], "art": "nestor", "label": f"Anweisung „{kurz}“",
                      "status": p["status"], "detail": p["detail"]})
    for g in referenz.get("grenzfaelle", []):
        p = pruefliste[i]; i += 1
        marken.append({"t": g["start"], "art": "grenzfall", "label": f"Grenzfall {g['id']} ({g['erwartet']})",
                      "status": p["status"], "detail": p["detail"]})
    if plan:  # wo der Test auf Nestor gewartet hat (#25)
        status = {"fertig": "ok", "zeitlimit": "fehlt", "abgebrochen": "fehlt", "kein_hoeren": "fehlt",
                  "keine_reaktion": "beobachtet"}
        for pa in (bericht["messwerte"].get("takt") or {}).get("pausen", []):
            name = "Begrüßung abgewartet" if pa["art"] == "begruessung" else f"Nestor abgewartet nach {pa.get('id')}"
            marken.append({"t": pa["t_bezug"] + uhr, "art": "pause", "label": name,
                          "status": status.get(pa["ergebnis"], "beobachtet"),
                          "detail": f"{pa['ergebnis']}, {pa['dauer_s']:.0f} s gewartet, Nestor sprach "
                                    f"{pa.get('ton_dauer_s', 0):.0f} s"})
        # Ticket #27: jeder Knopfdruck des Tests als eigene Marke (Sprechtaste mit Dauer und Satz, Knöpfe, Band, ✕, Still)
        for b in ct.takt.bedienung_auswerten((bericht["messwerte"].get("takt") or {}).get("bedienung") or [],
                                             frames, uhr):
            label = b["name"] + (f" {b['dauer_s']:.1f} s" if b.get("dauer_s") else "") + (
                f": „{b['satz'][:70]}“" if b.get("satz") else "")
            marken.append({"t": b["zeit"], "art": "bedienung", "label": label, "status": "bedienung",
                           "detail": ct.takt.bedienung_text(b)})
    marken.sort(key=lambda m: m["t"])
    return marken, versatz


def nestor_versatz_schaetzen(frames: list[dict]) -> float | None:
    """Verschiebung (Meetinguhr − Lauf-Achse) für nestor_stimme.wav: Median aus den ersten "stimme"-
    Nachrichten, deren Meetingzeit über die nächstgelegene Zustandsmeldung bestimmt wird – dieselbe
    Zuordnung wie cloudtest.nestor_reaktion() für Karten/Ton. Robuster als messwerte.seite_bis_meeting_
    start_s, das in älteren Berichten fehlt (siehe cloud_basis_grenz/cloud_basis_knopf, 08.10.2026)."""
    zustaende = ct.zustaende_aus_frames(frames)
    stimme = ct.nachrichten_aus_frames(frames, "stimme")
    if not zustaende or not stimme:
        return None
    diffs = []
    for s in stimme[:10]:
        z_nah = min(zustaende, key=lambda z: abs(z["_t"] - s["_t"]), default=None)
        if z_nah is not None:
            diffs.append(z_nah.get("zeit", 0.0) - s["_t"])
    if not diffs:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]


# ---------- Screenshots einordnen ----------
_DASHBOARD_RE = re.compile(r"^dashboard_(\d+)(\d{2})$")


def sekunden_aus_dashboard_name(name: str) -> float | None:
    m = _DASHBOARD_RE.match(name)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def screenshots_einordnen(bericht: dict) -> tuple[list[tuple[str, float]], list[str]]:
    dashboard, sonstige = [], []
    for name in bericht.get("screenshots", []):
        sek = sekunden_aus_dashboard_name(name)
        (dashboard.append((name, sek)) if sek is not None else sonstige.append(name))
    dashboard.sort(key=lambda x: x[1])
    return dashboard, sonstige


# ---------- Bild-/Audio-Umwandlung (ffmpeg, Pillow-Alternative laut Ticket nicht nötig) ----------
def webp_data_uri(png_pfad: Path, breite: int = BILD_BREITE, qualitaet: int = BILD_QUALITAET) -> str:
    with tempfile.NamedTemporaryFile(suffix=".webp", dir=str(ct._TMP), delete=False) as tmp:
        ziel = Path(tmp.name)
    try:
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(png_pfad),
                       "-vf", f"scale={breite}:-2", "-quality", str(qualitaet), str(ziel)], check=True)
        daten = ziel.read_bytes()
    finally:
        ziel.unlink(missing_ok=True)
    return "data:image/webp;base64," + base64.b64encode(daten).decode("ascii")


def _verzug_filter(versatz: float) -> str:
    """ffmpeg-Filterausdruck, der ein Audiosignal um `versatz` Sekunden auf die Meetinguhr verschiebt
    (positiv: Stille vorn einfügen: der Inhalt kam auf der Meetinguhr später an als auf seiner eigenen
    Zeitachse; negativ: vorn abschneiden) - siehe cloudtest.py: referenz_verschieben()/die Kommentare zum
    Versatz Referenzzeit↔Meetinguhr."""
    if versatz >= 0:
        return f"adelay={round(versatz * 1000)}:all=1"
    return f"atrim=start={-versatz},asetpts=PTS-STARTPTS"


def audio_mp3_data_uri(meeting_wav: Path, versatz_meeting: float, nestor_wav: Path | None,
                       versatz_nestor: float, dauer_s: float) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(ct._TMP), delete=False) as tmp:
        ziel = Path(tmp.name)
    try:
        eingaben = ["-i", str(meeting_wav)]
        teile = [f"[0:a]{_verzug_filter(versatz_meeting)},volume=1.0[a0]"]
        if nestor_wav is not None and nestor_wav.exists():
            eingaben += ["-i", str(nestor_wav)]
            teile.append(f"[1:a]{_verzug_filter(versatz_nestor)},volume={NESTOR_LAUTER_DB}[a1]")
            mix = (f"[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                  f"alimiter=limit=0.95,apad,atrim=0:{dauer_s},asetpts=PTS-STARTPTS[aus]")
        else:
            mix = f"[a0]apad,atrim=0:{dauer_s},asetpts=PTS-STARTPTS[aus]"
        filtergraph = ";".join(teile + [mix])
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *eingaben, "-filter_complex", filtergraph,
                       "-map", "[aus]", "-c:a", "libmp3lame", "-b:a", AUDIO_KBIT, str(ziel)], check=True)
        daten = ziel.read_bytes()
    finally:
        ziel.unlink(missing_ok=True)
    return "data:audio/mpeg;base64," + base64.b64encode(daten).decode("ascii")


# ---------- Referenzen zu den Testmaterialien (Drehbuch/Audio) aus dem Dateinamen der referenz.json ----------
def meeting_wav_zu(referenz_pfad: Path) -> Path:
    """`referenz_grenzfaelle.json` → `meeting_grenzfaelle.wav`, `referenz.json` → `meeting.wav`
    (docs/cloudtest.md: beide Testmaterialien teilen dasselbe Namensschema)."""
    return referenz_pfad.parent / (referenz_pfad.stem.replace("referenz", "meeting", 1) + ".wav")


# ---------- HTML ----------
STATUS_FARBE = {"ok": "#2e7d32", "fehlt": "#c62828", "beobachtet": "#6b6b6b", "offline": "#b8860b",
                "bedienung": "#7c3aed"}
STATUS_ZEICHEN = {"ok": "✅", "fehlt": "❌", "beobachtet": "📝", "offline": "⏭️", "bedienung": "👆"}


def _esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def kennzahlen_tabelle_html(kennzahlen: list[tuple[str, ...]]) -> str:
    if not kennzahlen:
        return "<p class='leise'>Keine bewertung.md gefunden – nur Ablauf und Screenshots.</p>"
    zeilen = "".join(f"<tr><td>{_esc(n)}</td><td>{_esc(w)}</td></tr>" for n, w in kennzahlen)
    return f"<table class='kennzahlen'><tbody>{zeilen}</tbody></table>"


def urteile_html(urteile: list[tuple[str, ...]], urteile_text: str | None) -> str:
    if urteile_text:
        return f"<p class='leise'>{_esc(urteile_text)}</p>"
    if not urteile:
        return ""
    zeilen = "".join(f"<tr><td>{_esc(k)}</td><td class='note'>{_esc(n)}</td><td>{_esc(b)}</td></tr>"
                     for k, n, b in urteile)
    return (f"<table class='urteile'><thead><tr><th>Kriterium</th><th>Note</th><th>Begründung</th></tr>"
           f"</thead><tbody>{zeilen}</tbody></table>")


_MD_FETT_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_LINK_RE = re.compile(r"\(\[([^\]]+)\]\([^)]+\)\)")


def _markdown_zeile_zu_html(zeile: str) -> str:
    """bewertung.md-Zeilen sind einfaches, festes Markdown (bewertung_schreiben() in cloudtest_bewerten.py:
    `**Name**` + optional `([Bild](screenshots/Bild.png))`) - hier nur das Bisschen nachgebildet statt eine
    Markdown-Bibliothek einzubinden. Der Screenshot-Link bleibt als Namensangabe, nicht als <a> auf eine Datei
    außerhalb dieser einen HTML-Datei (Ticket #19: "eine Datei, alles eingebettet")."""
    escaped = _esc(zeile)
    escaped = _MD_LINK_RE.sub(lambda m: f"(Screenshot: {_esc(m.group(1))})", escaped)
    escaped = _MD_FETT_RE.sub(r"<strong>\1</strong>", escaped)
    return escaped


def schlimmste_html(schlimmste: list[str]) -> str:
    if not schlimmste:
        return "<p class='leise'>Keine ❌-Prüfpunkte in diesem Lauf.</p>"
    return "<ul class='schlimmste'>" + "".join(f"<li>{_markdown_zeile_zu_html(s)}</li>" for s in schlimmste) + "</ul>"


def marken_html(marken: list[dict], dauer_s: float) -> str:
    aus = []
    for m in marken:
        prozent = max(0.0, min(100.0, m["t"] / dauer_s * 100)) if dauer_s else 0.0
        farbe = STATUS_FARBE.get(m["status"], "#888")
        zeichen = STATUS_ZEICHEN.get(m["status"], "•")
        titel = f"{m['label']} – {ct.mmss(m['t'])} – {zeichen} {m['detail']}"
        klasse = "marke marke-ereignis" + (" marke-bedienung" if m.get("art") == "bedienung" else "")
        aus.append(f"<button type='button' class='{klasse}' style='left:{prozent:.3f}%;"
                   f"--farbe:{farbe}' data-t='{m['t']:.2f}' data-label='{_esc(m['label'])}' "
                   f"data-status='{_esc(m['status'])}' data-detail='{_esc(m['detail'])}' "
                   f"title='{_esc(titel)}'>{zeichen}</button>")
    return "".join(aus)


def dashboard_marken_html(dashboard: list[tuple[str, float]], dauer_s: float) -> str:
    aus = []
    for idx, (name, sek) in enumerate(dashboard):
        prozent = max(0.0, min(100.0, sek / dauer_s * 100)) if dauer_s else 0.0
        aus.append(f"<button type='button' class='marke marke-screenshot' style='left:{prozent:.3f}%' "
                   f"data-index='{idx}' data-t='{sek:.2f}' title='{ct.mmss(sek)}'></button>")
    return "".join(aus)


CSS = """
:root{--bg:#f7f7f8;--fg:#1b1b1f;--karte:#ffffff;--rand:#dcdce0;--leise:#6b6b6b;--akzent:#2563eb;
  --spur:#e3e3e8;}
@media (prefers-color-scheme: dark){
  :root{--bg:#15161a;--fg:#e8e8ec;--karte:#1f2026;--rand:#33343c;--leise:#9a9aa4;--akzent:#60a5fa;
    --spur:#2b2c33;}}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,BlinkMacSystemFont,
  "Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
header{padding:16px 16px 4px;}
header h1{font-size:1.2rem;margin:0 0 4px;}
header p{margin:0;color:var(--leise);font-size:.9rem;}
main{display:flex;flex-direction:column;gap:16px;padding:16px;max-width:980px;margin:0 auto;}
section.karte{background:var(--karte);border:1px solid var(--rand);border-radius:12px;padding:14px 16px;}
section.karte h2{font-size:1rem;margin:0 0 10px;}
.leise{color:var(--leise);margin:0;}
#viewer-rahmen{background:#000;border-radius:10px;overflow:hidden;line-height:0;}
#viewer{width:100%;display:block;background:#000;}
audio{width:100%;margin-top:10px;}
#zeitstrahl-wrap{overflow-x:auto;margin-top:14px;padding-bottom:6px;}
#zeitstrahl{position:relative;height:80px;min-width:100%;}
.spur{position:absolute;left:0;right:0;height:6px;background:var(--spur);border-radius:3px;}
.spur-screenshots{top:6px;}
.spur-ereignisse{top:32px;}
.spur-bedienung{top:58px;}
.marke-ereignis.marke-bedienung{top:50px;border-radius:5px;}
.marke{position:absolute;transform:translateX(-50%);border:none;cursor:pointer;padding:0;
  background:none;font-size:13px;line-height:1;}
.marke-screenshot{top:2px;width:10px;height:10px;border-radius:50%;background:var(--akzent);
  box-shadow:0 0 0 2px var(--karte);}
.marke-screenshot:hover,.marke-screenshot:focus{transform:translateX(-50%) scale(1.5);}
.marke-ereignis{top:22px;width:20px;height:20px;border-radius:50%;background:var(--farbe);
  color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 0 0 2px var(--karte);}
.marke-ereignis:hover,.marke-ereignis:focus{transform:translateX(-50%) scale(1.25);}
#vorschau{position:absolute;bottom:60px;transform:translateX(-50%);background:var(--karte);
  border:1px solid var(--rand);border-radius:8px;padding:4px;box-shadow:0 4px 12px rgba(0,0,0,.25);
  z-index:5;pointer-events:none;}
#vorschau img{width:180px;display:block;border-radius:4px;}
#vorschau span{display:block;text-align:center;font-size:.8rem;color:var(--leise);margin-top:2px;}
#status-zeile{margin-top:10px;font-size:.88rem;min-height:1.3em;color:var(--leise);}
table{width:100%;border-collapse:collapse;font-size:.9rem;}
table td,table th{padding:5px 8px;border-bottom:1px solid var(--rand);text-align:left;vertical-align:top;}
table.urteile .note{font-weight:600;text-align:center;}
ul.schlimmste{margin:0;padding-left:18px;}
ul.schlimmste li{margin-bottom:6px;}
.legende{display:flex;gap:14px;flex-wrap:wrap;font-size:.82rem;color:var(--leise);margin-top:8px;}
.legende span{display:inline-flex;align-items:center;gap:4px;}
.legende i{width:12px;height:12px;border-radius:50%;display:inline-block;}
#sonstige{display:flex;gap:10px;flex-wrap:wrap;}
#sonstige figure{margin:0;width:160px;}
#sonstige img{width:100%;border-radius:6px;border:1px solid var(--rand);}
#sonstige figcaption{font-size:.78rem;color:var(--leise);text-align:center;margin-top:3px;}
@media (max-width:480px){
  header{padding:12px 12px 2px;}
  main{padding:12px;gap:12px;}
  #vorschau img{width:130px;}
}
"""


def html_bauen(*, bericht: dict, bewertung: dict | None, marken: list[dict], dashboard: list[tuple[str, float]],
               dashboard_bilder: list[str], sonstige_bilder: dict[str, str], audio_uri: str,
               versatz_hinweis: str, dauer_s: float) -> str:
    modus = bericht["messwerte"].get("modus", "?")
    gestartet = bericht["messwerte"].get("gestartet", "?")
    kopf_zeile = (bewertung or {}).get("kopf") or f"Gestartet {gestartet} · Dauer {dauer_s:.0f} s"
    legende = "".join(
        f"<span><i style='background:{farbe}'></i>{STATUS_ZEICHEN[s]} {s}</span>"
        for s, farbe in STATUS_FARBE.items())
    start_bild = dashboard_bilder[0] if dashboard_bilder else sonstige_bilder.get("startseite", "")
    abschluss_bild = sonstige_bilder.get("abschluss", start_bild)
    dashboard_js = json.dumps([{"t": sek, "i": i} for i, (_, sek) in enumerate(dashboard)])
    dashboard_bilder_js = json.dumps(dashboard_bilder)

    _BESCHRIFTUNG = {"startseite": "Startseite", "agenda-tabelle": "Agenda-Tabelle", "abschluss": "Abschluss"}
    sonstige_html = "".join(
        f"<figure><img src='{uri}' alt='{_esc(name)}' loading='lazy'>"
        f"<figcaption>{_esc(_BESCHRIFTUNG.get(name, name))}</figcaption></figure>"
        for name, uri in sonstige_bilder.items())

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cloud-Testlauf – {_esc(modus)}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Cloud-Testlauf – {_esc(modus)}</h1>
  <p>{_esc(kopf_zeile)}{(" · " + _esc(versatz_hinweis)) if versatz_hinweis else ""}</p>
</header>
<main>
  <section class="karte">
    <div id="viewer-rahmen"><img id="viewer" src="{start_bild}" alt="Dashboard-Screenshot"></div>
    <audio id="player" controls preload="metadata"><source src="{audio_uri}" type="audio/mpeg"></audio>
    <div id="zeitstrahl-wrap">
      <div id="zeitstrahl">
        <div class="spur spur-screenshots"></div>
        <div class="spur spur-ereignisse"></div>
        <div class="spur spur-bedienung"></div>
        {dashboard_marken_html(dashboard, dauer_s)}
        {marken_html(marken, dauer_s)}
        <div id="vorschau" hidden><img id="vorschau-bild" alt=""><span id="vorschau-zeit"></span></div>
      </div>
    </div>
    <div id="status-zeile">Bereit – Zeitstrahl: Screenshots (blaue Punkte), Ereignisse/Grenzfälle
      (✅/❌/📝/⏭️), Bedienung des Tests (👆 violett: Sprechtaste, Knöpfe, Band, ✕, Still).</div>
    <div class="legende">{legende}</div>
  </section>

  <section class="karte">
    <h2>Kennzahlen</h2>
    {kennzahlen_tabelle_html((bewertung or {}).get("kennzahlen", []))}
  </section>

  <section class="karte">
    <h2>Urteile</h2>
    {urteile_html((bewertung or {}).get("urteile", []), (bewertung or {}).get("urteile_text"))}
  </section>

  <section class="karte">
    <h2>Die schlimmsten Stellen</h2>
    {schlimmste_html((bewertung or {}).get("schlimmste", []))}
  </section>

  {f'<section class="karte"><h2>Weitere Bilder</h2><div id="sonstige">{sonstige_html}</div></section>'
   if sonstige_html else ''}
</main>
<script>
(function() {{
  "use strict";
  var DASHBOARD_ZEITEN = {dashboard_js};          // [{{t, i}}], aufsteigend
  var DASHBOARD_BILDER = {dashboard_bilder_js};   // Index -> WebP-Data-URI
  var ABSCHLUSS_BILD = {json.dumps(abschluss_bild)};
  var MEETING_DAUER = {dauer_s:.2f};
  var player = document.getElementById("player");
  var viewer = document.getElementById("viewer");
  var status = document.getElementById("status-zeile");
  var vorschau = document.getElementById("vorschau");
  var vorschauBild = document.getElementById("vorschau-bild");
  var vorschauZeit = document.getElementById("vorschau-zeit");
  var zeitstrahl = document.getElementById("zeitstrahl");

  function mmss(s) {{
    s = Math.max(0, Math.round(s));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }}

  function bildFuerZeit(t) {{
    if (MEETING_DAUER && t >= MEETING_DAUER - 0.5) return ABSCHLUSS_BILD;
    var gewaehlt = DASHBOARD_BILDER.length ? DASHBOARD_BILDER[0] : ABSCHLUSS_BILD;
    for (var k = 0; k < DASHBOARD_ZEITEN.length; k++) {{
      if (DASHBOARD_ZEITEN[k].t <= t) gewaehlt = DASHBOARD_BILDER[DASHBOARD_ZEITEN[k].i];
      else break;
    }}
    return gewaehlt;
  }}

  function setViewer(src) {{
    if (src && viewer.getAttribute("data-aktuell") !== src) {{
      viewer.src = src;
      viewer.setAttribute("data-aktuell", src);
    }}
  }}

  function springeZu(t) {{
    player.currentTime = t;
    setViewer(bildFuerZeit(t));
  }}

  player.addEventListener("timeupdate", function() {{ setViewer(bildFuerZeit(player.currentTime)); }});

  zeitstrahl.querySelectorAll(".marke-screenshot").forEach(function(knopf) {{
    var idx = parseInt(knopf.dataset.index, 10);
    var t = parseFloat(knopf.dataset.t);
    var bild = DASHBOARD_BILDER[idx];
    function zeigen() {{
      vorschauBild.src = bild;
      vorschauZeit.textContent = mmss(t);
      vorschau.style.left = knopf.style.left;
      vorschau.hidden = false;
      status.textContent = "Screenshot bei " + mmss(t) + " – anklicken springt im Audio dorthin.";
    }}
    function verbergen() {{ vorschau.hidden = true; }}
    knopf.addEventListener("mouseenter", zeigen);
    knopf.addEventListener("focus", zeigen);
    knopf.addEventListener("mouseleave", verbergen);
    knopf.addEventListener("blur", verbergen);
    knopf.addEventListener("click", function() {{ springeZu(t); }});
  }});

  zeitstrahl.querySelectorAll(".marke-ereignis").forEach(function(knopf) {{
    var t = parseFloat(knopf.dataset.t);
    function zeigen() {{
      status.textContent = mmss(t) + " · " + knopf.dataset.label + " – " +
        knopf.dataset.status + ": " + knopf.dataset.detail;
    }}
    knopf.addEventListener("mouseenter", zeigen);
    knopf.addEventListener("focus", zeigen);
    knopf.addEventListener("click", function() {{ springeZu(t); zeigen(); }});
  }});

  // Test-Haken für die automatisierte Playwright-Prüfung (Ticket #19) - keine öffentliche API, nur zum
  // Nachstellen von Klick/Zeitwechsel ohne echte Audiowiedergabe im headless Lauf.
  window.__cloudtestBericht = {{
    springeZu: springeZu, bildFuerZeit: bildFuerZeit,
    aktuellesBild: function() {{ return viewer.getAttribute("data-aktuell"); }},
  }};
}})();
</script>
</body>
</html>
"""


# ---------- Orchestrierung ----------
def erzeugen(ordner: Path) -> Path:
    bericht = json.loads((ordner / "bericht.json").read_text(encoding="utf-8"))
    frames_pfad = ordner / "ws.jsonl"
    frames = []
    if frames_pfad.exists():
        frames = [json.loads(z) for z in frames_pfad.read_text(encoding="utf-8").splitlines() if z.strip()]

    marken, versatz_meeting = marken_und_versatz(bericht, frames)
    versatz_nestor = nestor_versatz_schaetzen(frames)
    plan, uhr = ct.meeting_plan(bericht["messwerte"], ct.zustaende_aus_frames(frames)) if frames else (None, None)
    if plan:
        versatz_nestor = uhr  # gleiche Achse wie der Meeting-Ton, siehe unten
    dauer_s = bericht["messwerte"].get("meeting_s") or (max((m["t"] for m in marken), default=600.0) + 60.0)

    referenz_pfad_str = bericht["messwerte"].get("referenz_datei")
    audio_uri = ""
    versatz_hinweise = []
    if referenz_pfad_str and Path(referenz_pfad_str).exists():
        meeting_wav = meeting_wav_zu(Path(referenz_pfad_str))
        if meeting_wav.exists():
            v_meeting = versatz_meeting or 0.0
            nestor_wav = ordner / "nestor_stimme.wav"
            v_nestor = versatz_nestor if (versatz_nestor is not None and nestor_wav.exists()) else 0.0
            zusammen = None
            if plan:
                # #25: Meeting-Ton so, wie er im Browser lief - Abschnitte am Zeitplan, dazwischen die Pausen.
                # Beide Spuren hängen an derselben Laufachse (Zeitplan und stimme-Ankunft), verschoben um
                # Meetinguhr − Laufachse - daher kein eigener Versatz für den Meeting-Ton mehr.
                zusammen = Path(ct._TMP) / f"meeting_takt_{os.getpid()}.wav"
                ct.takt.wav_schreiben(zusammen, ct.takt.meeting_spur(ct.takt.wav_laden(meeting_wav), plan, dauer_s))
                meeting_wav, v_meeting = zusammen, 0.0
            try:
                audio_uri = audio_mp3_data_uri(meeting_wav, v_meeting,
                                               nestor_wav if nestor_wav.exists() else None, v_nestor, dauer_s)
            finally:
                if zusammen is not None:
                    zusammen.unlink(missing_ok=True)
            versatz_hinweise.append("Meeting-Ton nach Zeitplan mit Pausen" if plan
                                    else f"Versatz Meeting-Ton {v_meeting:+.1f}s")
            if nestor_wav.exists():
                versatz_hinweise.append(
                    f"Nestor-Stimme {v_nestor:+.1f}s" if versatz_nestor is not None
                    else "Nestor-Stimme ohne messbaren Versatz (unverschoben gemischt)")
            else:
                versatz_hinweise.append("ohne Nestor-Stimme (nur auf Knopfdruck: keine spontane Ansprache)")
        else:
            versatz_hinweise.append(f"Meeting-Ton fehlt ({meeting_wav})")
    else:
        versatz_hinweise.append("referenz.json nicht gefunden – kein Audio eingebettet")

    dashboard, sonstige_namen = screenshots_einordnen(bericht)
    screenshots_dir = ordner / "screenshots"
    dashboard_bilder = [webp_data_uri(screenshots_dir / f"{name}.png") for name, _ in dashboard
                        if (screenshots_dir / f"{name}.png").exists()]
    sonstige_bilder = {name: webp_data_uri(screenshots_dir / f"{name}.png")
                      for name in sonstige_namen if (screenshots_dir / f"{name}.png").exists()}

    bewertung = bewertung_md_parsen(ordner / "bewertung.md")

    seite = html_bauen(bericht=bericht, bewertung=bewertung, marken=marken, dashboard=dashboard,
                       dashboard_bilder=dashboard_bilder, sonstige_bilder=sonstige_bilder, audio_uri=audio_uri,
                       versatz_hinweis="; ".join(versatz_hinweise), dauer_s=dauer_s)
    ziel = ordner / "bericht.html"
    ziel.write_text(seite, encoding="utf-8")
    return ziel


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lauf", help="Berichtordner eines scripts/cloudtest.py-Laufs (enthält bericht.json)")
    args = ap.parse_args()
    ziel = erzeugen(Path(args.lauf))
    groesse_mb = ziel.stat().st_size / 1_000_000
    print(f"Bericht: {ziel} ({groesse_mb:.1f} MB)")


if __name__ == "__main__":
    main()
