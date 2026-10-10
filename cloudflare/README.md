# Nestor auf Cloudflare (Ticket #5)

Dieser Ordner ist der Cloudflare-Worker, der vor Nestor steht: Kundenpasswort prüfen, je Meeting einen
eigenen Container starten, Datenspenden nach R2 weiterleiten. Ausgerollt ist hier noch nichts – das Ticket
baut und prüft nur lokal (`wrangler deploy --dry-run`). Für den echten Betrieb fehlt der Workers-Paid-Plan
(5 $/Monat).

## Einrichten (wenn der Plan da ist)

1. **Plan buchen:** im Cloudflare-Dashboard auf Workers Paid wechseln (5 $/Monat, Voraussetzung für
   Containers).
2. **Anmelden:** `npx wrangler login` (braucht Node ≥ 22, siehe unten).
3. **Secrets setzen** (nie in wrangler.jsonc, nie ins Repo):
   ```
   npx wrangler secret put WORKER_GEHEIMNIS      # langer Zufallswert, z. B. `openssl rand -hex 32`
   npx wrangler secret put COOKIE_GEHEIMNIS      # ebenso, unabhängig vom WORKER_GEHEIMNIS
   npx wrangler secret put OPENAI_API_KEY        # Niclas' Schlüssel, eigenes Projekt mit Ausgabenlimit
   npx wrangler secret put MISTRAL_API_KEY       # Nestor Basis (Mistral, EU) – geht als LMC_MISTRAL_SCHLUESSEL in den Container
   npx wrangler secret put KUNDEN                # siehe "Kunden pflegen" unten
   npx wrangler secret put PAYPAL_ME             # Name aus paypal.me/<name>
   npx wrangler secret put IMPRESSUM_NAME
   npx wrangler secret put IMPRESSUM_MAIL
   npx wrangler secret put TELEGRAM_BOT_TOKEN  # private Live-Meldungen: Zugang, Login, Meeting Start/Ende
   npx wrangler secret put TELEGRAM_CHAT_ID
   # optional: IMPRESSUM_ANSCHRIFT (ohne entfällt die Zeile)
   ```
4. **Passwort-Hash erzeugen** (für das Secret `KUNDEN`) – SHA-256 des Klartext-Passworts, klein geschrieben:
   ```
   python3 -c "import hashlib; print(hashlib.sha256(input().encode()).hexdigest())"
   ```
   (Passwort eintippen, Enter – nichts wird protokolliert.) Alternativ mit Node:
   `node -e "crypto.subtle.digest('SHA-256', new TextEncoder().encode(process.argv[1])).then(b => console.log(Buffer.from(b).toString('hex')))" 'IhrPasswort'`
5. **R2-Bucket anlegen**, Jurisdiktion EU (Lastenheft §5):
   ```
   npx wrangler r2 bucket create nestor-spenden --jurisdiction=eu
   ```
6. **`WORKER_URL` eintragen:** nach dem ersten Deploy zeigt `wrangler deploy` die *.workers.dev-Adresse (oder
   die eigene Domain, falls eingerichtet). Diese Adresse in `wrangler.jsonc` unter `vars.WORKER_URL`
   eintragen (sie steht dort nur als Platzhalter) und erneut deployen – der Container braucht sie, um die
   Datenspende beim Worker abzuliefern (`coach/ablage_r2.py`).
7. **Deploy:** `npx wrangler deploy`.

## Kunden pflegen

Das Secret `KUNDEN` ist ein JSON-Objekt, ein Eintrag je Kunde:

```json
{ "firma-a": { "hash": "<sha256 hex>", "max_meetings": 3 },
  "firma-b": { "hash": "<sha256 hex>", "max_meetings": 1 } }
```

Einen Kunden hinzufügen oder sperren: die JSON-Datei lokal ändern und neu setzen
(`npx wrangler secret put KUNDEN` fragt interaktiv nach dem neuen Inhalt, oder `... < datei.json`). Einen
Kunden sperren heißt: seinen Eintrag entfernen (oder `max_meetings: 0` setzen) und neu setzen – es gibt kein
separates Nutzerkonto, das Passwort selbst ist die Identität (ein Formular-Feld, kein Name, siehe
`src/anmeldung.ts`).

## Wie es zusammenspielt

