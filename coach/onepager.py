"""Live-Bild des Meetings als One-Pager (FR-10), gezeichnet von Claude über das Abo (Claude Code CLI).

Verfahren aus dem Teachbuddy-Grafikvergleich (11.09.2026): Die Qualität hängt an der
Strukturanalyse VOR dem Zeichnen, nicht am Renderer. Darum zwei Schritte:
1. Strukturanalyse: Kernaussage, Themen mit festen Kennungen, Entscheidungen, Offenes, Beziehungen.
2. Zeichnen: ein einziges, in sich geschlossenes SVG in einem festen Grundraster.

Fortschreibung: Ab dem zweiten Bild bekommt Claude die letzte Analyse und das letzte SVG und
schreibt beides fort – gleiche Themen an gleicher Stelle, Neues kommt dazu und ist markiert.
So entwickelt sich das Bild sichtbar weiter, statt jedes Mal neu entworfen zu werden.

Claude läuft als `claude -p` – lokal oder per SSH auf einem Rechner mit angemeldetem Abo
(Einstellung LMC_CLAUDE_BEFEHL). Es entstehen keine API-Kosten, aber Abo-Kontingent.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex

from .analyse import mmss
from .config import EINST
from .zustand import Meeting

MAX_TRANSKRIPT_ZEICHEN = 30000

GESTALTUNG = """\
GESTALTUNGSSYSTEM (verbindlich, damit alle Bilder gleich aussehen):
- Leinwand: genau 1600 × 1000 px, viewBox="0 0 1600 1000". Nichts darf darüber hinausragen.
- Hintergrund #F8FAFC. Karten weiß (#FFFFFF), Rand #E2E8F0, Ecken 14 px, keine Schlagschatten.
- Schrift: font-family "Inter, Segoe UI, system-ui, sans-serif". Titel 36 px fett #0F172A,
  Untertitel 20 px #475569, Kartentitel 20 px fett, Fließtext mindestens 16 px #334155.
- Farbcodierung (sparsam, mit Bedeutung): Blau #2563EB = aktuell/Thema · Grün #059669 = entschieden ·
  Bernstein #D97706 = offen/strittig · Rot #DC2626 = Risiko/Konflikt (nur wenn wirklich vorhanden) ·
  Grau #94A3B8 = außerhalb der Agenda.
- Icons: schlichte Linien-Icons (stroke 2.5, keine Cliparts), selbst als <path>/<circle>/<rect> gezeichnet.
- Ruhig und sachlich wie eine moderne Tech-Firmen-App: viel Weißraum, klares Raster, keine Deko ohne Inhalt.
- Text nur in <text>/<tspan>; Zeilen selbst umbrechen (max. ~45 Zeichen je Zeile bei 16 px in 420 px Breite).
- Keine externen Ressourcen, keine Bilder, keine Skripte, kein <foreignObject>.

GRUNDRASTER (fest – jedes Bild hat diese Zonen an dieser Stelle, damit man den Fortschritt sieht):
- Kopf (y 30–120): links Titel, darunter die Kernaussage als Untertitel; rechts der Stand (Laufzeit).
- Agenda-Leiste (y 140–210): alle Agendapunkte als gleich breite Segmente in einer Reihe, Nummer + Kurztitel.
  erledigt = grün, Haken rechts im Segment (nicht über dem Text) · aktuell = blau gefüllt mit „JETZT“ ·
  offen = weiß, grauer Rand.
- Themenkarte (x 40–1060, y 240–800): die Themen als Karten mit Icon, Status-Farbstreifen links und
  Kernaussage; Beziehungen als beschriftete dünne Linien/Pfeile zwischen den Karten. Höchstens 6 Karten
  auf festen Plätzen im 2×3-Raster: Platz 1 oben links, Platz 2 oben rechts, Platz 3 Mitte links usw.
- Rechte Spalte (x 1100–1560): oben „Entschieden“ (grüne Haken-Liste mit Ergebnis), darunter „Offen“
  (bernsteinfarbene Liste mit Fragen und Aufgaben).
- Fußleiste (y 830–970): links „Außerhalb der Agenda“ (grau, gestrichelter Rand; leer = „keine Abschweifung“),
  Mitte „Neu seit dem letzten Bild“ (1–3 kurze Zeilen), rechts eine kleine Farblegende.
"""

ANALYSE_AUFTRAG = """\
Du bereitest ein Live-Bild eines laufenden Meetings vor: einen One-Pager, der auf einen Blick zeigt,
wo das Meeting steht, was entschieden ist, was offen ist und wie die Themen zusammenhängen.
Kein Protokoll – eine Grafik. Das Layout ist fest (siehe Grundraster), du lieferst nur den Inhalt.

