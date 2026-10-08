# Sprachassistent „Nestor“

Stand 05.10.2026 · Ausbaustufe 2: Der Coach lässt sich mit Namen ansprechen und antwortet mit Sprache.

## Ablauf im Meeting

1. **Begrüßung mit Einverständnis, ohne Wartepause.** Seit Ticket #23 (08.10.2026) in Premium **frei formuliert**
   im Realtime-Gespräch (`coach/begruessung.py`, gpt-realtime wie im ChatGPT-Sprachmodus): Das Modell bekommt die
   Pflichtinhalte als Liste, nicht als Wortlaut – Name und Rolle, die Regeln kurz, „ich höre mit“, Nein jetzt oder
   später als „Nestor, nein“ (dann wird gelöscht), wie man Nestor anspricht, die Bitte um Agenda-Ansage mit einem
   Halbsatz zur Agenda, Start mit Punkt eins. Jedes Mal etwas anders, Ziel ~30–40 s.
   - **Unterbrechbar:** semantic VAD mit `interrupt_response` und `create_response` (nur während der Begrüßung).
     „Passt, leg los“ stoppt den Ton sofort, auch wenn die Antwort schon fertig erzeugt ist; das Modell erfährt per
     `conversation.item.truncate`, wie weit es zu hören war, und reagiert selbst. Danach wird die Sitzung zum normalen
     Gespräch (der Coach entscheidet wieder, wann Nestor spricht). Fragt niemand etwas, schließt sie 20 s nach der
     Begrüßung, auch wenn die Runde weiterredet (sonst trüge die nächste Antwort Minuten mitgehörten Tons als Eingabe);
     nach einer Frage gilt das Leerlauf-Ende wie bisher.
   - **Prüfung:** Geprüft wird das Ausgabe-Transkript, und nur der Teil, der wirklich zu hören war. Fehlen „ich höre
     mit“, das Nein, „Nestor, nein“ oder das Löschen, sagt Nestor per Sprachausgabe einen festen Nachsatz.
   - **Rückfall:** feste Fassung (unten), wenn keine Sitzung zustande kommt oder binnen 8 s kein Ton kommt
     (`LMC_BEGRUESSUNG_FRIST_TON`); `LMC_BEGRUESSUNG=fest` schaltet die freie Begrüßung ab.
   - **Nein während der Begrüßung:** wie bisher über den Live-Text, dazu über die Transkription des Mikrofons in der
     Sitzung (ein kurzes „Nein“, auch als „Neun“ oder „Nee“ verstanden) und über das Werkzeug
     `nicht_einverstanden`, falls das Modell das Nein versteht. Jeder Weg führt in dieselbe Einwand-Logik; eine offene
     Realtime-Sitzung wird dabei sofort geschlossen.
   - Probelauf 08.10. (`scripts/begruessung_probe.py`): drei Begrüßungen 38–40 s, je ~5,5 Cent; „Passt, leg los“ nach
     10 s → Ton nach 0,6 s still, Reaktion mit Einwilligung, gesamt 25 s; „Nein“ nach 8 s → nach 3,4 s gelöscht.
   - **Basis:** Sprachausgabe der festen Fassung. Optional (`LMC_BASIS_BEGRUESSUNG_FREI=1`, noch nicht gemessen)
     formuliert mistral-small den Text vorher frei, mit derselben Prüfung; kommt er nicht binnen 2 s oder fehlt ein
     Pflichtpunkt, gilt die feste Fassung.

   Feste Fassung: „Hallo zusammen, ich bin Nestor und begleite heute euer Meeting. Ihr habt euch diese Regeln vorgenommen: …
   (Außerdem habt ihr euch vorgenommen: … – die weiteren Regeln.) Dafür höre ich mit. Wer nicht einverstanden ist,
   sagt einfach Nein – das geht auch später noch, dann mit meinem Namen: ‚Nestor, nein‘. Dann lösche ich alles.“
   Direkt danach, in lockerem Ton (eigene Stimm-Anweisung `STIL_START`): wie man mit Nestor arbeitet (Name + Frage,
   Nachfragen ohne Namen, Reinreden macht ihn still, Hinweise nur auf dem Bildschirm), die Bitte um Agendawechsel,
   ein Halbsatz zur Agenda („Vier Punkte in 60 Minuten – das passt gut.“) und „Los geht's mit Punkt eins: …“.
   - **Nein:** Ein einfaches „Nein“ zählt bis 7 s nach der Begrüßung (`LMC_EINWAND_SEKUNDEN`), danach nur noch
     „Nestor, nein“ als ganzer Satz – „Nestor, nein, ich meinte Punkt zwei“ löscht nichts. Bei einem Nein werden
     Transkript und Stimmprofile gelöscht, ab dann geht kein Ton mehr an OpenAI; wieder einschalten nur per Knopf.
   - Mit Vorstellungsrunde (`LMC_VORSTELLUNG_SEKUNDEN` > 0) kommt nach der Begrüßung zuerst die Bitte um die Namen.
     Frei formuliert endet die Begrüßung dann mit dieser Bitte; den Rest sagt Nestor nach der Runde im noch offenen
     Gespräch (sonst fest).