```
Browser ──Passwort──► /anmelden (Worker, Cookie nestor_kunde, signiert MIT Ablaufzeit in COOKIE_GEHEIMNIS)
Browser ──Anfrage───► Worker prüft Cookie, wählt/erzeugt Meeting-ID (signiertes Cookie nestor_meeting)
Worker  ──fetch()───► Container (idFromName(meetingId)), Kopfzeilen X-Nestor-Geheimnis/-Kunde/-Meeting
Coach   ──/intern/spende/<name>──► Worker (X-Nestor-Geheimnis) ──► R2 (nestor-spenden)
Coach   ──/intern/kopplungstoken──► Worker (X-Nestor-Geheimnis) ──► signiertes, kurzlebiges QR-Token
```

Innen (`coach/zugang.py`) gibt es im Cloud-Betrieb kein „am Laptop“ mehr: Eine Anfrage mit dem richtigen
`X-Nestor-Geheimnis` bekommt dieselben Rechte wie früher der Laptop, weil der Worker die eigentliche Prüfung
(das Kundenpasswort) schon gemacht hat. Ohne das Geheimnis gibt es 403 für alles – auch für Pfade, die sonst
offen sind (Handy, Rechtstexte) –, denn eine solche Anfrage ist gar nicht über den Worker gekommen.

Das Handy koppelt weiterhin über den Kopplungscode (`/handy?k=...`, unverändert in `coach/server.py`), nicht
über das Kundenpasswort – deshalb lässt der Worker `/handy` und seine Bausteine auch ohne `nestor_kunde`-
Cookie durch (siehe „Worker-Härtung“ unten: nur mit gültiger Signatur, nie mit einer rohen Meeting-ID). Die
Meeting-Zuordnung (welcher Container) läuft über den Worker: Der QR-Code, den `/api/kopplung` zeigt, trägt
`?meeting=<kopplungstoken>` – ein vom Worker signiertes, 15 Minuten gültiges Token (`/intern/kopplungstoken`,
aus der Worker-Kopfzeile `X-Nestor-Meeting` gebaut; lokal gibt es das nicht), damit das gescannte Handy im
selben Container landet wie das Dashboard, ohne dass die Meeting-ID selbst im Klartext in der URL steht.

## Instanztyp und Preis je Meetingstunde

Gewählt: **`standard-1`** (1/2 vCPU, 4 GiB RAM, 8 GB Disk) – die kleinste Stufe, die die Ticket-Vorgabe
„mind. 1/2 vCPU und 2 GiB" erfüllt (Stand der [Platform-Limits-Doku](https://developers.cloudflare.com/containers/platform/limits/),
07.10.2026):

| Stufe | vCPU | RAM | Disk |
|---|---|---|---|
| lite | 1/16 | 0,25 GiB | 2 GB |
| basic | 1/4 | 1 GiB | 4 GB |
| **standard-1** | **1/2** | **4 GiB** | **8 GB** |
| standard-2 | 1 | 6 GiB | 12 GB |

`basic` hätte zu wenig RAM (1 GiB, das Image allein braucht beim Start schon ~50 MiB, die lokalen Modelle
dazu, und Whisper-/Diarisierungs-Puffer brauchen Raum) – `standard-1` ist die erste Stufe, die beides
erfüllt.

