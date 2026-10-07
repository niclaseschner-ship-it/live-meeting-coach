/**
 * Nestor-Worker (Ticket #5): prüft das Kundenpasswort, wählt je Meeting einen eigenen Container und reicht
 * die Datenspende nach R2 weiter. Ausgerollt wird in diesem Ticket nichts – nur gebaut und mit
 * `wrangler deploy --dry-run` geprüft (Workers-Paid-Plan fehlt noch).
 *
 * Zugehörige Doku: ../docs/lastenheft.md (Abschnitte 2, 5, 6) und README.md in diesem Ordner.
 */

import { Container, getContainer } from "@cloudflare/containers";
import { cookieLesen, cookiePruefen, cookieSigniere, kundeFuerPasswort, type Kundenliste } from "./anmeldung";
import { KundenZaehler } from "./zaehler";

export { KundenZaehler };

export interface Env {
  NESTOR: DurableObjectNamespace<Nestor>;
  ZAEHLER: DurableObjectNamespace<KundenZaehler>;
  SPENDEN: R2Bucket;
  ASSETS: Fetcher; // Bilder der Anmeldeseite
  PAYPAL_ME?: string; // Secret – PayPal.me-Name für die Unterstützung
  IMPRESSUM_NAME?: string; // Secret – Impressum und Datenschutz
  IMPRESSUM_MAIL?: string;
  IMPRESSUM_ANSCHRIFT?: string; // optional; ohne Anschrift entfällt die Zeile
  KUNDEN: string; // Secret, JSON: {"<kunde>": {"hash": "<sha256 hex>", "max_meetings": 3}}
  COOKIE_GEHEIMNIS: string; // Secret – signiert das Kunden-Cookie
  WORKER_GEHEIMNIS: string; // Secret – beweist dem Coach, dass eine Anfrage vom Worker kommt
  OPENAI_API_KEY: string; // Secret – Niclas' Schlüssel, eigenes OpenAI-Projekt mit Ausgabenlimit
  WORKER_URL: string; // Var – eigene Adresse, für den Rückruf aus dem Container (Datenspende); nach dem
  // ersten Deploy in wrangler.jsonc eintragen, siehe README.md
}

/** Der Nestor-Container selbst: ein Image, 8080, schläft nach Ruhe ein (siehe README zur Begründung). */
export class Nestor extends Container<Env> {
  defaultPort = 8080;
  // Während eines laufenden Meetings schickt der Browser durchgehend Audio über /ws/audio (alle ~100 ms,
  // beide Modi – Lastenheft §3) – das sind eingehende Anfragen auf der offenen WebSocket und halten den
  // Container während des GANZEN Meetings wach, unabhängig von sleepAfter. Dieser Wert deckt nur die
  // Einrichtungsphase davor ab (Agenda tippen, Regeln wählen), in der es länger keine Anfrage geben kann.
  sleepAfter = "20m";

  constructor(ctx: ConstructorParameters<typeof Container<Env>>[0], env: Env) {
    super(ctx, env);
    this.envVars = {
      LMC_BETRIEB: "cloud",
      LMC_WORKER_GEHEIMNIS: env.WORKER_GEHEIMNIS,
      LMC_WORKER_URL: env.WORKER_URL,
      OPENAI_API_KEY: env.OPENAI_API_KEY,
      // Startseite, Rechtstexte, Unterstützung – als Secrets gesetzt, damit nichts davon im Repo steht
      LMC_PAYPAL_ME: env.PAYPAL_ME ?? "",
      LMC_IMPRESSUM_NAME: env.IMPRESSUM_NAME ?? "",
      LMC_IMPRESSUM_MAIL: env.IMPRESSUM_MAIL ?? "",
      LMC_IMPRESSUM_ANSCHRIFT: env.IMPRESSUM_ANSCHRIFT ?? "",
    };
  }
}