2. **Zuhören ohne Einmischen.** Ampeln und Hinweise laufen wie bisher still im Dashboard. Gesprochen wird
   nur auf Ansprache.
3. **Ansprache:** „Nestor, …“ irgendwo im Satz, oder Knopf „Nestor fragen“ (dann ohne Namen). Kommt nur
   der Name, antwortet er „Ja?“ (aus dem Zwischenspeicher) und wartet auf die Frage. Bis 15 s nach einer Antwort geht eine Rückfrage
   auch ohne Namen, wenn sie als Frage endet.
4. **Antwort** gesprochen, kurz (meist 1–3 Sätze), dazu als Text in der Assistenten-Leiste.
   **Aktionen** auf Zuruf:

| Beispiel | Aktion |
|---|---|
| „Nestor, wo stehen wir?“, „Fass den aktuellen Punkt zusammen“, „Was kommt als Nächstes?“ | Antwort aus Agenda, Ergebnissen und Transkript |
| „Wir kommen jetzt zum nächsten Punkt“ | Agendapunkt wechseln, danach greift Regel 10 (Ergebnis des abgeschlossenen Punkts) |
| „Erstell uns die visuelle Übersicht“, „Visualisier nur den letzten Punkt“, „Zeig, was noch ansteht“, „Wo fehlen Entscheidungen?“ | Live-Bild mit diesem Fokus (Claude, ~1–2 min), danach „Das Bild ist fertig“ |
| „Gib uns einen Überblick zu …“, „Wie ist der aktuelle Stand bei …?“ | Recherche im Web: „Ich schau kurz nach“, dann gesprochene Zusammenfassung; danach bietet Nestor an, das Ergebnis mit Quellen auf einer Folie zusammenzustellen |
| „Ja, mach eine Folie“ (nach einer Recherche) | Recherche-Folie im Dashboard: Titel, Kernaussage, Stichpunkte, Offenes, Quellen als Links (~3 s) |
| „Nestor, hör bitte nicht mehr zu“ | Pause (wieder an per Knopf) |

## Sofort bestätigen, sichtbar arbeiten (Ticket #21)

- **Eine Stelle für Antworten:** Was Nestor sagt, steht immer im **Nestor-Feld oben im mittleren Feld**
  (`#nestor-feld`): dunkles Indigo mit goldenem N. Agenda/Zeit links und die rechte Spalte bleiben frei. Der frühere
  Untertitel und die Pop-up-Karte sind weg; die Karte (Titel, Stichpunkte, Quellen) erscheint nach dem Sprechen an
  derselben Stelle. Hinweise (Regeln, Zeit) bleiben im Bernstein-/Rot-Band über den Spalten.