Antworte NUR mit dieser Analyse in knappem Markdown, genau diese Abschnitte:
1. Kernaussage – ein Satz, höchstens 15 Wörter: Wo steht das Meeting gerade? (Stand, nicht „es ging um X“.)
2. Themen – höchstens 6, je Zeile: `T<n> | Platz <n> | Agendapunkt <n> oder außerhalb | Status
   (besprochen/entschieden/offen/strittig/aktuell) | Stichwort (2–4 Wörter) | Kernaussage (≤ 12 Wörter) | Icon (1–2 Wörter)`.
   Zusammengehöriges zusammenfassen; erledigte Punkte dürfen zu einer Karte verdichtet werden.
3. Entscheidungen – nur ausdrücklich Beschlossenes, je Zeile mit Ergebnis (z. B. „einstimmig“). Sonst „keine“.
4. Offen – nur ausdrücklich genannte Fragen und Aufgaben; wer/bis wann nur, wenn gesagt. Höchstens 4.
5. Beziehungen – höchstens 4, je Zeile `T<a> → T<b>: Art (≤ 4 Wörter)`.
6. Außerhalb der Agenda – inhaltliche Gesprächsteile ohne Bezug zur Agenda mit Zeitraum, sonst „keine“.
   Das ist ein wichtiges Signal für die Gruppe, auch wenn es nur kurz war.
7. Neu seit dem letzten Bild – 1 bis 3 kurze Zeilen (beim ersten Bild: „erstes Bild“).

Regeln: Nur was im Transkript steht. Zahlen nur, wenn sie dort genannt sind. Keine Bewertung von Personen.
Sprecher heißen „Person N“. Deutsch, Dezimalkomma.
{fortschreibung}
{gestaltung}
"""

FORTSCHREIBUNG_ANALYSE = """\
FORTSCHREIBUNG: Es gibt schon ein Bild (Analyse unten). Schreibe es fort, statt neu zu entwerfen:
gleiche Kennungen T<n>, gleiche Plätze, gleiche Stichworte und Icons für bestehende Themen. Ändere nur
Status und Kernaussage, wo sich etwas getan hat. Neue Themen bekommen die nächste freie Kennung und den
nächsten freien Platz; wird es zu voll, verdichte die ältesten erledigten Themen zu einer Karte.

LETZTE ANALYSE:
{vorher}
"""

ZEICHEN_AUFTRAG = """\
Zeichne aus der folgenden Strukturanalyse den One-Pager als EIN in sich geschlossenes SVG im Grundraster.
Zeige Beziehungen sichtbar (Linien, Gruppierung, Farbstreifen), nicht nur Text in Kästen.
Prüfe vor der Ausgabe gedanklich jede Textzeile auf Überlauf aus ihrer Karte und aus der Leinwand.
Oben rechts steht genau: „Stand {stand}“.
{fortschreibung}
Antworte NUR mit dem SVG, beginnend mit <svg und endend mit </svg>. Kein Markdown, keine Erklärung.

{gestaltung}

STRUKTURANALYSE:
{analyse}
"""

FORTSCHREIBUNG_ZEICHNEN = """\
FORTSCHREIBUNG: Unten steht das letzte Bild. Aktualisiere es, statt neu zu zeichnen: Aufbau, Koordinaten,
Größen und Icons bestehender Karten bleiben gleich; ändere nur Texte, Status-Farben und die Agenda-Leiste.
Neue Themen kommen an ihren Platz und tragen oben rechts ein kleines blaues Etikett „neu“; entferne die
„neu“-Etiketten des letzten Bildes.

