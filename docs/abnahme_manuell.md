# Stufe D – Abnahme am echten Handy (10 Minuten)

Ticket #62. Was die Klick-E2E (Stufe B lokal, Stufe C auf Staging) nicht emulieren kann: echte Mikrofon-Hardware,
Raumakustik und Echo des eigenen Lautsprechers, iOS/Safari (WebKit-Medienrechte, Autoplay-/AudioContext-Freigabe,
Bildschirmsperre, PWA), Hörqualität der Stimme, Kamera-QR-Scan.

**Wann:** vor Pilot-Freigaben und nach Änderungen an `static/handy*`, `static/sw.js` oder der Audio-Wiedergabe/
-Aufnahme (`static/basis.js`, `coach/stimmen.py`) – dann verlangt `deploy/deploy.sh` für prod eine abgehakte
Checkliste (`logs/pipeline/<sha>/d.json`, Gate `GATE_C_D`). Nicht vor jedem Deploy.

**Gegen Staging, nicht prod:** `https://nestor-staging.niclas-eschner.workers.dev`, mit demselben Git-Stand, für den
Stufe C schon grün war (`deploy/deploy.sh --staging`, dann `scripts/pipeline.sh c`). Das Testpasswort steht nur in
`~/.cache/lmc-e2e/staging.env` auf dem Pi (`STAGING_PASSWORT`, nicht in der Hausablage):
`grep STAGING_PASSWORT ~/.cache/lmc-e2e/staging.env`. Telegram-Meldungen gibt es aus Staging keine. Kosten: wie ein
kurzes echtes Meeting (Premium ≈ 0,20–0,50 €, Basis wenige Cent).

**Ergebnis festhalten:** direkt danach am Pi `scripts/pipeline.sh d` – fragt die Punkte unten einzeln ab (j/n,
optional eine Notiz) und schreibt `logs/pipeline/<sha>/d.json`. Ein „n“ ist kein Versagen der Checkliste, sondern
ein Befund: Notiz schreiben, Ticket anlegen; `d.json` hat dann `"ok": false` und das Gate bleibt zu.

## Vorbereitung (vor der Uhr)

- Laptop mit Chrome oder Edge, ein **iPhone mit Safari** (wenn vorhanden zusätzlich ein Android-Handy mit Chrome).
- iPhone: **Stummschalter aus** (Schalter an der Seite / Action-Button – sonst bleibt Nestors Stimme in Safari
  stumm), Lautstärke halb, kein Bluetooth-Kopfhörer verbunden, Fokus-/Nicht-stören-Modus aus.
- iPhone: Einstellungen › Safari › Mikrofon auf „Fragen“ (nicht „Ablehnen“). Wer früher „Ablehnen“ getippt hat:
  Website-Einstellungen für `nestor-staging…workers.dev` zurücksetzen (aA-Menü in der Adressleiste › Website-
  Einstellungen).
- Raum: normal laut, Handy ~1 m vor den Sprechenden auf dem Tisch, Laptop-Lautsprecher leise.

## Checkliste

<!-- d-checkliste: scripts/pipeline.sh d liest genau diese Tabelle (Spalte „Prüfung“). Zeilen ergänzen ist ok. -->
| Min | Schritt | Prüfung |
|---|---|---|
| 0–1 | Laptop: Staging öffnen, Testpasswort, Karte **Premium** wählen | Pill zeigt „Premium“ |
| 1–2 | iPhone-**Kamera-App** scannt den QR-Code am Laptop (kein Login am Handy) | Handy-App öffnet sich in Safari, kein „Kein Meeting zugeordnet“, keine Code-Eingabe |
| 2–3 | Handy: „Mikrofon und Ton aktivieren“ tippen, Safari-Rechtedialog „Erlauben“ | Laptop: „Meeting starten“ wird binnen ~10 s klickbar |
| 3–5 | Laptop: Start, Begrüßung am Handy anhören | Stimme klingt nach Premium (Cedar), verständlich, keine Aussetzer oder Abbrüche |
| 5–7 | Laut sprechen: „Wir beschließen ein Budget von fünfhundert Euro.“ – „Anna schreibt bis Montag das Protokoll.“ – „Nestor, fass zusammen.“ | Transkript am Laptop richtig, Antwort am Handy hörbar, Karte im Verlauf |
| 7 | Während Nestor spricht: hört er sich selbst? (kein Echo-Satz von Nestor im Transkript) | Kein Selbstgespräch/Echo im Transkript |
| 7–8 | iPhone sperren (Seitentaste) 20 s, entsperren, Safari wieder nach vorn | Verbindet neu (Status grün), Ton und Mikro gehen weiter – sonst sichtbarer Hinweis zum erneuten Tippen |
| 8–9 | Laptop: Beenden, Paket (ZIP) herunterladen und öffnen | Protokoll nennt Budget und Annas Aufgabe; Handy zeigt die Abschluss-Phase |
| 9–10 | Laptop: neues Meeting mit Karte **Basis**, QR neu scannen, Start, am Handy die große Sprechtaste halten: „Wo stehen wir?“ | Stimme klingt nach Basis (Nova-euphorisch), Antwort kommt nach dem Loslassen |
| 10 | Optional: Handy-App als PWA („Zum Home-Bildschirm“) öffnen | Startet ohne Login direkt in die Kopplung bzw. das laufende Meeting |

## iPhone/Safari – worauf achten

- **Autoplay:** iOS gibt Ton nur nach einer Berührung frei. „Mikrofon und Ton aktivieren“ ist diese Berührung; bleibt
  die Begrüßung stumm, obwohl der Laptop „spricht“ anzeigt, ist das ein Befund (AudioContext nicht freigegeben).
- **Stummschalter:** Web-Audio folgt in Safari dem Stummschalter – „kein Ton“ erst nach dem Schalter-Check notieren.
- **Bildschirmsperre:** Safari friert Seiten im Hintergrund ein; WebSocket und Mikro sind nach dem Entsperren weg.
  Erwartet ist Wiederverbinden oder ein klarer Hinweis – nicht ein still totes Mikro.
- **Rechte:** Safari fragt je Sitzung erneut nach dem Mikrofon; zweimal fragen ist ok, ein Dauer-„Abgelehnt“ nicht.
- **Echo:** Am iPhone läuft die Echo-Unterdrückung der Hardware. Spricht Nestor laut und taucht sein eigener Satz im
  Transkript auf, Notiz mit Lautstärke und Abstand.
- **Android (falls zur Hand):** dieselbe Liste in Chrome; Unterschiede in der Notiz festhalten.