- **Text läuft mit:** Realtime schickt die Transkript-Stücke (`response.output_audio_transcript.delta`), der Text-Weg
  (auch Basis) den Satz unmittelbar vor seinem Ton – als `{"typ": "nestor_text"}` an alle Dashboards. Der
  Lautsprecher-Tab zeigt jedes Stück, wenn der Ton davor abgespielt ist; andere Tabs schätzen ~15 Zeichen/s.
- **Bestätigung:** Jeder Auftrag bekommt sofort eine wechselnde Floskel („Okay, kleinen Moment“, „Schau ich mir an“ …).
  Lange Aufgaben (Bild, Folie, Recherche, Überblick) sagen zusätzlich: „Mach ich, braucht ein bisschen. Macht ruhig
  schon weiter, ich zeig's euch hier gleich. Wenn ihr noch was braucht, sprecht mich einfach an.“ – sobald das
  Modell die Aufgabe wirklich anstößt (Aktionszeile bzw. Werkzeug). Die Floskeln werden je Stimme einmal erzeugt
  (Premium gpt-4o-mini-tts, Basis Voxtral/Thorsten), Stille vorn und hinten gekürzt und unter `cache/floskeln/`
  abgelegt (`LMC_FLOSKEL_ORDNER`); danach kosten sie nichts. Erzeugt werden sie beim Meetingstart im Hintergrund.
  `LMC_BESTAETIGUNG=0` schaltet das ab.
- **Messung 08.10.** (`scripts/bestaetigung_messen.py`, ab dem Satz mit „Nestor“, ohne den Verzug des Live-Texts):

| Weg | erster Ton |
|---|---|
| Floskel aus dem Zwischenspeicher (beide Stufen) | < 0,01 s bis zum ersten Tonstück, im Ende-zu-Ende-Lauf 0,07 s |
| Premium Realtime, neue Sitzung (Verbindung + status_abfragen + Antwort) | Median 1,58 s (1,39–2,08) |
| Premium Realtime, offene Sitzung | Median 0,82 s (0,73–1,04) |
| Basis, mistral-medium erster Satz + Voxtral | Median 1,23 s (1,20–1,61) |

  **Entscheidung:** Neue Sitzung und Text-Weg (Basis, Kurzantwort): Floskel sofort, die Antwort folgt nahtlos danach.
  In der offenen Realtime-Sitzung keine kurze Floskel – das Modell spricht selbst nach ~0,8 s, eine Floskel hielte den
  Inhalt nur auf (`LMC_BESTAETIGUNG_IM_GESPRAECH=1` schaltet sie trotzdem ein); lange Aufgaben bekommen die lange
  Ansage beim Werkzeugaufruf (~0,4–0,5 s). Die Anweisungen sagen dem Modell, dass es nicht selbst mit „Okay“ beginnt.
  Die lange Ansage aus der Frage zu raten wurde verworfen: im Probelauf kündigte Nestor eine Recherche an, das Modell
  bot dann ein Bild an.
- **Arbeitssymbol und Warteschlange:** Im Feld dreht sich ein goldener Ring um das N, solange Nestor angesprochen ist,
  denkt, recherchiert oder ein Auftrag läuft. Darunter die Aufträge mit „läuft“/„wartet“ und ✕
  (`POST /api/assistent/abbrechen {id}`). Per Stimme: „Nestor, lass die Recherche“, „Nestor, brich das Bild ab“,
  „Nestor, vergiss die Folie“ → „Okay, lass ich.“ Eine zweite Recherche wartet, bis die erste fertig ist; während
  einer Recherche kann die Runde Nestor im Gespräch weiter fragen.