LETZTES BILD:
{vorher_svg}
"""


def meeting_text(meeting: Meeting) -> str:
    zeilen = [f"Titel: {meeting.titel or '-'}", f"Ziel: {meeting.ziel or '-'}",
              f"Laufzeit bisher: {mmss(meeting.jetzt())} Minuten", "", "Agenda:"]
    for i, p in enumerate(meeting.agenda, start=1):
        zeilen.append(f"{i}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "")
                      + f" [{meeting.status(i - 1)}]")
    transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in meeting.transkript if s.text)
    zeilen += ["", "Transkript:", transkript[-MAX_TRANSKRIPT_ZEICHEN:]]
    return "\n".join(zeilen)


class ClaudeFehler(RuntimeError):
    pass


async def claude(auftrag: str, modell: str, aufwand: str = "", zeitlimit: float = 600) -> tuple[str, dict]:
    """Ein Aufruf `claude -p` (Abo). Der Auftrag geht über stdin, die Antwort kommt als JSON über stdout.

    Ohne Einstellungsdateien, MCP-Server und Werkzeuge: Dadurch laufen die Hooks des Zielrechners
    (Gedächtnis, Protokolle) nicht mit – Meetinginhalte landen dort nicht –, und der Grundkontext
    schrumpft von ~34 000 auf ~3 000 Tokens. Liefert (Text, Messwerte).
    """
    befehl = shlex.split(EINST.claude_befehl, posix=True) + [
        "-p", "--model", modell, "--output-format", "json",
        # leere Werte mit „=“, damit sie auch über ssh (Zeile geht durch eine Shell) ankommen
        "--setting-sources=", "--strict-mcp-config", "--tools=", "--no-session-persistence",
    ] + (["--effort", aufwand] if aufwand else [])
    proc = await asyncio.create_subprocess_exec(
        *befehl, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(auftrag.encode("utf-8")), zeitlimit)
    except asyncio.TimeoutError:
        proc.kill()
        raise ClaudeFehler(f"Zeitlimit {zeitlimit:.0f}s überschritten") from None
    if proc.returncode != 0:
        raise ClaudeFehler((err or out).decode("utf-8", "replace").strip()[:200] or f"Exit {proc.returncode}")
    try:
        erg = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise ClaudeFehler("Antwort von claude ist kein JSON") from None
    if erg.get("is_error"):
        raise ClaudeFehler(str(erg.get("result", "Fehler"))[:200])
    nutzung = erg.get("usage") or {}
    messung = {
        "modell": modell, "sekunden": round(erg.get("duration_ms", 0) / 1000, 1),
        "tokens_raus": nutzung.get("output_tokens"),
        "denk_tokens": (nutzung.get("output_tokens_details") or {}).get("thinking_tokens"),
        "tokens_rein": (nutzung.get("input_tokens") or 0) + (nutzung.get("cache_read_input_tokens") or 0)
        + (nutzung.get("cache_creation_input_tokens") or 0),
    }
    return str(erg.get("result", "")).strip(), messung


def svg_herausloesen(antwort: str) -> str:
    treffer = re.search(r"<svg[\s\S]*</svg>", antwort)
    if not treffer:
        raise ClaudeFehler("Antwort enthält kein SVG")
    svg = treffer.group(0)
    # Sicherheit: das SVG wird ins Dashboard eingebettet – keine Skripte, keine Ereignis-Attribute, nichts Externes
    svg = re.sub(r"<script[\s\S]*?</script>", "", svg, flags=re.I)
    svg = re.sub(r"<foreignObject[\s\S]*?</foreignObject>", "", svg, flags=re.I)
    svg = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", svg, flags=re.I)
    svg = re.sub(r"(href\s*=\s*[\"'])(?!#)[^\"']*([\"'])", r"\1#\2", svg, flags=re.I)
    return svg


FOKUS_AUFTRAG = """FOKUS DIESES BILDES (auf Wunsch der Gruppe): {fokus}
Zeige nur, was zu diesem Fokus gehört, dafür ausführlicher. Kopf und Agenda-Leiste bleiben wie im Grundraster
(der Fokus wird in der Agenda-Leiste hervorgehoben); die übrigen Zonen dürfen für den Fokus umgenutzt werden.
Schreibe den Fokus als Untertitel in den Kopf.
"""


async def erzeugen(meeting: Meeting, vorher: dict | None = None, fokus: str | None = None) -> dict:
    """Strukturanalyse + Zeichnung, auf Wunsch als Fortschreibung des letzten Bildes ({analyse, svg})
    oder mit einem Fokus (z. B. „Agendapunkt 2“, „was noch ansteht“, „wo Entscheidungen fehlen“).

    Liefert {analyse, svg, messung}.
    """
    daten = meeting_text(meeting)
    fort_a = FORTSCHREIBUNG_ANALYSE.format(vorher=vorher["analyse"]) if vorher else ""
    if fokus:
        fort_a = FOKUS_AUFTRAG.format(fokus=fokus)
    analyse, m1 = await claude(
        ANALYSE_AUFTRAG.format(gestaltung=GESTALTUNG, fortschreibung=fort_a) + "\n\nMEETING:\n" + daten,
        EINST.onepager_analyse_modell, EINST.onepager_analyse_aufwand)
    fort_z = FORTSCHREIBUNG_ZEICHNEN.format(vorher_svg=vorher["svg"]) if vorher else ""
    if fokus:
        fort_z = FOKUS_AUFTRAG.format(fokus=fokus)
    antwort, m2 = await claude(
        ZEICHEN_AUFTRAG.format(gestaltung=GESTALTUNG, analyse=analyse, fortschreibung=fort_z,
                               stand=mmss(meeting.jetzt())),
        EINST.onepager_zeichen_modell, EINST.onepager_zeichen_aufwand)
    return {"analyse": analyse, "svg": svg_herausloesen(antwort), "messung": [m1, m2]}