Preis (Workers-Paid-Plan, [Pricing-Doku](https://developers.cloudflare.com/containers/pricing/), 07.10.2026):
vCPU 0,000020 $/vCPU-Sekunde, RAM 0,0000025 $/GiB-Sekunde, Disk 0,00000007 $/GB-Sekunde.

Je Meetingstunde (3600 s) bei `standard-1`, **ohne** die monatliche Freimenge:

- vCPU: 0,5 × 0,000020 × 3600 ≈ **0,036 $**
- RAM: 4 × 0,0000025 × 3600 ≈ **0,036 $**
- Disk: 8 × 0,00000007 × 3600 ≈ **0,002 $**
- **≈ 0,074 $ je Meetingstunde** Container-Laufzeit (dazu kommen die OpenAI-Kosten aus dem Lastenheft, ~2 $/h)

Die Freimenge pro Monat (25 GiB-h RAM, 375 vCPU-min, 200 GB-h Disk) deckt bei `standard-1` ungefähr die
ersten 6 Meetingstunden ab, danach gilt der Preis oben.

## EU-Prüfung (`constraints.jurisdiction`)

Ergebnis: **`constraints.jurisdiction: "eu"` funktioniert für diesen Container** – siehe `wrangler.jsonc`. Der
lokale `npx wrangler deploy --dry-run` akzeptiert die Einstellung ohne Fehler.

Hintergrund (wichtig, weil es leicht durcheinandergeht): [cloudflare/workers-sdk#15995](https://github.com/cloudflare/workers-sdk/issues/15995)
beschreibt genau diesen Fehler – „Unsupported fields for Durable Object-managed Containers in containers:
'constraints'" – aber **nur** für Container mit `scheduling_policy: "durable_object"` (der Modus, in dem die
App selbst bei jedem Start Image und Instanzgröße per `container.start({...})` angibt, z. B. bei
`@cloudflare/sandbox`). Das Issue wurde als „not planned" geschlossen.

Unser Container nutzt die **Standard-Policy** (`scheduling_policy` weggelassen = `"default"`): ein Image, eine
`instance_type`, zentral in `wrangler.jsonc` – das ist der ältere, von Anfang an unterstützte Modus, für den
`constraints` schon existierte, bevor es ihn für `durable_object` überhaupt gab (im verlinkten Issue selbst
als Referenz genannt: #13570). Dass unser Container über eine Durable-Object-Bindung angesprochen wird (jedes
`@cloudflare/containers`-Setup läuft so), ist nicht dasselbe wie `scheduling_policy: "durable_object"` – das
hat uns beim ersten Lesen des Issues auch kurz verwirrt.

Zusätzlich beschränkt der Worker-Code (`src/index.ts`) die Durable Object selbst auf `eu`, falls `wrangler`
das für eine implizite (Binding-)Namespace künftig unterstützt – aktuell geschieht die Platzierung der
Steuerungs-DO wie üblich (nächstgelegen zur ersten Anfrage); das betrifft nur die paar Kilobyte
Koordinationszustand (Meeting-ID, Cookie-Zuordnung), nicht die Meetinginhalte selbst, die ausschließlich im
`eu`-beschränkten Container liegen.

## `sleepAfter`

Gesetzt auf **`20m`** (`src/index.ts`, Klasse `Nestor`). Begründung in zwei Teilen:

1. **Während des Meetings** ist das kein Problem: Beide Modi (Lastenheft §3, „Live" und „Auf Knopfdruck")
   schicken den Ton durchgehend zum Server, alle ~100 ms über die offene WebSocket `/ws/audio`
   (`coach/server.py`, `ws_audio`) – das sind laufend eingehende Anfragen auf der Verbindung, die den
   Inaktivitäts-Timer unabhängig von seiner Länge immer wieder zurücksetzen. Ein laufendes Meeting schläft
   also nicht ein, ganz unabhängig vom genauen `sleepAfter`-Wert.
2. **Vor dem Meeting** (Einrichtungsphase: Agenda per Prompt tippen, Gesprächsregeln wählen) kann es länger
   keine Anfrage geben, während jemand nachdenkt oder einen Text formuliert – dafür ist der Puffer.

Zur Doku-Lage: Die [Container-Class-Referenz](https://developers.cloudflare.com/containers/container-class/)
sagt nur allgemein „Activity resets the timer", ohne eine offene, aber gerade stille WebSocket-Verbindung
ausdrücklich einzuschließen. Das von Cloudflare dokumentierte Low-Level-Beispiel mit einer eigenen
`DurableObject`-Klasse ist dagegen eindeutig: „An open WebSocket connection maintains Durable Object
activity" ([Durable-Object-Interface-Beispiel](https://developers.cloudflare.com/containers/examples/durable-object-interface/)).
Da unser Fall ohnehin durchgehend **Daten** über die Verbindung schickt (nicht nur eine offene, stille
Verbindung), reicht auch die enger gelesene Variante der Doku („eingehende Anfragen setzen zurück") aus, um
sicher zu sein. `20m` ist deshalb bewusst großzügig für die Einrichtungsphase gewählt, nicht weil das Meeting
selbst länger bräuchte.

## `max_meetings` je Kunde (Ticket #12: Start- und Ende-Signal)

Ein kleines Durable Object `KundenZaehler` (eins je Kunde, `src/zaehler.ts`) zählt gestartete Meeting-IDs.
Anders als im ursprünglichen Stand (Ticket #5) zählt ein Meeting nicht mehr schon beim ersten Seitenaufruf:

- **Start:** `coach/server.py` meldet den echten Start (`POST /api/start`, nicht das bloße Ansehen der
  Startseite) an den Worker: `POST /intern/meeting-start` mit `X-Nestor-Geheimnis`, Meeting-ID und Kunde. Erst
  das zählt gegen `max_meetings` (`zaehler-logik.ts`, `pruefenUndAktualisieren`).
- **Aktives Ende:** `coach/api_abschluss.py` meldet „Fertig“ (`POST /api/abschluss/fertig`) als
  Hintergrundaufgabe – also erst, nachdem die Antwort beim Browser ist – an den Worker: `POST
  /intern/meeting-ende`. Der Worker gibt den Platz sofort frei (`beenden()`) **und stoppt den Container**
  (`getContainer(env.NESTOR, meetingId).stop()`, SIGTERM; `destroy()`/SIGKILL wäre nur für ein erzwungenes Ende
  nötig – Doku: [Container-Class-Referenz](https://developers.cloudflare.com/containers/container-class/),
  Stand 08.10.2026: „`stop()` sends a signal to the container … defaults to SIGTERM … triggers `onStop`“,
  „`destroy()` … sends SIGKILL“). Der Worker löscht dabei nicht selbst das Meeting-Cookie – das tut `coach/
  api_abschluss.py` direkt in seiner Antwort an den Browser (derselbe Pfad, den der Worker ohnehin nur
  durchreicht), damit der nächste Aufruf ein neues Meeting bekommt.
- **Ohne „Fertig“** (Browser zu, Absturz, Netz weg): Der Platz fällt nach `VERFALL_MS` = 30 Minuten ohne
  Anfrage automatisch frei (vorher 6 Stunden) – weiterhin eine Näherung, jetzt aber nur noch die
  Rückfalllösung für den selteneren Fall, nicht mehr der einzige Weg. Der Container selbst schläft davon
  unabhängig weiter nach `sleepAfter` (siehe unten).

Siehe `src/zaehler.ts` und `src/zaehler-logik.ts` (Kommentare am Kopf) für Einzelheiten; Tests in
`src/zaehler.test.ts`.

Daneben gilt weiter `max_instances: 10` (global, alle Kunden zusammen) in `wrangler.jsonc`.

## Bauen: Pi oder Windows-Laptop?

Cloudflare Containers brauchen `linux/amd64`, der Pi ist `arm64`. Geprüft (07.10.2026, auf dem Pi):

- `docker buildx build --platform linux/amd64 ...` funktioniert auf dem Pi – QEMU-Emulation ist installiert
  (`docker run --privileged --rm tonistiigi/binfmt --install all`) und der Bau lief durch, ohne dass eine
  einzige Python-Abhängigkeit aus dem Quellcode kompiliert werden musste (sherpa-onnx, onnxruntime & Co.
  haben fertige `manylinux`-Wheels für `x86_64`, genau wie für `aarch64`). Dauer unter Emulation: einige
  Minuten für den `pip install`-Schritt (statt Sekunden nativ), Speicher blieb dabei durchgehend über 2,5 GB
  frei.
- `npx wrangler deploy --dry-run` baut das Image sogar selbst (ebenfalls amd64) und war genauso erfolgreich.

**Empfehlung:** Für den echten Deploy auf dem Pi bauen (mit `docker buildx build --platform linux/amd64 ...`
bzw. direkt `wrangler deploy`, das baut automatisch) – ein eigener Windows-Build-Schritt ist nicht nötig. Der
einzige Haken ist nicht die Architektur, sondern Node: `wrangler` ≥ 4.87 verlangt Node ≥ 22 (siehe unten),
der Pi hat aktuell 20.20.2.

## Node-Version

`wrangler` ist in diesem Ordner auf **4.86.0** gepinnt (`package.json`), weil neuere Fassungen (ab 4.87, auch
die zum Zeitpunkt des Tickets aktuelle 4.148) `Node ≥ 22` fest verlangen und sich auf dem Pi (Node 20.20.2)
nicht einmal starten lassen („Wrangler requires at least Node.js v22.0.0"). Vor dem echten Deploy lohnt sich
ein Node-Upgrade auf dem Build-Rechner (z. B. per `nvm`), danach kann `wrangler` wieder auf die aktuelle
Fassung gehoben werden – `4.86.0` ist nur die Brücke für diesen Teststand.

## Tests

```
npm install
npm test
```

## Pilotzugang per Mail-PIN

Neue Interessenten registrieren sich mit Name, E-Mail-Adresse und „Woher kennst du Niclas?“. Der Worker speichert
die Liste im bereits EU-gebundenen R2-Bucket unter `pilot/interessenten/`, verschickt über den vorhandenen Gmail-SMTP-Zugang einen sechsstelligen, zehn Minuten gültigen PIN und setzt nach erfolgreicher
Prüfung das bisherige signierte Kunden-Cookie. Standardmäßig werden neue Einträge sofort freigeschaltet;
`AUTO_FREIGABE=0` setzt sie auf `wartet`. Die Liste ist intern über `GET /intern/interessenten` mit
`X-Nestor-Geheimnis` abrufbar. Bestehende Passwortzugänge bleiben vorerst unter `/anmelden?alt=1` erhalten.

Vor dem ersten Deploy einmalig:

```bash
npx wrangler secret put GMAIL_SMTP_PASSWORT
npx wrangler secret put PIN_GEHEIMNIS
npx wrangler secret put MAIL_VON
```

`MAIL_VON` ist die zum Gmail-App-Passwort gehörende Adresse. PINs werden nur gehasht gespeichert, laufen nach zehn
Minuten ab und sind auf fünf Fehlversuche begrenzt. Für Produktion sollte zusätzlich ein Bot-Schutz ergänzt werden,
wenn die öffentliche Registrierung missbraucht wird.

Prüft die Anmeldung (Passwort → Kunde über den SHA-256-Hash, ohne Namensfeld), die Cookie-Signatur
(signieren/prüfen/verwerfen bei falschem Geheimnis oder Manipulation) und die `max_meetings`-Zählung
(Limit, Verfall nach 30 min, keine Doppelzählung, aktives `beenden()` gibt sofort frei – Ticket #12) – reine
Funktionen, ohne Miniflare/Workers-Laufzeit nötig (`src/anmeldung.ts`, `src/zaehler-logik.ts`). Die neuen
`/intern/meeting-start`/`/intern/meeting-ende`-Routen in `index.ts` selbst (Container `stop()`, Cookie-Pfad)
brauchen die Workers-Laufzeit und sind darum nicht separat unit-getestet – geprüft über `tsc --noEmit` und,
für den Rückruf von der Coach-Seite, `tests/test_meeting_ende.py` (Python, Netz gemockt).

## Worker-Härtung (Ticket #63)

Befund eines Sicherheits- und Architekturreviews (10.10.2026): `/handy?meeting=<beliebig>` konnte vorher direkt
einen Container starten, das Kunden-Cookie lief serverseitig nie ab, Sperren wirkte nicht sofort, `/anmelden`
und `/pin` hatten keine IP-Begrenzung, `/intern/*` verglich das Geheimnis nicht zeitkonstant, und es fehlten
Sicherheitsheader. Behoben:

- **Signierte Meeting-Identität** (`src/meeting.ts`): `nestor_meeting` ist ein HMAC-signiertes Cookie
  (Meeting-ID + Kunde + Ablaufzeit), das QR-Kopplungstoken ein eigener, kurzlebiger (15 min) signierter Wert –
  beide über das vorhandene `COOKIE_GEHEIMNIS`, mit getrennten Zwecken ("meeting"/"kopplung"), damit sich
  keiner als der andere ausgeben lässt. `index.ts` ruft `getContainer` nur noch mit einer so geprüften
  Meeting-ID auf; ein fremder, unsignierter oder abgelaufener Wert in `?meeting=` oder im Cookie startet
  keinen Container mehr. Der Coach kennt `COOKIE_GEHEIMNIS` nicht und holt sich das Kopplungstoken für den
  QR-Code über die neue, durch `WORKER_GEHEIMNIS` geschützte Route `POST /intern/kopplungstoken`
  (`coach/server.py`, `/api/kopplung`). Die QR-Kopplung ohne Login am Handy funktioniert unverändert – das
  Token trägt den Kunden mit, das Handy braucht kein eigenes Login-Cookie.
- **Kunden-Cookie mit Ablauf** (`src/anmeldung.ts`, `signiereMitAblauf`/`pruefeMitAblauf`): `nestor_kunde` trägt
  seine Ablaufzeit jetzt im signierten Wert selbst, nicht mehr nur im (clientseitigen) `Max-Age`.
- **„Gesperrt“ wirkt sofort** (`src/pilotzugang.ts`, `kundeAktiv`): ein Cache von höchstens 5 Minuten je
  Worker-Isolate hält den Interessenten-Status vor, statt bei jeder Anfrage R2 zu lesen – ein Sperren wirkt so
  binnen spätestens 5 Minuten, nicht erst nach 30 Tagen (Cookie-Ablauf). `maxMeetingsFuer` liefert für
  `gesperrt`/`wartet` jetzt `0` statt `1`. `AUTO_FREIGABE` selbst ist unverändert (Entscheidung steht aus).
- **IP-Ratenbegrenzung** (`src/ratenbegrenzung.ts`/`-logik.ts`, Durable Object `IpZaehler`, Binding
  `RATENBEGRENZUNG`): `/anmelden` erlaubt 8, `/pin` 20 Versuche je IP und 10 Minuten, zusätzlich zur
  bestehenden Pro-Adresse-Sperre. `/anmelden` antwortet jetzt unabhängig davon, ob die Mailadresse schon
  registriert ist, mit derselben Seite (keine Enumeration mehr über den Status-Code).
- **Zeitkonstanter Vergleich für `/intern/*`** (`src/sicherheit.ts`, `workerGeheimnisPasst`): ersetzt den
  bisherigen `!==`-Vergleich des Worker-Geheimnisses an allen vier `/intern/*`-Routen.
- **Sicherheitsheader auf jeder Antwort** (`src/sicherheit.ts`, `mitSicherheitsheadern`): `Content-Security-
  Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin` – auf allen vom Worker erzeugten Seiten UND auf jeder vom Container
  durchgereichten Antwort (einzige Aufrufstelle im `fetch`-Export). Die CSP ist an die tatsächlich genutzten
  Quellen angepasst (`script-src 'self'`, `style-src 'self' 'unsafe-inline'` nur als schmale, dokumentierte
  Ausnahme für die Inline-`<style>`-Blöcke der drei vom Worker selbst erzeugten Seiten – Anmeldung,
  Registrierung, PIN). Die zwei Inline-`<script>`-Blöcke, die das noch gebraucht hätten
  (`static/impressum.html`, `static/datenschutz.html`), wurden nach `static/rechtstexte.js` verschoben.
- **Freundliche Kapazitätsseite + Telegram-Meldung** (`src/sicherheit.ts`,
  `containerAufrufenOderAusweichen`): schlägt der Container-Aufruf fehl, sieht der Besucher „Gerade
  ausgelastet“ statt eines rohen Fehlers, und Niclas bekommt eine Telegram-Meldung mit dem Pfad und der
  Fehlermeldung.

**Löschfrist für nie aktivierte Interessenten:** Ein Interessent, der seinen Mail-Code nie eingibt (Status
bleibt `wartet`/`aktiv` ohne je einzuloggen), soll **30 Tage** nach `erstellt_at` aus `pilot/interessenten/*`
in R2 gelöscht werden – Minimierungsgrundsatz, bis der Pilotbetrieb über die Testphase hinausgeht. Das ist
bislang **nur diese Festlegung, nicht automatisiert**: R2 kennt kein TTL von sich aus, die Durchsetzung bräuchte
einen Cron Trigger (`wrangler.jsonc` → `triggers.crons`) mit einem eigenen `scheduled`-Handler, der
`interessentenListe` nach `erstellt_at` filtert und nie aktivierte, abgelaufene Datensätze löscht – das ist in
diesem Ticket nicht mehr enthalten (offene Folge-Aufgabe).

## Ausrollen und Zurückrollen (Ticket #65)

Es gibt nur noch EINEN Weg, Nestor auszurollen: **`deploy/deploy.sh`** im Repo-Wurzelordner. Die früheren
`/tmp/nestor_deploy.py`, `/tmp/nestor_rollout.py`, `/tmp/nestor_ui56_rollout.py` sind Geschichte – sie lagen
auf der RAM-Disk des Pi, waren nicht versioniert und trugen Konto-/Anwendungs-IDs als Literal im Quelltext.

```
deploy/deploy.sh [--dry-run] [--ohne-b] [--erzwingen] [--tag-push]
deploy/deploy.sh --ref <tag-oder-commit> [--erzwingen]      # Rollback / Re-Deploy
```

Was das Skript macht, in dieser Reihenfolge:

1. **Git-Stand sauber und gepusht** (`git status --porcelain` leer, `HEAD` == Upstream) – nur im Normalfall,
   nicht bei `--ref`.
2. **`scripts/pipeline.sh a`** (pytest, Worker-vitest, `tsc --noEmit`).
3. **GATE_B_C:** `logs/pipeline/<GIT_SHA>/b.ok` muss existieren – diese Markierung schreibt
   `scripts/pipeline.sh b` selbst, aber nur nach einem grünen Lauf über **beide** Stufen (Basis und Premium;
   ein Lauf mit `--stufe basis` oder `--stufe premium` allein reicht nicht). Fehlt sie, bricht der Deploy ab;
   `--ohne-b` übersteuert das mit einer lauten Warnung.
4. **`coach/version.json`** (gitignored) mit `git_sha` und `gebaut_am` (UTC) – landet über `COPY coach ./coach`
   automatisch im Image. Build-Args wurden geprüft (`containers[].image_vars` in `wrangler.jsonc` existiert
   und reicht `--build-arg` an `docker build` durch), aber das bräuchte einen pro Deploy veränderten Eintrag in
   der versionierten `wrangler.jsonc` – die Datei ist der einfachere, deterministische Weg.
5. Nur bei `--dry-run`: **`wrangler deploy --dry-run`** (baut das Image wirklich, lokal) und Schluss – kein
   echter Deploy, kein Rollout, kein Smoke-Test, kein Git-Tag. Braucht kein Cloudflare-Token.
6. Sonst: **keine laufenden Container-Instanzen** (Cloudflare-Containers-API, `deploy/rollout_warten.py
   instanzen`) – sonst Abbruch, außer mit `--erzwingen`.
7. **`wrangler deploy`** mit dem Cloudflare-Token aus `sudo -n zugang holen cloudflare-nestor`, ausschließlich
   per Umgebungsvariable `CLOUDFLARE_API_TOKEN` an den Unterprozess, nie als Datei oder Log-Zeile. Dabei
   `--var GIT_SHA:<sha> --var BUILD_ZEIT:<zeit> --keep-vars` – das sind die Felder, die die Worker-Route
   `/version` zeigt (siehe unten).
8. **Rollout abwarten** (`deploy/rollout_warten.py neuester-tag` + `warten --tag <tag>`, Logik aus dem
   früheren `/tmp/nestor_rollout.py` – jetzt ohne hart kodierte Konto-/Anwendungs-ID: beide kommen aus
   `CLOUDFLARE_ACCOUNT_ID`/`NESTOR_APPLICATION_ID`, mit automatischer Ermittlung über `wrangler whoami --json`
   bzw. `wrangler containers list --json`, falls nicht gesetzt).
9. **Smoke-Test** (`deploy/smoke.py`): Pflicht ist `GET <WORKER_URL>/version` – eine Route direkt im Worker
   (`cloudflare/src/index.ts`), ohne Login und ohne Container, zeigt den gerade deployten `GIT_SHA`. Zusätzlich,
   **falls erreichbar**: `GET /api/version` auf dem Container selbst (`coach/server.py`) – das geht nur mit
   einem gültigen, schon eingeloggten `nestor_kunde`-Cookie (Umgebungsvariable `NESTOR_SMOKE_COOKIE`); ohne sie
   wird dieser Teil übersprungen, nicht als Fehler gewertet (ein Container extra fürs Prüfen zu starten kostet
   Geld und einen der zehn Plätze).
10. **Git-Tag** `deploy-JJJJMMTT-HHMM` auf den deployten Commit; `git push` dafür nur mit `--tag-push`.

**Rollback** heißt `deploy/deploy.sh --ref <tag>` (z. B. ein vorheriger `deploy-...`-Tag, oder jeder Commit).
Das Skript checkt diesen Stand in einen eigenen, temporären Git-Worktree aus (räumt ihn danach wieder weg),
baut und deployt genau diesen Code – Tests und GATE_B_C werden übersprungen (der Stand war ja schon einmal
live), und es entsteht kein neuer Tag.

**Vor dem ersten echten Deploy prüfen** (in diesem Ticket nicht möglich, da kein echter Deploy erlaubt war):
Ob `wrangler whoami --json` wirklich ein `accounts`-Array mit `id` liefert und `wrangler containers list
--json` einen Eintrag mit `name: "nestor-nestor"` – beide Annahmen stammen aus dem Lesen des `wrangler`-Quelltexts
(Version 4.86.0), nicht aus einem echten Aufruf. Schlägt eine Ermittlung fehl, einfach `CLOUDFLARE_ACCOUNT_ID`
bzw. `NESTOR_APPLICATION_ID` von Hand exportieren, bevor `deploy.sh` läuft.