const KUNDE_COOKIE = "nestor_kunde";
const MEETING_COOKIE = "nestor_meeting";
const DREISSIG_TAGE = 30 * 24 * 60 * 60;

function kundenliste(env: Env): Kundenliste {
  try {
    return JSON.parse(env.KUNDEN) as Kundenliste;
  } catch {
    return {};
  }
}

function setzeCookie(antwort: Response, name: string, wert: string, maxAge: number): Response {
  const kopie = new Response(antwort.body, antwort);
  kopie.headers.append(
    "Set-Cookie",
    `${name}=${encodeURIComponent(wert)}; Max-Age=${maxAge}; Path=/; HttpOnly; Secure; SameSite=Lax`,
  );
  return kopie;
}

// Anmeldeseite: die einzige Seite ohne Login. Idee und Bilder ja, aber kein Angebot im Sinne eines Dienstes –
// Impressum und Datenschutz liegen hinter dem Login (Niclas, 07.10.2026: privates Projekt, Zugang auf Einladung).
const TEASER = [
  ["fokus", "Eure Runde. Ein gemeinsamer Fokus."],
  ["fragen", "Frag Nestor. Komm weiter."],
  ["recherche", "Fehlt Wissen? Nestor schaut nach."],
  ["ergebnisse", "Klare Ergebnisse. Auch danach."],
];

const ANMELDEN_SEITE = (fehler: boolean) => `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Nestor</title>
<style>
  :root { --grund: #F8FAFC; --karte: #FFFFFF; --rand: #E2E8F0; --text: #0F172A; --text2: #475569; --tief: #1E1B4B; }
  @media (prefers-color-scheme: dark) {
    :root { --grund: #0B1020; --karte: #141A2E; --rand: #263049; --text: #E2E8F0; --text2: #94A3B8; --tief: #4F46E5; }
  }
  body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; background: var(--grund); color: var(--text);
         margin: 0; padding: 40px 16px; }
  main { max-width: 980px; margin: 0 auto; display: grid; gap: 28px; }
  header h1 { font-size: 30px; margin: 0 0 8px; }
  header p { color: var(--text2); font-size: 17px; line-height: 1.5; margin: 0; max-width: 640px; }
  .bilder { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .bilder figure { margin: 0; }
  .bilder img { width: 100%; height: auto; border-radius: 10px; border: 1px solid var(--rand); display: block; }
  .bilder figcaption { font-size: 13px; color: var(--text2); margin-top: 6px; }
  form { background: var(--karte); border: 1px solid var(--rand); border-radius: 14px; padding: 24px;
         max-width: 360px; box-sizing: border-box; width: 100%; }
  form h2 { font-size: 17px; margin: 0 0 4px; }
  p.unter { color: var(--text2); font-size: 14px; margin: 0 0 16px; }
  input { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid var(--rand); border-radius: 8px;
          font-size: 15px; margin-bottom: 12px; background: var(--grund); color: var(--text); }
  button { width: 100%; padding: 10px 12px; border: none; border-radius: 8px; background: var(--tief); color: #fff;
           font-size: 15px; cursor: pointer; }
  .fehler { color: #DC2626; font-size: 14px; margin: 0 0 12px; }
  footer { color: var(--text2); font-size: 13px; }
  @media (max-width: 720px) { .bilder { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<main>
  <header>
    <h1>Nestor</h1>
    <p>Die Idee: ein Begleiter für Besprechungen, der Agenda, Zeit und Gesprächsfluss im Blick behält, auf Zuruf
      hilft und am Ende festhält, was entschieden wurde. Die Gruppe entscheidet, Nestor unterstützt.</p>
  </header>
  <section class="bilder">
    ${TEASER.map(([datei, text]) =>
      `<figure><img src="/teaser/${datei}.webp" alt="${text}" loading="lazy" /><figcaption>${text}</figcaption></figure>`,
    ).join("")}
  </section>
  <form method="post" action="/anmelden">
    <h2>Anmelden</h2>
    <p class="unter">Privates Testprojekt, Zugang nur auf Einladung.</p>
    ${fehler ? '<p class="fehler">Passwort nicht erkannt.</p>' : ""}
    <input type="password" name="passwort" placeholder="Passwort" autofocus required />
    <button type="submit">Anmelden</button>
  </form>
  <footer>Ein privates Projekt von Niclas Eschner.</footer>
</main>
</body>
</html>`;

