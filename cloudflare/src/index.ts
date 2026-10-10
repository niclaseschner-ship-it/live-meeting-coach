/**
 * Nestor-Worker (Ticket #5): prüft das Kundenpasswort, wählt je Meeting einen eigenen Container und reicht
 * die Datenspende nach R2 weiter. Ausgerollt wird in diesem Ticket nichts – nur gebaut und mit
 * `wrangler deploy --dry-run` geprüft (Workers-Paid-Plan fehlt noch).
 *
 * Zugehörige Doku: ../docs/lastenheft.md (Abschnitte 2, 5, 6) und README.md in diesem Ordner.
 */

import { Container, getContainer } from "@cloudflare/containers";
import { cookieLesen, kundeFuerPasswort, pruefeMitAblauf, signiereMitAblauf, type Kundenliste } from "./anmeldung";
import { kopplungstokenPruefen, kopplungstokenSigniere, meetingCookiePruefen, meetingCookieSigniere, type MeetingTicket } from "./meeting";
import {
  interessentLesen, interessentenListe, interessentSpeichern, kundeAktiv, normalisiereAnmeldung, pinErzeugen,
  pinMailSenden, pinPruefen, pinSeite, registrierungsSeite, statusCacheErzeugen,
} from "./pilotzugang";
import { IpZaehler } from "./ratenbegrenzung";
import { containerAufrufenOderAusweichen, mitSicherheitsheadern, workerGeheimnisPasst } from "./sicherheit";
import { meetingKurz, telegramMelden } from "./telegram";
import { mitVariantenwahl } from "./variantenwahl";
import { KundenZaehler } from "./zaehler";

export { IpZaehler, KundenZaehler };

export interface Env {
  NESTOR: DurableObjectNamespace<Nestor>;
  ZAEHLER: DurableObjectNamespace<KundenZaehler>;
  RATENBEGRENZUNG: DurableObjectNamespace<IpZaehler>; // Ticket #63: IP-Ratenbegrenzung für /anmelden und /pin
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
  MISTRAL_API_KEY?: string; // Secret – Nestor Basis (Ticket #13); ohne ihn ist Basis auf der Startseite nicht wählbar
  GMAIL_SMTP_PASSWORT: string; // Secret – vorhandenes Gmail-App-Passwort für Login-PINs
  PIN_GEHEIMNIS: string; // Secret – hasht PINs vor der Ablage
  MAIL_VON: string; // Secret/Var – verifizierter Absender, z. B. Nestor <login@example.de>
  AUTO_FREIGABE?: string; // "0" = neue Interessenten warten auf manuelle Freigabe, sonst sofort aktiv
  TELEGRAM_BOT_TOKEN?: string; // Secret – bestehender privater Assistenten-Bot
  TELEGRAM_CHAT_ID?: string; // Secret – Niclas' privater Chat
  WORKER_URL: string; // Var – eigene Adresse, für den Rückruf aus dem Container (Datenspende); nach dem
  // ersten Deploy in wrangler.jsonc eintragen, siehe README.md
}

/** Der Nestor-Container selbst: ein Image, 8080, schläft nach Ruhe ein (siehe README zur Begründung). */
export class Nestor extends Container<Env> {
  private readonly wahlSpeicher: DurableObjectStorage;
  defaultPort = 8080;
  // Während eines laufenden Meetings schickt der Browser durchgehend Audio über /ws/audio (alle ~100 ms,
  // beide Modi – Lastenheft §3) – das sind eingehende Anfragen auf der offenen WebSocket und halten den
  // Container während des GANZEN Meetings wach, unabhängig von sleepAfter. Dieser Wert deckt nur die
  // Einrichtungsphase davor ab (Agenda tippen, Regeln wählen), in der es länger keine Anfrage geben kann.
  sleepAfter = "20m";

