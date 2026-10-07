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
   npx wrangler secret put KUNDEN                # siehe "Kunden pflegen" unten
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
Browser ──Passwort──► /anmelden (Worker, Cookie nestor_kunde, signiert mit COOKIE_GEHEIMNIS)
Browser ──Anfrage───► Worker prüft Cookie, wählt/erzeugt Meeting-ID (Cookie nestor_meeting)
Worker  ──fetch()───► Container (idFromName(meetingId)), Kopfzeilen X-Nestor-Geheimnis/-Kunde/-Meeting
Coach   ──/intern/spende/<name>──► Worker (X-Nestor-Geheimnis) ──► R2 (nestor-spenden)
```

Innen (`coach/zugang.py`) gibt es im Cloud-Betrieb kein „am Laptop“ mehr: Eine Anfrage mit dem richtigen
`X-Nestor-Geheimnis` bekommt dieselben Rechte wie früher der Laptop, weil der Worker die eigentliche Prüfung
(das Kundenpasswort) schon gemacht hat. Ohne das Geheimnis gibt es 403 für alles – auch für Pfade, die sonst
offen sind (Handy, Rechtstexte) –, denn eine solche Anfrage ist gar nicht über den Worker gekommen.

Das Handy koppelt weiterhin über den Kopplungscode (`/handy?k=...`, unverändert in `coach/server.py`), nicht
über das Kundenpasswort – deshalb lässt der Worker `/handy` und seine Bausteine auch ohne `nestor_kunde`-
Cookie durch. Die Meeting-Zuordnung (welcher Container) läuft aber über den Worker: Der QR-Code, den
`/api/kopplung` zeigt, trägt `?meeting=<id>` (in der Cloud aus der Worker-Kopfzeile `X-Nestor-Meeting`, lokal
gibt es das nicht), damit das gescannte Handy im selben Container landet wie das Dashboard.

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

## `max_meetings` je Kunde

Umgesetzt, mit einer offenen Einschränkung (Abnahme erlaubt das: „sonst im Bericht begründen"):

Ein kleines Durable Object `KundenZaehler` (eins je Kunde, `src/zaehler.ts`) zählt bekannte Meeting-IDs. Ein
Meeting zählt, sobald der Worker es zum ersten Mal sieht; es zählt weiter, bis 6 Stunden lang keine Anfrage
mehr dafür kam (`VERFALL_MS`). Das ist eine Näherung: Der Worker erfährt vom tatsächlichen Ende eines
Meetings nicht, weil das Abschluss-Ticket (#3) in diesem Stand noch nicht existiert und keinen Rückruf zum
Worker macht. Ein gerade beendetes Meeting zählt darum bis zu 6 Stunden nach, und ein Kunde könnte knapp an
seinem Limit vorbeirutschen. Für v1 reicht das; ein echtes Ende-Signal (derselbe Mechanismus wie die
Datenspende: der Coach ruft beim Worker an) ist eine naheliegende Erweiterung für Ticket #3 – siehe
`src/zaehler.ts`, Kommentar am Kopf.

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

Prüft die Anmeldung (Passwort → Kunde über den SHA-256-Hash, ohne Namensfeld), die Cookie-Signatur
(signieren/prüfen/verwerfen bei falschem Geheimnis oder Manipulation) und die `max_meetings`-Zählung
(Limit, Verfall, keine Doppelzählung) – reine Funktionen, ohne Miniflare/Workers-Laufzeit nötig
(`src/anmeldung.ts`, `src/zaehler.ts`).