async function handleAnmelden(request: Request, env: Env): Promise<Response> {
  if (request.method === "GET") {
    const fehler = new URL(request.url).searchParams.has("falsch");
    return new Response(ANMELDEN_SEITE(fehler), { headers: { "content-type": "text/html; charset=utf-8" } });
  }
  const form = await request.formData();
  const passwort = String(form.get("passwort") ?? "");
  const kunde = await kundeFuerPasswort(passwort, kundenliste(env));
  if (!kunde) {
    return Response.redirect(new URL("/anmelden?falsch=1", request.url).toString(), 303);
  }
  const cookieWert = await cookieSigniere(kunde, env.COOKIE_GEHEIMNIS);
  const antwort = Response.redirect(new URL("/", request.url).toString(), 303);
  return setzeCookie(antwort, KUNDE_COOKIE, cookieWert, DREISSIG_TAGE);
}

/** Lädt Dateien zur Datenspende hoch (vom Coach selbst aufgerufen, siehe coach/ablage_r2.py). */
async function handleSpende(request: Request, env: Env, name: string): Promise<Response> {
  if (request.headers.get("X-Nestor-Geheimnis") !== env.WORKER_GEHEIMNIS) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const form = await request.formData();
  let anzahl = 0;
  for (const [dateiname, wert] of form.entries()) {
    if (typeof wert !== "string") {
      // FormDataEntryValue ist File | string; alles, was kein reiner Text ist, ist eine Datei
      await env.SPENDEN.put(`${name}/${dateiname}`, await (wert as File).arrayBuffer());
      anzahl++;
    }
  }
  return Response.json({ ok: true, dateien: anzahl });
}

/** Pfade, die ohne Anmeldung erreichbar bleiben: das Handy koppelt über den Kopplungscode. */
function offenOhneAnmeldung(pfad: string): boolean {
  return (
    pfad === "/handy" ||
    pfad === "/handy.webmanifest" ||
    pfad === "/sw.js" ||
    pfad.startsWith("/static/")
  );
}

/** Meeting-Start melden (Ticket #12): vom Coach aufgerufen (`coach/server.py`, echtes `/api/start`), NICHT vom
 * normalen Seitenaufruf – ein Meeting zählt beim Kunden erst jetzt, nicht schon beim Ansehen der Startseite. */
async function handleMeetingStart(request: Request, env: Env): Promise<Response> {
  if (request.headers.get("X-Nestor-Geheimnis") !== env.WORKER_GEHEIMNIS) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const { meetingId, kunde } = (await request.json()) as { meetingId?: string; kunde?: string };
  if (!meetingId || !kunde) return new Response("meetingId/kunde fehlen.", { status: 400 });
  const maxMeetings = kundenliste(env)[kunde]?.max_meetings ?? 1;
  const zaehler = env.ZAEHLER.get(env.ZAEHLER.idFromName(kunde));
  const antwort = await zaehler.fetch("https://zaehler/pruefen", {
    method: "POST",
    body: JSON.stringify({ meetingId, maxMeetings }),
  });
  return Response.json(await antwort.json());
}

/** Meeting-Ende melden (Ticket #12): vom Coach aufgerufen (`coach/api_abschluss.py`, `/api/abschluss/fertig`,
 * als Hintergrundaufgabe erst NACH der Antwort an den Browser). Gibt den Platz im KundenZaehler sofort frei und
 * stoppt den Container – `stop()` (SIGTERM; Doku: developers.cloudflare.com/containers/container-class/) reicht
 * für ein regulär beendetes Meeting, `destroy()` (SIGKILL) wäre nur für ein erzwungenes Ende nötig. */