  constructor(ctx: ConstructorParameters<typeof Container<Env>>[0], env: Env) {
    super(ctx, env);
    this.wahlSpeicher = ctx.storage;
    this.envVars = {
      LMC_BETRIEB: "cloud",
      LMC_WORKER_GEHEIMNIS: env.WORKER_GEHEIMNIS,
      LMC_WORKER_URL: env.WORKER_URL,
      // Basis bleibt die Vorauswahl; Premium nutzt den serverseitigen Projektschlüssel.
      OPENAI_API_KEY: env.OPENAI_API_KEY ?? "",
      LMC_MISTRAL_SCHLUESSEL: env.MISTRAL_API_KEY ?? "",
      LMC_STUFE: "basis",
      // Startseite, Rechtstexte, Unterstützung – als Secrets gesetzt, damit nichts davon im Repo steht
      LMC_PAYPAL_ME: env.PAYPAL_ME ?? "",
      LMC_IMPRESSUM_NAME: env.IMPRESSUM_NAME ?? "",
      LMC_IMPRESSUM_MAIL: env.IMPRESSUM_MAIL ?? "",
      LMC_IMPRESSUM_ANSCHRIFT: env.IMPRESSUM_ANSCHRIFT ?? "",
    };
  }

  override async fetch(request: Request): Promise<Response> {
    return mitVariantenwahl(request, this.wahlSpeicher, r => super.fetch(r));
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

function melden(ctx: ExecutionContext, env: Env, text: string): void {
  ctx.waitUntil(telegramMelden(env, text).catch((e) => console.error("Telegram-Meldung fehlgeschlagen", e)));
}

/** Ein kurzlebiger, per Isolate gehaltener Cache: "gesperrt"/"wartet" wirkt binnen ≤5 min, ohne jede Anfrage
 * gegen R2 zu prüfen (Ticket #63, Befund 3 / U2). Siehe `kundeAktiv` in pilotzugang.ts für die Begründung. */
const statusCache = statusCacheErzeugen();

/** IP-Ratenbegrenzung für `/anmelden` und `/pin` (Ticket #63, Befund 2): ein `IpZaehler`-Durable-Object je
 * IP-Adresse, zusätzlich zur bestehenden Pro-Adresse-Sperre in pilotzugang.ts. Fehlt die IP (z. B. im Test),
 * teilen sich alle Anfragen ein gemeinsames Kontingent – sicherer als gar keine Begrenzung. */
async function ratenOk(env: Env, request: Request, zweck: string, limit: number, fensterMs: number): Promise<boolean> {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unbekannt";
  const stub = env.RATENBEGRENZUNG.get(env.RATENBEGRENZUNG.idFromName(ip));
  const antwort = await stub.fetch("https://ratenbegrenzung/pruefen", {
    method: "POST", body: JSON.stringify({ zweck, limit, fensterMs }),
  });
  const ergebnis = await antwort.json() as { erlaubt?: boolean };
  return !!ergebnis.erlaubt;
}

const ZU_VIELE_VERSUCHE_SEITE = registrierungsSeite("Zu viele Versuche von dieser Verbindung. Bitte später erneut versuchen.");
const ZU_VIELE_PIN_VERSUCHE_SEITE = `<!doctype html><html lang="de"><head><meta charset="utf-8">` +
  `<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">` +
  `<title>Nestor</title></head><body><main style="font:16px system-ui;max-width:420px;margin:48px auto;padding:0 16px">` +
  `<p>Zu viele Versuche von dieser Verbindung. Bitte in ein paar Minuten erneut versuchen.</p></main></body></html>`;

async function handleAnmelden(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (request.method === "GET") {
    if (new URL(request.url).searchParams.has("alt")) {
      const fehler = new URL(request.url).searchParams.has("falsch");
      return new Response(ANMELDEN_SEITE(fehler), { headers: { "content-type": "text/html; charset=utf-8" } });
    }
    return new Response(registrierungsSeite(), { headers: { "content-type": "text/html; charset=utf-8" } });
  }
  // IP-Ratenbegrenzung (Ticket #63): max. 8 Anfragen je 10 min, unabhängig davon, ob Registrierung oder
  // Passwort-Login – schützt vor Mail-Flut und vor massenhaftem Passwort-Raten gleichermaßen.
  if (!(await ratenOk(env, request, "anmelden", 8, 10 * 60_000))) {
    return new Response(ZU_VIELE_VERSUCHE_SEITE, { status: 429, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  const form = await request.formData();
  const anmeldung = normalisiereAnmeldung(form);
  if (anmeldung) {
    // Gleichlautende Antwort unabhängig vom Registrierungsstand (Ticket #63, Befund 2): ob die Mailadresse
    // schon bekannt ist oder nicht, der Besucher sieht in jedem Fall dieselbe "Code ist unterwegs"-Seite. Nur
    // innerhalb der bestehenden 60s-Kühlzeit für dieselbe Adresse wird kein zweiter Code verschickt (schützt
    // Gmail vor Mail-Flut), ohne das über die Antwort zu verraten.
    const vorhanden = await interessentLesen(env, anmeldung.email);
    const kuehlzeitAktiv = !!vorhanden && Date.now() - vorhanden.letzter_pin_at < 60_000;
    if (!kuehlzeitAktiv) {
      const pin = pinErzeugen();
      await interessentSpeichern(env, anmeldung, pin);
      try {
        await pinMailSenden(env, anmeldung, pin);
      } catch {
        // Zustellfehler sind kein Enumerationskanal (betrifft neue wie bekannte Adressen gleich), aber ein
        // eigener Hinweis ist hier hilfreicher als eine stille Erfolgsseite.
        return new Response(registrierungsSeite("Der Code konnte gerade nicht verschickt werden. Bitte versuche es später erneut."),
          { status: 502, headers: { "content-type": "text/html; charset=utf-8" } });
      }
      melden(ctx, env, `🟣 Nestor: Zugang angefordert\n${anmeldung.name}\n${anmeldung.email}\nKennt dich über: ${anmeldung.herkunft}`);
    }
    return new Response(pinSeite(anmeldung.email), { headers: { "content-type": "text/html; charset=utf-8" } });
  }
  if (!form.has("passwort")) {
    return new Response(registrierungsSeite("Bitte fülle alle drei Felder vollständig aus."),
      { status: 400, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  const passwort = String(form.get("passwort") ?? "");
  const kunde = await kundeFuerPasswort(passwort, kundenliste(env));
  if (!kunde) {
    return Response.redirect(new URL("/anmelden?falsch=1", request.url).toString(), 303);
  }
  const cookieWert = await signiereMitAblauf("kunde", kunde, env.COOKIE_GEHEIMNIS, Date.now(), DREISSIG_TAGE * 1000);
  const antwort = Response.redirect(new URL("/", request.url).toString(), 303);
  return setzeCookie(antwort, KUNDE_COOKIE, cookieWert, DREISSIG_TAGE);
}

async function handlePin(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  // IP-Ratenbegrenzung (Ticket #63): max. 20 Versuche je 10 min – großzügiger als /anmelden, weil mehrere
  // echte Nutzer hinter derselben IP (Büro-NAT) PINs eintippen können, aber eng genug gegen Rateversuche über
  // viele Mailadressen hinweg (die bestehende Sperre in pilotzugang.ts ist nur pro Adresse).
  if (!(await ratenOk(env, request, "pin", 20, 10 * 60_000))) {
    return new Response(ZU_VIELE_PIN_VERSUCHE_SEITE, { status: 429, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  const form = await request.formData();
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  const pin = String(form.get("pin") ?? "").trim();
  const ergebnis = await pinPruefen(env, email, pin);
  if (ergebnis === "wartet") {
    return new Response(pinSeite(email, "Deine Anfrage wartet noch auf Freigabe."),
      { status: 403, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  if (ergebnis !== "ok") {
    return new Response(pinSeite(email, "Der Code ist falsch oder abgelaufen."),
      { status: 400, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  melden(ctx, env, `✅ Nestor: Zugang bestätigt\n${email}`);
  const antwort = Response.redirect(new URL("/", request.url).toString(), 303);
  const cookieWert = await signiereMitAblauf("kunde", email, env.COOKIE_GEHEIMNIS, Date.now(), DREISSIG_TAGE * 1000);
  return setzeCookie(antwort, KUNDE_COOKIE, cookieWert, DREISSIG_TAGE);
}

async function maxMeetingsFuer(env: Env, kunde: string): Promise<number> {
  const legacy = kundenliste(env)[kunde]?.max_meetings;
  if (legacy) return legacy;
  const row = await interessentLesen(env, kunde);
  // gesperrt/wartet -> 0 statt 1 (Ticket #63, U2): „gesperrt“ darf kein neues Meeting mehr erlauben.
  return row?.status === "aktiv" ? row.max_meetings : 0;
}

async function handleInteressenten(request: Request, env: Env): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) return new Response("Nicht erlaubt.", { status: 403 });
  const rows = await interessentenListe(env);
  return Response.json(rows.map(({ pin_hash: _hash, pin_bis: _bis, pin_versuche: _versuche, ...sichtbar }) => sichtbar));
}

/** Lädt Dateien zur Datenspende hoch (vom Coach selbst aufgerufen, siehe coach/ablage_r2.py). */
async function handleSpende(request: Request, env: Env, name: string, ctx: ExecutionContext): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) {
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
  melden(ctx, env, `📦 Nestor: Datenspende / Feedback gespeichert\nPaket: ${name}\nDateien: ${anzahl}`);
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
async function handleMeetingStart(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const { meetingId, kunde } = (await request.json()) as { meetingId?: string; kunde?: string };
  if (!meetingId || !kunde) return new Response("meetingId/kunde fehlen.", { status: 400 });
  const maxMeetings = await maxMeetingsFuer(env, kunde);
  const zaehler = env.ZAEHLER.get(env.ZAEHLER.idFromName(kunde));
  const antwort = await zaehler.fetch("https://zaehler/pruefen", {
    method: "POST",
    body: JSON.stringify({ meetingId, maxMeetings }),
  });
  const ergebnis = await antwort.json() as { erlaubt?: boolean };
  if (ergebnis.erlaubt) melden(ctx, env, `🎙️ Nestor: Meeting gestartet\nZugang: ${kunde}\nMeeting: ${meetingKurz(meetingId)}`);
  return Response.json(ergebnis);
}

/** Meeting-Ende melden (Ticket #12): vom Coach aufgerufen (`coach/api_abschluss.py`, `/api/abschluss/fertig`,
 * als Hintergrundaufgabe erst NACH der Antwort an den Browser). Gibt den Platz im KundenZaehler sofort frei und
 * stoppt den Container – `stop()` (SIGTERM; Doku: developers.cloudflare.com/containers/container-class/) reicht
 * für ein regulär beendetes Meeting, `destroy()` (SIGKILL) wäre nur für ein erzwungenes Ende nötig. */
async function handleMeetingEnde(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) {
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
  melden(ctx, env, `🏁 Nestor: Meeting beendet\nZugang: ${kunde || "unbekannt"}\nMeeting: ${meetingKurz(meetingId)}`);
  return Response.json({ ok: true });
}

/** Mintet das kurzlebige Kopplungstoken für den QR-Code (Ticket #63, U1): vom Coach aufgerufen
 * (`coach/server.py`, `/api/kopplung`, über das vorhandene `api_abschluss.worker_melden`-Muster), mit dem
 * schon bekannten Worker-Geheimnis. Der Coach selbst kennt `COOKIE_GEHEIMNIS` nicht und kann das Token darum
 * nicht selbst signieren – das macht ausschließlich der Worker. */
async function handleKopplungstoken(request: Request, env: Env): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const { meetingId, kunde } = (await request.json()) as { meetingId?: string; kunde?: string };
  if (!meetingId) return new Response("meetingId fehlt.", { status: 400 });
  const token = await kopplungstokenSigniere({ meetingId, kunde: kunde ?? "" }, env.COOKIE_GEHEIMNIS);
  return Response.json({ token });
}

/** Löst die für `getContainer` maßgebliche Meeting-Identität auf (Ticket #63, Befund 1 / U1): NIE aus dem
 * rohen `?meeting=`-Parameter oder einem unsignierten Cookie, sondern ausschließlich aus einem gültigen,
 * unabgelaufenen Meeting-Cookie oder einem gültigen, unabgelaufenen Kopplungstoken aus der QR-URL. Ohne beides
 * gibt es nur dann eine neue Meeting-ID, wenn ein eingeloggter Kunde sie anfordert (Desktop-Login) – ein rein
 * anonymer Aufruf bekommt gar keine. */
async function meetingAufloesen(
  request: Request, url: URL, env: Env, kunde: string | null,
): Promise<{ ticket: MeetingTicket | null; neuGemintet: boolean }> {
  const ausCookie = await meetingCookiePruefen(cookieLesen(request.headers.get("Cookie"), MEETING_COOKIE), env.COOKIE_GEHEIMNIS);
  if (ausCookie) return { ticket: ausCookie, neuGemintet: false };

  const kopplungsParam = url.searchParams.get("meeting");
  if (kopplungsParam) {
    const ausToken = await kopplungstokenPruefen(kopplungsParam, env.COOKIE_GEHEIMNIS);
    if (ausToken) return { ticket: ausToken, neuGemintet: true }; // neues Cookie setzen, Token nicht erneut nötig
    return { ticket: null, neuGemintet: false }; // fremd/abgelaufen – NIE als meetingId übernehmen
  }

  if (kunde) return { ticket: { meetingId: crypto.randomUUID(), kunde }, neuGemintet: true };
  return { ticket: null, neuGemintet: false };
}

/** Die eigentliche Zustellung, vor den Sicherheitsheadern (einzige Aufrufstelle unten im Export). */
async function kern(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  const pfad = url.pathname;

  if (pfad.startsWith("/intern/spende/")) {
    return handleSpende(request, env, decodeURIComponent(pfad.slice("/intern/spende/".length)), ctx);
  }
  if (pfad === "/intern/meeting-start") {
    return handleMeetingStart(request, env, ctx);
  }
  if (pfad === "/intern/meeting-ende") {
    return handleMeetingEnde(request, env, ctx);
  }
  if (pfad === "/intern/kopplungstoken") {
    return handleKopplungstoken(request, env);
  }
  if (pfad === "/anmelden") {
    return handleAnmelden(request, env, ctx);
  }
  if (pfad === "/pin") {
    return handlePin(request, env, ctx);
  }
  if (pfad === "/intern/interessenten") {
    return handleInteressenten(request, env);
  }
  if (pfad.startsWith("/teaser/")) {
    return env.ASSETS.fetch(request); // Bilder der Anmeldeseite (cloudflare/oeffentlich/teaser/)
  }

  let kunde = await pruefeMitAblauf<string>("kunde", cookieLesen(request.headers.get("Cookie"), KUNDE_COOKIE), env.COOKIE_GEHEIMNIS, Date.now());
  if (kunde && !(await kundeAktiv(env, kunde, statusCache))) kunde = null; // gesperrt/wartet wirkt sofort (≤5 min Cache)

  // Meeting-Zuordnung NUR aus einer gültigen, unabgelaufenen Signatur (Cookie oder Kopplungstoken) – niemals
  // aus einem rohen `?meeting=`-Wert oder unsigniertem Cookie (Ticket #63, Befund 1). Ohne gültige Signatur
  // und ohne Login gibt es gar keine Meeting-ID und damit auch kein `getContainer` weiter unten.
  const { ticket, neuGemintet } = await meetingAufloesen(request, url, env, kunde);
  const lmcKopplungVorhanden = !!cookieLesen(request.headers.get("Cookie"), "lmc_kopplung");
  const gekoppelt = !!ticket && !kunde && lmcKopplungVorhanden;

  if (!kunde && !gekoppelt && !offenOhneAnmeldung(pfad)) {
    return Response.redirect(new URL("/anmelden", request.url).toString(), 303);
  }
  if (!ticket) {
    // offenOhneAnmeldung (z. B. /handy ohne noch gültiges Token/Cookie) – bewusst KEIN Container für anonyme
    // Aufrufe (Ticket #63, Mindestanforderung aus U4): derselbe Hinweis wie zuvor, nur ohne je `getContainer`
    // zu erreichen.
    return new Response("Kein Meeting zugeordnet – bitte den QR-Code am Dashboard scannen.", { status: 400 });
  }

  const kopfzeilen = new Headers(request.headers);
  kopfzeilen.set("X-Nestor-Geheimnis", env.WORKER_GEHEIMNIS);
  kopfzeilen.set("X-Nestor-Meeting", ticket.meetingId);
  kopfzeilen.delete("X-Nestor-Kunde");
  if (kunde) kopfzeilen.set("X-Nestor-Kunde", kunde);
  const weitergeleitet = new Request(request, { headers: kopfzeilen });

  const container = getContainer(env.NESTOR, ticket.meetingId);
  let antwort = await containerAufrufenOderAusweichen(
    () => container.fetch(weitergeleitet), (text) => melden(ctx, env, text), pfad,
  );
  if (neuGemintet) {
    antwort = setzeCookie(antwort, MEETING_COOKIE, await meetingCookieSigniere(ticket, env.COOKIE_GEHEIMNIS), DREISSIG_TAGE);
  }
  return antwort;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return mitSicherheitsheadern(await kern(request, env, ctx));
  },
} satisfies ExportedHandler<Env>;