- **Hineinreden (#20):** Auch im normalen Gespräch verstummt Nestor, solange sein Ton im Dashboard noch läuft, nicht
  nur während der Erzeugung; das Modell erfährt per `conversation.item.truncate`, wie weit es zu hören war.

## Architektur

Zwei Betriebsarten (`LMC_ASSISTENT_MODUS`):

**„gespraech“ (Standard): wie der ChatGPT-Sprachmodus.** Nestor ist Teil der Runde:

```
Mikrofon ─► Live-Text (läuft ohnehin) ─► Satz mit „Nestor“ ─► Realtime-Sitzung öffnen (gpt-realtime)
                                                               Anweisung: Persona + Meeting-Zustand
                                                               erste Frage als Text → Antwort als Sprache
Mikrofon ──────────────────────────────────────────────────► geht direkt in die offene Sitzung
                                                               (Modell hört Rückfragen, Gesagtes, Tonfall)
Live-Text: Name oder Rückfrage „…?“ kurz nach der Antwort ──► Coach löst die nächste Antwort aus
Jemand redet hinein ──► Dashboard verstummt sofort (auch nach response.done), truncate an das Modell
20 s Ruhe oder „danke, das war's“ ──► Sitzung zu, Nestor hört wieder nur auf seinen Namen
Werkzeuge: bild_zeichnen(fokus), agendapunkt_wechseln(nummer), recherchieren(frage), folie_erstellen, zuhoeren_pausieren,
           gespraech_beenden
Ton: PCM-Stücke ─► WebSocket ─► Dashboard (nur Moderationsansicht) spielt nahtlos ab
```

- **Natürlichkeit:** Stimme, Betonung und Tempo kommen direkt aus dem Sprachmodell, nicht aus einer
  vorgelesenen Textantwort. Rückfragen funktionieren ohne Namen, und man kann Nestor ins Wort fallen.
- **Wer entscheidet, wann er spricht:** der Coach, nicht das Modell (`create_response` aus). Abspieltest:
  Mit eigener Entscheidung kommentierte das Modell ungefragt das laufende Gespräch („Alles klar,
  Vorschlag: maximal 2000 Euro“). Jetzt antwortet es nur, wenn der Name im Live-Text fällt oder kurz nach
  seiner Antwort eine Rückfrage kommt. Es hört aber alles mit und weiß, was gesagt wurde.
- **Kosten** laut Token-Protokoll im Abspieltest: je Antwort ~1–2 Cent, solange die Sitzung offen ist
  dazu das mitgehörte Audio. Die Sitzung schließt nach 20 s Ruhe.

**„text“ (Rückfall, günstiger):** Satz mit Namen ─► GPT-5.4-mini gestreamt (erste Zeile Aktion, dann
Text) ─► Satz für Satz Sprachausgabe gpt-4o-mini-tts ─► Dashboard. Gemessen: erster Satz nach ~1,2 s,
erster Ton ~0,5 s später, ~1 Cent je Frage. Nicht unterbrechbar, Rückfragen nur als Frage mit „?“. Der
Coach nutzt diesen Weg automatisch, wenn keine Realtime-Sitzung zustande kommt.

**Nestor Basis (Ticket #13, nur Mistral):** immer der Weg „text“ – Satz mit Namen ─► `mistral-medium-latest`
gestreamt (dieselbe `AKTION:`-Zeile, kein Tool-Call) ─► Satz für Satz Voxtral TTS mit der gespeicherten Stimme
**Thorsten** (`voice_id`, Thorsten-Voice CC0, Referenz in `coach/stimmen/`) ─► Dashboard. Live-Text über Voxtral
Realtime. Gemessen 08.10. ([messung_basis.md](messung_basis.md)): Sprechende → erster Ton im Median ~2,0–2,1 s,
24/24 Zurufe mit richtiger Aktion. Keine Rückfragen ohne Namen, kein Ins-Wort-Fallen; die Begrüßung sagt deshalb
„jedes Mal mit meinem Namen – oder ihr nehmt die Knöpfe“. „Zeig uns die Übersicht“ (`AKTION: bild`) stellt in Basis
den **Überblick als Text** ins Dashboard (`coach/ueberblick.py`), nach wenigen Sekunden. Kommt Mistral auch nach
Wiederholungen nicht durch (HTTP 429), sagt Nestor: „Ich komme gerade nicht durch, versucht es gleich nochmal.“
Die Stil-Anweisung für die Stimme (`STIL_START`) gibt es bei Voxtral nicht; sie entfällt in Basis.

**Nestor fragen per Knopf, auch am Handy:** Am Handy wird „Nestor fragen“ gehalten: halten, fragen, loslassen. Der
Ton der Frage geht als WAV an `/api/frage/audio`, wird mit dem Transkriptionsmodell der Stufe zu Text und dann wie
eine gesprochene Frage beantwortet (Stimme + Karte); mit „Nur auf Knopfdruck“ als Karte. Was während des Haltens
gesagt wurde, wertet der Live-Text nicht noch einmal als Zuruf aus.

**Recherche** (`coach/recherche.py`): Websuche über die OpenAI-Responses-API (GPT-5.4-mini mit
`web_search`). In die Suche geht nur das vom Modell formulierte Thema und der Meetingtitel, kein
Transkript. Eingebettete Quellenverweise werden vor dem Vorlesen entfernt. Gemessen 05.10.: Suche 5–8 s,
gesprochener Überblick ~11 s nach der Frage, ~2 Cent je Recherche. In Basis: Mistral Conversations-API mit dem
Werkzeug `web_search` (`store: false`), gemessen ~5 s mit 2 Quellen; kommt eine Antwort ohne Quellen, wird die Suche
einmal erzwungen. Kosten ~3 Cent (Suchergebnisse zählen bei Mistral als Eingabe-Tokens).

**Nestor-Karten** (`coach/karten.py`): Was Nestor sagt, erscheint nach dem Sprechen im Nestor-Feld oben im mittleren Feld (Ticket #21) –
Titel, die Frage, 2–4 Stichpunkte, bei Recherchen die Quellen. GPT-5.4-mini verdichtet die gesprochene Antwort
(gemessen 1,3–2,5 s, Frist 6 s, sonst die ersten Sätze) und lässt Bestätigungen, Rückfragen und Smalltalk weg.
Bei Aktionen (Bild, Agenda-Wechsel, Pause, Folie) gibt es keine Karte, weil das Dashboard das Ergebnis selbst
zeigt. Automatisch geöffnete Karten treten nach einer Minute zurück; alle bleiben im Verlauf (Reiter „Nestor“)
und lassen sich dort wieder öffnen. Den Untertitel gibt es nicht mehr; der Text läuft im selben Feld mit.

**Recherche-Folie** (`coach/folie.py`): auf Zuruf oder per Knopf im Live-Bild-Bereich. GPT-5.4-mini macht aus
dem Rechercheergebnis Titel, Kernaussage, 3–5 Stichpunkte und Offenes – ohne neue Suche, ohne Transkript. Die
Folie ist eine Dashboard-Ansicht (umschaltbar mit dem Live-Bild), damit Text scharf und Quellen anklickbar
bleiben. Gemessen 05.10.: 2,8 s, unter 1 Cent.

**Gemeinsam:**
- **Kein eigenes Wake-Word-Modell.** Der Name wird im Live-Text gesucht, der ohnehin mitläuft; das kostet
  nichts zusätzlich. Der Name steht in der Stichwortliste und im Prompt der Texterkennung. Abspieltest:
  Ohne diese Hilfe kam „Nestor“ am Satzanfang 3 von 4 Mal als „Mestor“ an, mit ihr 4 von 4 richtig.
  Ähnliche Schreibweisen werden zusätzlich akzeptiert.
- **Begrüßung:** in Premium frei im Realtime-Gespräch mit geprüften Pflichtinhalten, sonst feste Texte über die
  Sprachausgabe (siehe oben).
- **Eigene Stimme:** Mit Assistent nutzt das Mikrofon die Echo-Unterdrückung des Browsers. Zusätzlich
  verwirft der Server Sätze und Sprecherabschnitte aus den Zeitfenstern, in denen Nestor spricht. So zählt
  er weder im Transkript noch bei den Redeanteilen als Person.
- **Datenschutz:** Ein Nein bei der Begrüßung löscht alles Gehörte. Ab da geht kein Ton mehr an OpenAI,
  weder an den Live-Text noch an ein Gespräch. Die Antworten nennen keine Personen.

## Was (noch) nicht geht

- **Ins Wort fallen im Raum:** Im Gesprächsmodus bricht Nestor ab, sobald jemand spricht. Ob die
  Echo-Unterdrückung des Browsers seine eigene Stimme sicher heraushält (sonst unterbricht er sich selbst),
  zeigt erst der Raumtest. Notfalls gibt es den Knopf „Stopp“.
- **Kontext während eines Gesprächs:** Der Meeting-Stand wird beim Öffnen der Sitzung mitgegeben. Was
  danach passiert, hört Nestor direkt, Agenda und Ergebnisse aktualisiert er aber erst in der nächsten
  Sitzung.
- **Lautstärke im Raum:** Der Laptoplautsprecher reicht für einen kleinen Raum. Für 5 Personen am Tisch
  eher einen kleinen Lautsprecher anschließen; das Konferenzmikro mit eigenem Lautsprecher hat meist
  bessere Echo-Unterdrückung.
- **Wer fragt:** Nestor weiß nicht, wer ihn anspricht (Namen gibt es nur als „Person N“).
- **Fehlauslöser:** Fällt der Name im normalen Gespräch („wie Nestor vorhin sagte“), antwortet er. Ein
  seltener Name verringert das.

## Test

- `scripts/tts_assistent_probe.py` erzeugt zwei synthetische Meetings (Kosten wenige Cent):
  `assistent_dialog` (Begrüßung ohne Einwand, Gespräch, vier Fragen) und `assistent_nein` (Einwand).
- Abspielen: `scripts\abspielen.py testbibliothek\audio\assistent_dialog.wav --tempo 1`, oder im Dashboard
  unter „Aufnahme abspielen“ (dann ist die Stimme zu hören). Fragen und Antworten stehen im Bericht
  unter `protokoll` mit `art = "assistent"`.
- `assistent_recherche`: „Gib uns einen kurzen Überblick zum aktuellen Stand beim gesetzlichen
  Mindestlohn“ → „Ich schau kurz nach“, Suche 5,4 s, Überblick mit Stand 2026 und Ausblick 2027.
- Ergebnis 05.10.: Gesprächsmodus 4/4 Ansprachen beantwortet, bei nicht gerichtetem Gespräch still,
  Agenda-Wechsel per Zuruf, Fokusbild angestoßen. Der Textmodus beantwortete ebenfalls 4/4. Ein Einwand
  löscht alles und pausiert. Im Dashboard abgespielt: Assistenten-Leiste und Ton kommen an.
- Unit-Tests ohne Netz: `tests/test_assistent.py`.

## Name

Arbeitsname **Nestor**. In Homers Ilias ist Nestor der erfahrene Ratgeber, der im Rat der Griechen
vermittelt, zum Beispiel im Streit zwischen Agamemnon und Achilles. Der Name ist kurz, gut zu sprechen,
im Alltag selten und wird nach dem Stichwort-Trick zuverlässig erkannt.

Alternativen:
- **Forseti:** nordischer Gott der Schlichtung; in seiner Halle Glitnir gehen alle Streitenden versöhnt
  auseinander. Im Isländischen heißt „forseti“ heute „Vorsitzender“. Sehr passend, aber die
  Texterkennung muss ihn erst lernen (ungewohnt im Deutschen).
- **Solon:** Athener Gesetzgeber und Schlichter. Kurz und deutlich.
- Nicht geeignet: **Themis** (Göttin der Ordnung, beruft die Götterversammlung ein) klingt zu sehr nach
  „Thema“ und würde in Meetings ständig auslösen. **Mentor** ist ein Alltagswort.

Änderbar über `LMC_ASSISTENT_NAME` und `LMC_ASSISTENT_MUSTER` (Schreibweisen für die Erkennung).