async function handleMeetingEnde(request: Request, env: Env): Promise<Response> {
  if (request.headers.get("X-Nestor-Geheimnis") !== env.WORKER_GEHEIMNIS) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const { meetingId, kunde } = (await request.json()) as { meetingId?: string; kunde?: string };
  if (!meetingId) return new Response("meetingId fehlt.", { status: 400 });
  if (kunde) {
    const zaehler = env.ZAEHLER.get(env.ZAEHLER.idFromName(kunde));
    await zaehler.fetch("https://zaehler/beenden", { method: "POST", body: JSON.stringify({ meetingId }) });
  }
  const container = getContainer(env.NESTOR, meetingId);
  try {
    await container.stop();
  } catch {
    // Container war evtl. schon gestoppt oder eingeschlafen – kein Fehler für den Aufrufer, der Platz im
    // Zähler ist zu diesem Zeitpunkt ohnehin schon frei.
  }
  return Response.json({ ok: true });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const pfad = url.pathname;

    if (pfad.startsWith("/intern/spende/")) {
      return handleSpende(request, env, decodeURIComponent(pfad.slice("/intern/spende/".length)));
    }
    if (pfad === "/intern/meeting-start") {
      return handleMeetingStart(request, env);
    }
    if (pfad === "/intern/meeting-ende") {
      return handleMeetingEnde(request, env);
    }
    if (pfad === "/anmelden") {
      return handleAnmelden(request, env);
    }
    if (pfad.startsWith("/teaser/")) {
      return env.ASSETS.fetch(request); // Bilder der Anmeldeseite (cloudflare/oeffentlich/teaser/)
    }

    const kunde = await cookiePruefen(cookieLesen(request.headers.get("Cookie"), KUNDE_COOKIE), env.COOKIE_GEHEIMNIS);
    if (!kunde && !offenOhneAnmeldung(pfad)) {
      return Response.redirect(new URL("/anmelden", request.url).toString(), 303);
    }

    // Meeting-Zuordnung: Cookie, sonst ?meeting= aus dem QR-Code, sonst (nur mit Login) ein neues Meeting. Zählt
    // hier noch NICHT gegen max_meetings (Ticket #12) – das meldet der Coach erst beim echten Start
    // (`/api/start` → `/intern/meeting-start`), damit das bloße Ansehen der Startseite niemanden blockiert.
    let meetingId = url.searchParams.get("meeting") ?? cookieLesen(request.headers.get("Cookie"), MEETING_COOKIE);
    let cookieSetzen: string | null = null;
    if (!meetingId) {
      if (!kunde) {
        return new Response("Kein Meeting zugeordnet – bitte den QR-Code am Dashboard scannen.", { status: 400 });
      }
      meetingId = crypto.randomUUID();
      cookieSetzen = meetingId;
    } else if (url.searchParams.get("meeting") && kunde) {
      cookieSetzen = meetingId; // aus der QR-URL übernommen (Handy) – eigenes Cookie, damit es gekoppelt bleibt
    }

    const kopfzeilen = new Headers(request.headers);
    kopfzeilen.set("X-Nestor-Geheimnis", env.WORKER_GEHEIMNIS);
    kopfzeilen.set("X-Nestor-Meeting", meetingId);
    if (kunde) kopfzeilen.set("X-Nestor-Kunde", kunde);
    const weitergeleitet = new Request(request, { headers: kopfzeilen });

    const container = getContainer(env.NESTOR, meetingId);
    let antwort = await container.fetch(weitergeleitet);
    if (cookieSetzen) antwort = setzeCookie(antwort, MEETING_COOKIE, cookieSetzen, DREISSIG_TAGE);
    return antwort;
  },
} satisfies ExportedHandler<Env>;
