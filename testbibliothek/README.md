# Testbibliothek

Aufnahmen mit bekannter Wahrheit (Referenz), an denen jeder Baustein des Coaches gemessen wird:
wer spricht, Agenda-Abgleich, Fokus und künftig die Gesprächsregeln
([docs/gespraechsregeln.md](../docs/gespraechsregeln.md)). Neue Verfahren und Schwellen werden hier
gemessen, nicht nach Gefühl eingestellt.

**Intern:** Nur diese Beschreibung liegt im Repo. Proben, Texte und Audio bleiben auf den Rechnern des Teams,
weil sie aus öffentlichen Aufnahmen Dritter stammen. Die freie Demo liegt unter [demo/](../demo/README.md).

## Aufbau

```
testbibliothek/
  proben/<name>/probe.json   Quelle, Zeitfenster, Setting, Meeting-Einrichtung, Referenz, Eignung  (im Git)
  audio/<name>.wav           24 kHz mono, wird hergestellt                                        (nicht im Git)
  audio/<name>.json          Titel und Agenda für den Abspielmodus im Dashboard                    (nicht im Git)
```

Audio herstellen (lädt die öffentlichen Videos, schneidet das Zeitfenster aus und löscht den Download):

```powershell
.venv\Scripts\python scripts\bibliothek_laden.py
```

Danach stehen die Proben im Dashboard unter „Aufnahme abspielen“ (Standardordner von `LMC_AUFNAHMEN`).

## Proben

| Name | Setting | Referenz | Eignung |
|---|---|---|---|
| `zoom_inca4d` | Online-Meeting, eigenes Mikro je Person, geordnet, 6 Personen | Sprecher inhaltlich je Äußerung | Sprecher, Redeanteile, „ausreden lassen“ (geordnet) |
| `stadtrat` | Stadtrat Hoyerswerda, Saalanlage, sehr geordnet, kurze TOPs mit Abstimmung | Sprecher inhaltlich (3 Personen), Agenda aus Kapitelmarken | Sprecher, Agenda, Monolog, Beschlüsse, „ausreden lassen“ (geordnet) |
| `untervier` | TV-Talk, 4 Personen, Wechsel ohne Pause, Unterbrechungen | Sprecher aus OpenAI-Diarisierung, inhaltlich geprüft | Sprecher, Redeanteile, Überlappung, „ausreden lassen“ (wild), Ton |
| `stadtrat_fremd` | `stadtrat` mit 40 s Talkshow bei 4:10 | Fremdthema 250–290 s | Fokus, Agenda |
| `bundestag_ordnungsrufe` | Bundestag, Zusammenschnitt Ordnungsrufe 2024, Zwischenrufe aus dem Saal | 31 Zwischenrufe mit Zeitmarke (Untertitel laut Plenarprotokoll) | „ausreden lassen“ (Zwischenrufe), Ton |
| `ahaus_rat` | Stadtrat Ahaus 29.09.2026, TOP 11 Anträge, anderer Ratssaal | noch keine; Grob-Transkript aus Untertiteln | Sprecher, Monolog, geordnet |
| `freital_buergerversammlung` | Sächsischer Landtag 2015, Aktuelle Debatte (Name historisch, keine Bürgerversammlung) | Sprecher (Diarisierung, inhaltlich getrennt) | Sprecher, Monolog, geordnet |
| `ton_tts` | synthetisch: 14 Sätze, 4 TTS-Stimmen (`scripts/tts_probe.py`) | Klasse je Satz | Ton Ende zu Ende, Kraftausdrücke in der Texterkennung |

Text-Testsets ohne Audio liegen in `texte/` (z. B. `texte/ton.json`, 100 gelabelte Sätze für Regel 7).
Untertitel (Grob-Transkript, Zwischenrufe) lädt `bibliothek_laden.py` mit, wenn `quelle.untertitel` gesetzt ist.

Alle Quellen sind öffentlich zugängliche Videos. Das Audio dient nur lokalen Tests und wird nicht
weitergegeben; deshalb liegt es nicht im Repository.

## Messwerkzeuge

| Skript | misst |
|---|---|
| `scripts/bench_sprecher.py [probe …]` | Wer spricht: Anteil richtig zugeordneter Sprechzeit, Personenzahl – mit dem Live-Code |
| `scripts/bench_regeln.py [probe …]` | Regel 5 (Monologe) und 6 (Redeanteile, stille Person) gegen die Sprecher-Referenz, ohne KI-Kosten |
| `scripts/bench_fokus.py` | Regel 3: Fremdthemen-Einschübe auf Satzebene, ~5 Cent je Aufruf |
| `scripts/bench_ton.py` | Regel 7 auf dem Text-Testset, unter 1 Cent |
| `scripts/bench_ergebnisse.py` | Regel 10: Ergebnis je TOP im Stadtrat gegen bekannte Beschlüsse, unter 1 Cent |
| `scripts/tts_probe.py` | erzeugt die synthetische Probe `ton_tts` (wenige Cent) |
| `scripts/abspielen.py <wav> --tempo N` | ganze Pipeline, Bericht in `logs/bericht_<name>.json` (`LMC_OFFLINE=1` ohne KI-Kosten) |
| `scripts/themen_vergleich.py` | Agenda-Wechsel und Fokus-Hinweise auf einem gespeicherten Transkript |
| `scripts/onepager_messen.py` | Live-Bild: Zeit je Schritt, Fortschreibung |

Stand 05.10.2026, Wer spricht (CAM++, Schwelle 0,50): Stadtrat 95 % / 3 Personen, Talkshow 96 % / 4,
Zoom 96 % / 6.

## Neue Probe aufnehmen

1. Ordner `proben/<name>/` mit `probe.json` anlegen (Vorlage: eine bestehende Probe): `quelle` (URL,
   `von`/`bis` in Sekunden) oder `abgeleitet` (Teile anderer Proben), `meeting`, `referenz`, `eignung`.
2. `scripts\bibliothek_laden.py <name>` ausführen.
3. Referenz ehrlich kennzeichnen (`*_quelle`): inhaltlich ermittelt, aus Kapitelmarken, aus einem anderen
   Modell – und was davon geprüft ist.

Gesucht werden vor allem: Präsenzmeeting mit einem Raummikrofon (5 Personen), Aufnahmen mit
dokumentierten Regelverstößen (z. B. Bundestag mit Zwischenrufen und Ordnungsrufen im Plenarprotokoll),
eigene Rollenspiel-Aufnahmen mit Drehbuch.
