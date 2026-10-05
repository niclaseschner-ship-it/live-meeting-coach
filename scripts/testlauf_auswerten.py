r"""Testlauf auswerten: Berichte aus scripts/abspielen.py gegen Referenz und Nestor-Einschübe prüfen.

    .venv\Scripts\python scripts\testlauf_auswerten.py docs\testlauf_2026-10-05.md koblenz_rat_nestor …

Liest logs/bericht_<name>.json, testbibliothek/audio/<name>.einschuebe.json und die probe.json der Quelle.
Schreibt ein Markdown-Protokoll: je Probe Agenda-Wechsel gegen die Kapitelmarken, jede Frage an Nestor mit
Antwort, Verzug und Karte, Hinweise, Ergebnisse, Live-Bilder, Kosten. Ohne Transkript (fremde Inhalte) –
das liegt nur lokal in logs/.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AUDIO = WURZEL / "testbibliothek" / "audio"
PROBEN = WURZEL / "testbibliothek" / "proben"


def mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def abbilden(t: float, ein: dict) -> float:
    """Zeitpunkt der Quelle -> Zeitpunkt in der Aufnahme mit Einschüben."""
    v = ein["vorlauf"]
    for s in ein["schnitte"]:
        if t >= s["ab_quelle"]:
            v = s["versatz"]
    return t - ein["quelle_von"] + v


def probe_auswerten(name: str) -> tuple[list[str], dict]:
    b = json.loads((WURZEL / "logs" / f"bericht_{name}.json").read_text(encoding="utf-8"))
    ein = json.loads((AUDIO / f"{name}.einschuebe.json").read_text(encoding="utf-8"))
    probe = json.loads((PROBEN / ein["probe"] / "probe.json").read_text(encoding="utf-8"))
    tempo = b.get("tempo", 1)
    prot = b["protokoll"]
    dauer = max([s["ende"] for s in b["transkript"]] + [0])
    z = [f"## {probe['titel']}", "",
         f"Quelle: {probe['quelle']['url']} ({mmss(probe['quelle']['von'])}–{mmss(probe['quelle']['bis'])}), "
         f"{probe.get('setting', '')}. Aufnahme mit Einschüben {mmss(dauer)} min, abgespielt mit Tempo {tempo}, "
         f"Live-Text „{b['einstellungen'].get('live_art')}“, Nestor im Modus „{b['einstellungen'].get('modus')}“.", ""]

    # Personen und Redeanteile
    anteile = sorted(b["redeanteile"].items(), key=lambda x: -x[1])
    nennenswert = [p for p, s in anteile if s >= 10]
    z += [f"**Personen:** {len(nennenswert)} mit mindestens 10 s Redezeit ({len(anteile)} Kennungen). "
          f"Größte Anteile: " + ", ".join(f"{p} {mmss(s)}" for p, s in anteile[:4]) + f". **Sätze:** {len(b['transkript'])}.", ""]

    # Agenda gegen Referenz
    erg: dict = {"name": name, "dauer": dauer, "tempo": tempo}
    wechsel = [e for e in prot if e["art"] == "wechsel"]
    ref = probe.get("referenz", {}).get("agenda_wechsel")
    if ref:
        z += ["**Agenda-Wechsel gegen die Kapitelmarken**", "", "| Punkt | Referenz | erkannt | Verzug | durch |", "|---|---|---|---|---|"]
        treffer, verzuege = 0, []
        for t_q, i in ref[1:]:  # der erste Punkt ist von Anfang an aktiv
            t = abbilden(t_q, ein)
            w = next((e for e in wechsel if e["nach"] == i and e["zeit"] >= t - 30), None)
            titel = probe["meeting"]["agenda"][i]["titel"]
            if w:
                d = w["zeit"] - t
                treffer += d <= 120
                verzuege.append(d)
                z.append(f"| {i + 1}. {titel} | {mmss(t)} | {mmss(w['zeit'])} | {d:+.0f} s | {w.get('durch', 'Themen-Zuordnung')} |")
            else:
                z.append(f"| {i + 1}. {titel} | {mmss(t)} | – | – | – |")
        passend = {(e["nach"]) for e in wechsel}
        falsch = [e for e in wechsel if not any(e["nach"] == i for _, i in ref)]
        z += ["", f"{treffer} von {len(ref) - 1} Wechseln innerhalb von 2 min erkannt"
              + (f", Verzug Median {sorted(verzuege)[len(verzuege) // 2]:.0f} s" if verzuege else "")
              + f"; {len(wechsel)} Wechsel insgesamt, davon {len(falsch)} zu Punkten ohne Referenz.", ""]
        erg.update(agenda_treffer=treffer, agenda_soll=len(ref) - 1, wechsel=len(wechsel))
    else:
        z += [f"**Agenda:** keine Referenz; {len(wechsel)} Wechsel: "
              + (", ".join(f"{mmss(e['zeit'])} → {e['nach'] + 1}" for e in wechsel) or "keiner") + ".", ""]
        erg.update(wechsel=len(wechsel))
    z += ["| Agendapunkt | Plan | genutzt |", "|---|---|---|"] + [
        f"| {p['titel']} | {p['minuten']:.0f} min | {mmss(p['genutzt'])} |" for p in b["agenda"]] + [""]

    # Nestor
    antworten = [e for e in prot if e["art"] == "assistent"]
    z += ["**Fragen an Nestor**", "", "| Frage (eingeschnitten) | Antwort nach | Aktion | Karte | Antwort (gekürzt) |", "|---|---|---|---|---|"]
    beantwortet, benutzt = 0, set()

    def worte(t: str) -> set:
        return {w.strip(",.?!„“").lower() for w in (t or "").split() if len(w.strip(",.?!„“")) > 3}

    for e in ein["einschuebe"]:
        kandidaten = [x for x in antworten if e["frage_ende"] - 1 <= x["zeit"] <= e["frage_ende"] + 300
                      and id(x) not in benutzt]
        a = next((x for x in kandidaten if len(worte(x.get("frage")) & worte(e["text"])) >= 2), None) or             next(iter(kandidaten), None)
        if a:
            benutzt.add(id(a))
        rech = next((x for x in prot if x["art"] == "recherche" and e["frage_ende"] - 1 <= x["zeit"] <= e["frage_ende"] + 330), None)
        karte = next((k for k in b.get("karten", []) if e["frage_ende"] - 1 <= k["zeit"] <= e["frage_ende"] + 330), None)
        if a or rech:
            beantwortet += 1
        verzug = f"{((a or rech)['zeit'] - e['frage_ende']) / tempo:.1f} s" if (a or rech) else "keine Antwort"
        aktion = (a or {}).get("aktion")
        aktion = aktion.get("typ") if isinstance(aktion, dict) else ("recherche" if rech else "–")
        text = (a or {}).get("antwort", "") or (f"Recherche, {len(rech['quellen'])} Quellen" if rech else "")
        z.append(f"| {e['text']} | {verzug} | {aktion} | {karte['titel'] if karte else '–'} | {text[:160].replace('|', '/')} |")
    z += ["", f"{beantwortet} von {len(ein['einschuebe'])} Fragen beantwortet. Verzug in Echtzeit (Meetingzeit / Tempo), "
          "gemessen vom Ende der Frage bis die Antwort fertig formuliert ist.", ""]
    ungefragt = [x for x in antworten if id(x) not in benutzt]
    if ungefragt:
        z += [f"**Ungefragt ausgelöst:** {len(ungefragt)}×"] + [
            f"- {mmss(x['zeit'])} erkannt als „{(x.get('frage') or '')[:90]}“ → „{(x.get('antwort') or '')[:90]}“" for x in ungefragt] + [""]
    erg.update(nestor_fragen=len(ein["einschuebe"]), nestor_antworten=beantwortet, ungefragt=len(ungefragt))

    # Hinweise
    arten = Counter(h["art"] for h in b["hinweise"])
    z += [f"**Hinweise an die Runde:** {len(b['hinweise'])} (" + ", ".join(f"{k} {v}" for k, v in arten.most_common()) + ")", ""]
    for h in b["hinweise"][:12]:
        z.append(f"- {mmss(h['zeit'])} [{h['art']}] {h['text'][:150]}")
    if len(b["hinweise"]) > 12:
        z.append(f"- … {len(b['hinweise']) - 12} weitere")
    z.append("")
    erg.update(hinweise=len(b["hinweise"]))

    # Ergebnisse, Bilder, Kosten
    if b.get("ergebnisse"):
        z += ["**Ergebnisse (Regel 10)**", ""]
        for i, e in sorted(b["ergebnisse"].items(), key=lambda x: int(x[0])):
            titel = b["agenda"][int(i)]["titel"]
            z.append(f"- {titel}: {e.get('ergebnis') or '–'} ({len(e.get('entscheidungen', []))} Entscheidungen, "
                     f"{len(e.get('aufgaben', []))} Aufgaben)")
        z.append("")
    bilder = sorted((WURZEL / "logs" / "testlauf" / name).glob("bild_*.png")) if (WURZEL / "logs" / "testlauf" / name).exists() else []
    k = b["kosten"]
    z += [f"**Live-Bilder:** {b['onepager_version']} (gespeichert unter logs/testlauf/{name}/).", "",
          f"**Kosten:** {k['meeting']:.2f} $ – " + ", ".join(f"{x['name']} {x['usd']:.3f} $" for x in k["bereiche"] if x["usd"])
          + (f"; hochgerechnet {k['meeting'] / (dauer / 3600):.2f} $ pro Stunde." if dauer else "."), ""]
    if b.get("fehler"):
        z += [f"**Fehler:** {b['fehler']}", ""]
    erg.update(kosten=k["meeting"], bilder=len(bilder))
    return z, erg


def main() -> None:
    ziel = Path(sys.argv[1])
    teile, uebersicht = [], []
    for name in sys.argv[2:]:
        z, e = probe_auswerten(name)
        teile += z
        uebersicht.append(e)
    kopf = ["| Probe | Dauer | Agenda-Wechsel | Nestor beantwortet | ungefragt | Hinweise | Kosten |", "|---|---|---|---|---|---|---|"]
    for e in uebersicht:
        ag = f"{e['agenda_treffer']}/{e['agenda_soll']}" if "agenda_treffer" in e else f"{e['wechsel']} (ohne Referenz)"
        kopf.append(f"| {e['name']} | {mmss(e['dauer'])} | {ag} | {e['nestor_antworten']}/{e['nestor_fragen']} | {e['ungefragt']} | "
                    f"{e['hinweise']} | {e['kosten']:.2f} $ |")
    summe = sum(e["kosten"] for e in uebersicht)
    stunden = sum(e["dauer"] for e in uebersicht) / 3600
    kopf += ["", f"Zusammen {stunden:.1f} h Aufnahme, {summe:.2f} $ ({summe / stunden:.2f} $ pro Stunde).", ""]
    ziel.write_text("\n".join(["<!-- ÜBERSICHT -->"] + kopf + teile) + "\n", encoding="utf-8")
    print("\n".join(kopf))


if __name__ == "__main__":
    main()
