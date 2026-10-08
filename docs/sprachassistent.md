# Sprachassistent „Nestor“

Stand 08.10.2026 · Seit Ticket #27 spricht Nestor nur im **Antwortbogen** – Premium wie ein Telefon, Basis wie ein
Funkgerät. Verbindlich ist [lastenheft.md](lastenheft.md) Abschnitt 1 und 4.10; hier stehen Technik und Messungen.

## Grundregel

Nestor spricht nur in einem Antwortbogen, den die Runde ausgelöst hat. Was er von sich aus merkt, kommt still: als
Zeile im Band oben oder als Karte im Verlauf. Einzige Ausnahme ist die Begrüßung.

## Ablauf im Meeting

1. **Begrüßung mit Einverständnis, ohne Wartepause.** In Premium **frei formuliert** im Realtime-Gespräch
   (`coach/begruessung.py`, Ticket #23): Das Modell bekommt die Pflichtinhalte als Liste, nicht als Wortlaut – Name
   und Rolle, die Regeln kurz, „ich höre mit“, Nein jetzt oder später als „Nestor, nein“ (dann wird gelöscht), wie man
   Nestor anspricht (wie ein Telefon), die Bitte um Agenda-Ansage mit einem Halbsatz zur Agenda, Start mit Punkt eins
   und **als letzter Satz** „Wenn ihr mögt, sagt kurz eure Namen, dann schreibe ich das Protokoll mit Namen.“
   (Ticket #27: Nestor sagt in der Begrüßung alles; nach der Namensrunde gibt es keinen Startsatz mehr).
   - **Unterbrechbar:** semantic VAD mit `interrupt_response` und `create_response` (nur während der Begrüßung).
     „Passt, leg los“ stoppt den Ton sofort; das Modell erfährt per `conversation.item.truncate`, wie weit es zu hören
     war, und reagiert selbst. Danach wird die Sitzung zum normalen Gespräch; ungenutzt schließt sie 20 s nach der
     Begrüßung, auch wenn die Runde weiterredet.
   - **Prüfung:** Geprüft wird das Ausgabe-Transkript, und nur der Teil, der wirklich zu hören war. Fehlen „ich höre
     mit“, das Nein, „Nestor, nein“ oder das Löschen, sagt Nestor einen festen Nachsatz; fehlt die Bitte um die Namen,
     sagt er sie.
   - **Rückfall:** feste Fassung, wenn keine Sitzung zustande kommt oder binnen 8 s kein Ton kommt
     (`LMC_BEGRUESSUNG_FRIST_TON`); `LMC_BEGRUESSUNG=fest` schaltet die freie Begrüßung ab.
   - **Nein während der Begrüßung:** über den Live-Text, über die Transkription des Mikrofons in der Sitzung (ein
     kurzes „Nein“, auch als „Neun“ oder „Nee“ verstanden) und über das Werkzeug `nicht_einverstanden`.
   - **Basis:** Sprachausgabe der festen Fassung; optional (`LMC_BASIS_BEGRUESSUNG_FREI=1`) formuliert mistral-small
     den Text vorher frei, mit derselben Prüfung.

   Feste Fassung: „Hallo zusammen, ich bin Nestor und begleite heute euer Meeting. Ihr habt euch diese Regeln
   vorgenommen: … Dafür höre ich mit. Wer nicht einverstanden ist, sagt einfach Nein – das geht auch später noch, dann
   mit meinem Namen: ‚Nestor, nein‘. Dann lösche ich alles.“ Direkt danach, in lockerem Ton (`STIL_START`):
   Premium „Ich funktioniere wie ein Telefon: Sagt ‚Nestor‘ und eure Frage. Direkt danach könnt ihr ohne Namen
   nachfragen, und wenn ich zu viel rede, redet einfach rein.“ bzw. Basis „Ich funktioniere wie ein Funkgerät: Taste
   halten, sprechen, loslassen – ich rede dann aus. Die Taste ist auf dem Bildschirm und am Handy, am Laptop geht auch
   die Leertaste.“, die Bitte um Agendawechsel, ein Halbsatz zur Agenda, „Los geht's mit Punkt eins: …“ und die
   Bitte um die Namen.
   - **Nein:** Ein einfaches „Nein“ zählt bis 7 s nach der Begrüßung (`LMC_EINWAND_SEKUNDEN`), danach nur noch
     „Nestor, nein“ als ganzer Satz – auch in Basis, das sonst nicht auf den Namen hört. Bei einem Nein werden
     Transkript und Stimmprofile gelöscht, ab dann geht kein Ton mehr an einen KI-Dienst; wieder einschalten nur per
     Knopf.
   - **Namen:** Während der Namensrunde (`LMC_VORSTELLUNG_SEKUNDEN`, 45 s) merkt sich Nestor jeden genannten Namen mit
     dem Stimm-Fingerabdruck genau dieser Äußerung und ordnet ihn still der Stimme im Register zu, sobald es sie sicher
     gibt (beste Ähnlichkeit ≥ 0,45, Abstand zur zweitbesten ≥ 0,08, je Person ein Name; bis 10 min nach der Runde).
     Oben im Band: „Erkannt: Anna, David …“. Messung siehe unten.
2. **Zuhören ohne Einmischen.** Regel-Hinweise (nur gewählte Regeln), Agenda-Vorschlag, Fünf-Minuten-Angebot und
   Lücken stehen still im Band; Zusammenfassungen je Agendapunkt kommen still in den Verlauf.
3. **Ansprache.** Premium (Telefon): „Nestor, …“ irgendwo im Satz; kommt nur der Name, antwortet er „Ja?“ (aus dem
   Zwischenspeicher) und nimmt den nächsten Satz als Frage. Nach jedem Bogen ist 15 s lang eine Nachfrage ohne Namen
   möglich (Follow-up-Modus, unten). Am Handy geht auch die Sprechtaste. Basis (Funkgerät): nur die Sprechtaste –
   halten, sprechen, loslassen (Laptop: Knopf oder Leertaste; Handy: großer Knopf). Sagt jemand „Nestor“, steht still
   im Band „Sprechtaste halten, dann fragen“ (höchstens einmal je Minute). In beiden Stufen: getippte Frage und Knöpfe.
4. **Antwortbogen** – siehe unten. **Aktionen** auf Zuruf:

| Beispiel | Was passiert |
|---|---|
| „Nestor, wie viel Zeit haben wir noch?“ | Bogen: Bestätigung, Antwort in einem Satz, Karte mit den Einzelheiten |
| „Nestor, fass zusammen“, „… was fehlt noch?“, „… wo stehen wir?“, „… zeig das Protokoll“ | Karten-Bogen (eindeutige Sätze direkt erkannt, sonst `AKTION: karte` bzw. Werkzeug `karte_zeigen`): Karte, dazu ein bis zwei Sätze zu dem, was auffällt |
| „Wir kommen jetzt zum nächsten Punkt“ (ohne Namen) | Agendapunkt wechseln; die Zusammenfassung des alten Punkts kommt still als Karte |
| „Nestor, Sofie übernimmt die Statusseite bis Freitag“ | Lücke schließen: Premium Werkzeug `artefakt_eintragen`, Basis `AKTION: eintragen` – Nestor sagt nur „Notiert.“, die Karte wird grün |
| „Nestor, mach ein Bild davon“, „Visualisier nur den letzten Punkt“ | langer Auftrag: „Nehme ich mit …“, das Bild kommt still in den Verlauf (Basis: Überblick als Text, kurzer Bogen) |
| „Gib uns einen Überblick zu …“, „Wie ist der aktuelle Stand bei …?“ | langer Auftrag Recherche: „Nehme ich mit …“, das Ergebnis kommt still als Karte mit Quellen |
| „Ja, mach eine Folie“ (nach einer Recherche) | Bogen „Folie“: Bestätigung, Folie als Karte, „Hier ist die Folie.“ |
| „Nestor, erklär das Bild“ | normale Frage zum letzten Bild bzw. zur letzten Recherche |
| „Nestor, lass die Recherche“, „brich das Bild ab“ | Auftrag abbrechen: „Okay, lass ich.“ |
| „Nestor, hör bitte nicht mehr zu“ | Pause (wieder an per Knopf) |

## Der Antwortbogen (Ticket #27)

- **Ablauf:** sofort eine Floskel aus dem Vorrat (`coach/bestaetigung.py`: „Bin dran.“, „Moment, kommt gleich.“,
  „Schau ich mir an, komme gleich zurück.“ – für Zuruf, Sprechtaste und Knopf gleich), dann die Karte im Verlauf, dann
  ein bis zwei Sätze zu dem, was auffällt. Für Zusammenfassen und Was fehlt formuliert ein kleiner Modellaufruf den
  Satz (`coach/bogen.py: moderationssatz`, Frist 5 s, sonst ein fester Ersatzsatz aus den Lücken); Wo stehen wir
  liefert Karte und Satz in einem Aufruf. Fragen beantwortet das Modell in einem, höchstens zwei Sätzen; die Karte
  (`coach/karten.py`) ergänzt Einzelheiten aus dem Meeting-Stand.
- **Ein Bogen zur Zeit:** Knöpfe sind gesperrt (HTTP 409, im Dashboard sichtbar). Ein Zuruf, eine Nachfrage oder die
  Sprechtaste unterbricht die Stimme des laufenden Bogens (`stimme_stopp`) und startet den neuen. Der alte Bogen
  arbeitet still weiter, seine Karte kommt trotzdem in den Verlauf (im Realtime-Gespräch: `interrupt_response` aus,
  die Antwort wird fertig erzeugt, ohne Ton weitergereicht; am Ende `conversation.item.truncate` auf das Gehörte).
- **Lange Aufträge** (Bild, Recherche) sind kein Bogen: „Nehme ich mit, dauert ein bisschen. Macht ruhig weiter.“ –
  das Ergebnis kommt still. Höchstens zwei (einer läuft, einer wartet: „Ich bin noch am Bild, die Recherche mache ich
  danach.“), ein dritter wird abgewehrt („Ich hab gerade zwei Sachen auf dem Zettel. Fragt mich gleich nochmal.“).
  Arbeitsring oben rechts, ✕ (`POST /api/assistent/abbrechen {id}`) oder per Stimme abbrechen.
- **Floskeln** werden je Stimme einmal erzeugt (Premium gpt-4o-mini-tts, Basis Voxtral/Thorsten), Stille vorn und
  hinten gekürzt und unter `cache/floskeln/` abgelegt; beim Meetingstart im Hintergrund. `LMC_BESTAETIGUNG=0` schaltet
  sie ab.
- **Text läuft mit:** Realtime schickt die Transkript-Stücke, der Text-Weg den Satz unmittelbar vor seinem Ton – als
  `{"typ": "nestor_text"}`; das Dashboard zeigt ihn in Nestors Zeile über dem Verlauf.
- **Gemessen** (`scripts/bogen_messen.py`, 60-Minuten-Meeting, ab dem Auslöser):

MESS_BOGEN_TABELLE

## Nachfrage ohne Namen (Premium, Follow-up-Modus)

Nach jedem Bogen öffnet sich ab dem Ende der Wiedergabe ein Fenster von 15 s (`LMC_NACHFRAGE_SEKUNDEN`), sichtbar als
Ring „Ich höre zu“, der abläuft. Nur der **erste Satz** danach kann eine Nachfrage sein; ist er nicht an Nestor
gerichtet, schließt das Fenster sofort (die Runde hat übernommen). Entscheidung in drei Stufen, im Zweifel schweigen
(`coach/bogen.py`, `coach/assistent.py: nachfrage_einordnen`):
1. Regel: der Satz spricht eine Person der Runde an („Anna, …“, „…, oder Tarek?“, ein Name aus Einrichtung oder
   Namensrunde) → nicht an Nestor.
2. Regel: klare Anschlussfrage oder Auftrag („Und bis wann?“, „Und wer?“, „Zeig/trag/ergänz …“, „Kannst du …“ ohne
   anderen Namen) → an Nestor, Bogen.
3. Sonst ein schneller Klassifikator (gpt-5.4-mini, kurzer Prompt mit Nestors letzter Antwort): `frage_an_nestor`
   (Bogen), `an_nestor_ohne_antwort` („Passt“, „Danke“ → still), `nicht_an_nestor` (still). Frist 2,5 s.
Dieselbe Person wie die Fragende wird mitgeschrieben, ist aber nur ein Plus-Signal. Antwortet Nestor doch falsch,
stoppt ihn Reinreden. MESS_EINORDNUNG_TEXT

## Architektur


Zwei Betriebsarten (`LMC_ASSISTENT_MODUS`):

**„gespraech“ (Standard): wie der ChatGPT-Sprachmodus.** Nestor ist Teil der Runde:

```
Mikrofon ─► Live-Text (läuft ohnehin) ─► Satz mit „Nestor“ ─► Bogen ─► Realtime-Sitzung öffnen (gpt-realtime)
                                                               Anweisung: Persona + Meeting-Zustand
                                                               erste Frage als Text → Antwort als Sprache
Mikrofon ──────────────────────────────────────────────────► geht direkt in die offene Sitzung
                                                               (Modell hört Rückfragen, Gesagtes, Tonfall)
Live-Text: Name oder gerichtete Nachfrage (erster Satz nach dem Bogen) ──► Coach löst den nächsten Bogen aus
Jemand redet hinein ──► Dashboard verstummt sofort; die Antwort wird still fertig (Karte), truncate an das Modell
20 s Ruhe oder „danke, das war's“ ──► Sitzung zu, Nestor hört wieder nur auf seinen Namen
Werkzeuge: bild_zeichnen(fokus), recherchieren(frage) – lange Aufträge; folie_erstellen, karte_zeigen(art) – Karten-
           Bogen; artefakt_eintragen; agendapunkt_wechseln(nummer); status_abfragen; zuhoeren_pausieren;
           gespraech_beenden
Ton: PCM-Stücke ─► WebSocket ─► Dashboard (nur Moderationsansicht) spielt nahtlos ab
```

- **Natürlichkeit:** Stimme, Betonung und Tempo kommen direkt aus dem Sprachmodell, nicht aus einer
  vorgelesenen Textantwort. Eine Nachfrage geht ohne Namen, und man kann Nestor ins Wort fallen. Die Sätze der
  Karten-Bögen (Zusammenfassen usw.) spricht die Sprachausgabe mit derselben Stimme.
- **Wer entscheidet, wann er spricht:** der Coach, nicht das Modell (`create_response` aus). Abspieltest:
  Mit eigener Entscheidung kommentierte das Modell ungefragt das laufende Gespräch („Alles klar,
  Vorschlag: maximal 2000 Euro“). Jetzt antwortet es nur, wenn der Name im Live-Text fällt oder der erste Satz
  nach seinem Bogen an es gerichtet ist. Es hört aber alles mit und weiß, was gesagt wurde.
- **Kosten** laut Token-Protokoll im Abspieltest: je Antwort ~1–2 Cent, solange die Sitzung offen ist
  dazu das mitgehörte Audio. Die Sitzung schließt nach 20 s Ruhe.

**„text“ (Rückfall, günstiger):** Satz mit Namen ─► GPT-5.4-mini gestreamt (erste Zeile Aktion, dann
Text) ─► Satz für Satz Sprachausgabe gpt-4o-mini-tts ─► Dashboard. Gemessen: erster Satz nach ~1,2 s,
erster Ton ~0,5 s später, ~1 Cent je Frage. Der Coach nutzt diesen Weg automatisch, wenn keine Realtime-Sitzung
zustande kommt. Wird der Bogen unterbrochen, schweigt die Stimme, die Antwort wird trotzdem fertig und kommt als Karte.

**Nestor Basis (Ticket #13, Funkgerät seit #27, nur Mistral):** immer der Weg „text“ – Sprechtaste ─► Ton der Frage
als WAV an `/api/frage/audio` ─► Voxtral-Transkription ─► Bogen ─► `mistral-medium-latest` gestreamt (dieselbe
`AKTION:`-Zeile, kein Tool-Call) ─► Satz für Satz Voxtral TTS mit der gespeicherten Stimme **Thorsten** (`voice_id`,
Thorsten-Voice CC0, Referenz in `coach/stimmen/`) ─► Dashboard. Live-Text über Voxtral Realtime (für Transkript,
Agenda-Ansagen, Fokus und das „Nein“). Basis reagiert nicht auf den Namen; Rückfrage-Fenster gibt es keins, die
Sprechtaste unterbricht Nestor. „Zeig uns die Übersicht“ (`AKTION: bild`) stellt den **Überblick als Text** in den
Verlauf (`coach/ueberblick.py`). Kommt Mistral auch nach Wiederholungen nicht durch (HTTP 429), sagt Nestor: „Ich
komme gerade nicht durch, versucht es gleich nochmal.“ Die Stil-Anweisung für die Stimme (`STIL_START`) gibt es bei
Voxtral nicht. Gemessen 08.10. vor #27 ([messung_basis.md](messung_basis.md)): Sprechende → erster Ton ~2,0–2,1 s,
24/24 Aktionen richtig.

**Sprechtaste, auch am Handy:** Halten, fragen, loslassen; Laptop (Basis) Knopf oder Leertaste, Handy (beide Stufen)
großer Knopf. Was während des Haltens gesagt wurde, wertet der Live-Text nicht noch einmal als Zuruf aus. Drücken
unterbricht einen laufenden Bogen.

**Recherche** (`coach/recherche.py`): Websuche über die OpenAI-Responses-API (GPT-5.4-mini mit
`web_search`). In die Suche geht nur das vom Modell formulierte Thema und der Meetingtitel, kein
Transkript. Seit Ticket #27 ein langer Auftrag: das Ergebnis kommt still als Karte mit Quellen in den Verlauf (keine
Ansage, kein Vorlesen). Gemessen 05.10.: Suche 5–8 s, ~2 Cent je Recherche. In Basis: Mistral Conversations-API mit dem
Werkzeug `web_search` (`store: false`), gemessen ~5 s mit 2 Quellen; kommt eine Antwort ohne Quellen, wird die Suche
einmal erzwungen. Kosten ~3 Cent (Suchergebnisse zählen bei Mistral als Eingabe-Tokens).

**Verlauf und Karten** (`coach/karten.py`, `static/verlauf.js`): Jede Antwort, Zusammenfassung, Recherche, Folie, jedes
Bild und jeder Überblick ist eine Karte im Verlauf in der Mitte – neueste vorn, ‹ › bzw. Wischen zum Blättern, ein
neues Ergebnis leuchtet kurz; still Geliefertes springt nur nach vorn, wenn die vordere Karte älter als ~60 s ist,
sonst „1 neu ›“. Die Antwortkarte verdichtet GPT-5.4-mini aus Frage, gesprochener Antwort und Meeting-Stand (Frist 6 s,
sonst die Sätze). Karten mit Meeting-Artefakten zeigen immer den aktuellen Stand (Lücken rot, geschlossene grün,
antippen zum Eintragen).

**Recherche-Folie** (`coach/folie.py`): als Bogen auf Zuruf oder per Knopf. GPT-5.4-mini macht aus dem
Rechercheergebnis Titel, Kernaussage, 3–5 Stichpunkte und Offenes – ohne neue Suche, ohne Transkript; die Folie ist
eine Karte im Verlauf. Gemessen 05.10.: 2,8 s, unter 1 Cent.

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

- **Ins Wort fallen im Raum (Premium):** Nestor verstummt, sobald jemand spricht. Ob die
  Echo-Unterdrückung des Browsers seine eigene Stimme sicher heraushält (sonst unterbricht er sich selbst),
  zeigt erst der Raumtest. Notfalls gibt es den Knopf „Stopp“.
- **Kontext während eines Gesprächs:** Der Meeting-Stand wird beim Öffnen der Sitzung mitgegeben. Was
  danach passiert, hört Nestor direkt, Agenda und Ergebnisse aktualisiert er aber erst in der nächsten
  Sitzung.
- **Lautstärke im Raum:** Der Laptoplautsprecher reicht für einen kleinen Raum. Für 5 Personen am Tisch
  eher einen kleinen Lautsprecher anschließen; das Konferenzmikro mit eigenem Lautsprecher hat meist
  bessere Echo-Unterdrückung.
- **Wer fragt:** Nestor kennt die Sprecher als „Person N“ bzw. mit dem Namen aus der Namensrunde; im
  Nachfrage-Fenster zählt die Sprecherzuordnung nur als Plus-Signal (dafür ist sie zu unsicher).
- **Fehlauslöser (Premium):** Fällt der Name im normalen Gespräch („wie Nestor vorhin sagte“), antwortet er. Ein
  seltener Name verringert das. In Basis gibt es das nicht (Funkgerät).

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
