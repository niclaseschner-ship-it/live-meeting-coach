/**
 * Nestor-Worker (Ticket #5): prüft das Kundenpasswort, wählt je Meeting einen eigenen Container und reicht
 * die Datenspende nach R2 weiter. Ausgerollt wird in diesem Ticket nichts – nur gebaut und mit
 * `wrangler deploy --dry-run` geprüft (Workers-Paid-Plan fehlt noch).
 *
 * Zugehörige Doku: ../docs/lastenheft.md (Abschnitte 2, 5, 6) und README.md in diesem Ordner.
 */

import { Container, getContainer } from "@cloudflare/containers";
import { cookieLesen, pruefeMitAblauf, signiereMitAblauf } from "./anmeldung";
import { kopplungstokenPruefen, kopplungstokenSigniere, meetingCookiePruefen, meetingCookieSigniere, type MeetingTicket } from "./meeting";
import {
  interessentLesen, interessentenListe, interessentSpeichern, kundeAktiv, normalisiereAnmeldung, pinErzeugen,
  pinMailSenden, pinPruefen, pinSeite, registrierungsSeite, statusCacheErzeugen, testzugangMailPasst,
  testzugangPinPruefen,
} from "./pilotzugang";
import { IpZaehler } from "./ratenbegrenzung";
import { containerAufrufenOderAusweichen, mitSicherheitsheadern, pauseSeite, pausiert, workerGeheimnisPasst } from "./sicherheit";
import { meetingKurz, telegramMelden } from "./telegram";
import { meetingBeenden, mitVariantenwahl, varianteText } from "./variantenwahl";
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
  COOKIE_GEHEIMNIS: string; // Secret – signiert das Kunden-Cookie
  TESTZUGANG?: string; // Secret/Var – NUR Dev/Staging (Ticket #75): Mail+PIN-Hash für die Test-Pipeline, in
  // prod nie gesetzt UND über WORKER_NAME hart blockiert, siehe pilotzugang.ts
  WORKER_NAME?: string; // Var – muss in wrangler.jsonc exakt den Worker-Namen tragen (prod "nestor")
  WORKER_GEHEIMNIS: string; // Secret – beweist dem Coach, dass eine Anfrage vom Worker kommt
  OPENAI_API_KEY: string; // Secret – Niclas' Schlüssel, eigenes OpenAI-Projekt mit Ausgabenlimit
  MISTRAL_API_KEY?: string; // Secret – Nestor Basis (Ticket #13); ohne ihn ist Basis auf der Startseite nicht wählbar
  GMAIL_SMTP_PASSWORT: string; // Secret – vorhandenes Gmail-App-Passwort für Login-PINs
  PIN_GEHEIMNIS: string; // Secret – hasht PINs vor der Ablage
  MAIL_VON: string; // Secret/Var – verifizierter Absender, z. B. Nestor <login@example.de>
  AUTO_FREIGABE?: string; // "0" = neue Interessenten warten auf manuelle Freigabe, sonst sofort aktiv
  NESTOR_PAUSE?: string; // Ticket #64, Notschalter: "1" = keine neuen Meetings, laufende bleiben unberührt
  TELEGRAM_BOT_TOKEN?: string; // Secret – bestehender privater Assistenten-Bot
  TELEGRAM_CHAT_ID?: string; // Secret – Niclas' privater Chat
  WORKER_URL: string; // Var – eigene Adresse, für den Rückruf aus dem Container (Datenspende); nach dem
  // ersten Deploy in wrangler.jsonc eintragen, siehe README.md
  LOKAL_COACH_URL?: string; // NUR Test-Pipeline (#61, `wrangler dev`): lokaler uvicorn statt Container – in prod nie gesetzt
  GIT_SHA?: string; // Var – von deploy/deploy.sh per `--var GIT_SHA:<sha> --keep-vars` gesetzt (Ticket #65)
  BUILD_ZEIT?: string; // Var – dito, ISO-8601 UTC; beide ohne Deploy über deploy.sh leer (lokal, `wrangler dev`)
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
      // Keine Vorgabe-Stufe (Ticket #60): die Variante kommt nur aus der bestätigten Wahl (variantenwahl.ts).
      // Premium nutzt den serverseitigen Projektschlüssel, Basis den Mistral-Schlüssel.
      OPENAI_API_KEY: env.OPENAI_API_KEY ?? "",
      LMC_MISTRAL_SCHLUESSEL: env.MISTRAL_API_KEY ?? "",
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

  /** Ticket #60: nach „Fertig“ beendet – das Meeting-Cookie (30 Tage) führt nicht mehr in einen Container. Nur
   * per RPC aus `handleMeetingEnde` erreichbar, nicht über eine URL. */
  async meetingBeenden(): Promise<void> {
    await meetingBeenden(this.wahlSpeicher);
  }
}

/**
 * Testnaht der lokalen Klick-E2E (Ticket #61): Ist `LOKAL_COACH_URL` gesetzt (nur `wrangler dev` der Pipeline,
 * nie in wrangler.jsonc oder als Secret), geht die Anfrage statt an den Meeting-Container an den lokalen Coach.
 * Pfad, Query, Methode, Kopfzeilen und Körper bleiben gleich; die ursprüngliche Adresse geht als
 * `X-Forwarded-Host` mit, weil `fetch` den Host aus der Ziel-URL nimmt. Ohne die Variable: `null`.
 */
export function lokalerCoach(env: Pick<Env, "LOKAL_COACH_URL">): { fetch(request: Request): Promise<Response> } | null {
  const ziel = env.LOKAL_COACH_URL;
  if (!ziel) return null;
  return {
    fetch(request: Request): Promise<Response> {
      const alt = new URL(request.url);
      const kopf = new Headers(request.headers);
      kopf.set("X-Forwarded-Host", alt.host);
      return fetch(new Request(new URL(alt.pathname + alt.search, ziel).toString(), new Request(request, { headers: kopf })));
    },
  };
}

const KUNDE_COOKIE = "nestor_kunde";
const MEETING_COOKIE = "nestor_meeting";
const DREISSIG_TAGE = 30 * 24 * 60 * 60;

function setzeCookie(antwort: Response, name: string, wert: string, maxAge: number): Response {
  const kopie = new Response(antwort.body, antwort);
  kopie.headers.append(
    "Set-Cookie",
    `${name}=${encodeURIComponent(wert)}; Max-Age=${maxAge}; Path=/; HttpOnly; Secure; SameSite=Lax`,
  );
  return kopie;
}

// Ticket #75 (Entscheidung Niclas 10.10.2026): der Passwortweg samt Teaser-Login-Seite ist entfernt – einziger
// Zugang ist jetzt der Mail-PIN-Dialog aus pilotzugang.ts (registrierungsSeite()/pinSeite()).

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
    return new Response(registrierungsSeite(), { headers: { "content-type": "text/html; charset=utf-8" } });
  }
  // IP-Ratenbegrenzung (Ticket #63): max. 8 Anfragen je 10 min.
  if (!(await ratenOk(env, request, "anmelden", 8, 10 * 60_000))) {
    return new Response(ZU_VIELE_VERSUCHE_SEITE, { status: 429, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  const form = await request.formData();
  const anmeldung = normalisiereAnmeldung(form);
  if (!anmeldung) {
    // Ticket #75: ein Passwortfeld allein (oder sonst unvollständige Angaben) führt hier nie mehr zum Login –
    // es gibt nur noch den Mail-PIN-Weg.
    return new Response(registrierungsSeite("Bitte fülle alle drei Felder vollständig aus."),
      { status: 400, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  // Ticket #75: Testzugang (nur Dev/Staging) – zeigt dieselbe "Code ist unterwegs"-Seite, ohne eine echte Mail
  // zu verschicken oder einen R2-Datensatz anzulegen; `/pin` beantwortet ihn über testzugangPinPruefen.
  if (testzugangMailPasst(env, anmeldung.email)) {
    return new Response(pinSeite(anmeldung.email), { headers: { "content-type": "text/html; charset=utf-8" } });
  }
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
  // Ticket #75: Testzugang zuerst fragen (null = nicht zuständig, dann normal weiterprüfen).
  const ergebnis = (await testzugangPinPruefen(env, email, pin)) ?? (await pinPruefen(env, email, pin));
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

/** Ticket #75: ein Zugang führt höchstens EIN Meeting gleichzeitig – fest, kein Feld mehr je Kunde. */
async function maxMeetingsFuer(env: Env, kunde: string): Promise<number> {
  if (testzugangMailPasst(env, kunde)) return 1; // Testzugang legt nie einen R2-Datensatz an
  const row = await interessentLesen(env, kunde);
  // gesperrt/wartet -> 0 statt 1 (Ticket #63, U2): „gesperrt“ darf kein neues Meeting mehr erlauben.
  return row?.status === "aktiv" ? 1 : 0;
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
  const { meetingId, kunde, stufe } = (await request.json()) as {
    meetingId?: string; kunde?: string; stufe?: string;
  };
  if (!meetingId || !kunde) return new Response("meetingId/kunde fehlen.", { status: 400 });
  const maxMeetings = await maxMeetingsFuer(env, kunde);
  const zaehler = env.ZAEHLER.get(env.ZAEHLER.idFromName(kunde));
  const antwort = await zaehler.fetch("https://zaehler/pruefen", {
    method: "POST",
    body: JSON.stringify({ meetingId, maxMeetings }),
  });
  const ergebnis = await antwort.json() as { erlaubt?: boolean };
  if (ergebnis.erlaubt) {
    melden(ctx, env, `🎙️ Nestor: Meeting gestartet\nZugang: ${kunde}\nVariante: ${varianteText(stufe)}`
      + `\nMeeting: ${meetingKurz(meetingId)}`);
  }
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
  // kostenUsd (Ticket #64): coach/api_abschluss.py liefert die Kosten des beendeten Meetings mit – Grundlage
  // für den Tagesdeckel je Kunde (zaehler-logik.ts, tageskostenBuchen).
  const { meetingId, kunde, kostenUsd } = (await request.json()) as {
    meetingId?: string; kunde?: string; kostenUsd?: number;
  };
  if (!meetingId) return new Response("meetingId fehlt.", { status: 400 });
  if (kunde) {
    const zaehler = env.ZAEHLER.get(env.ZAEHLER.idFromName(kunde));
    await zaehler.fetch("https://zaehler/beenden", { method: "POST", body: JSON.stringify({ meetingId, kostenUsd }) });
  }
  const container = getContainer(env.NESTOR, meetingId);
  // Ticket #60: erst als beendet markieren – ein altes Handy-Cookie startet danach keinen frischen Container mehr
  try {
    await container.meetingBeenden();
  } catch {
    melden(ctx, env, `⚠️ Nestor: Meeting ${meetingKurz(meetingId)} konnte nicht als beendet markiert werden`);
  }
  try {
    await container.stop();
  } catch {
    // Container war evtl. schon gestoppt oder eingeschlafen – kein Fehler für den Aufrufer, der Platz im
    // Zähler ist zu diesem Zeitpunkt ohnehin schon frei.
  }
  melden(ctx, env, `🏁 Nestor: Meeting beendet\nZugang: ${kunde || "unbekannt"}\nMeeting: ${meetingKurz(meetingId)}`);
  return Response.json({ ok: true });
}

/** Meeting-Kostendeckel erreicht (Ticket #64): vom Coach gemeldet, sobald die zentrale Sperre
 * (coach/pipeline.py, `_kosten_pruefen`) den KI-Client für den Rest des Meetings schließt. Reine
 * Telegram-Weiterleitung über den vorhandenen Rückkanal (api_abschluss.worker_melden) – kein Containerzugriff,
 * keine Zähler-Logik hier (die steht in zaehler-logik.ts / handleMeetingEnde). */
async function handleKostenDeckel(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if (!workerGeheimnisPasst(request, env.WORKER_GEHEIMNIS)) {
    return new Response("Nicht erlaubt.", { status: 403 });
  }
  if (request.method !== "POST") return new Response("Nur POST.", { status: 405 });
  const { meetingId, kunde, stufe, usd } = (await request.json()) as {
    meetingId?: string; kunde?: string; stufe?: string; usd?: number;
  };
  melden(ctx, env, `💸 Nestor: Kostendeckel erreicht\nZugang: ${kunde || "unbekannt"}\nVariante: ${stufe || "?"} `
    + `(${usd ?? "?"} $)\nMeeting: ${meetingKurz(meetingId ?? "")}`);
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
): Promise<{ ticket: MeetingTicket | null; neuGemintet: boolean; neuesMeeting: boolean }> {
  const ausCookie = await meetingCookiePruefen(cookieLesen(request.headers.get("Cookie"), MEETING_COOKIE), env.COOKIE_GEHEIMNIS);
  if (ausCookie) return { ticket: ausCookie, neuGemintet: false, neuesMeeting: false };

  const kopplungsParam = url.searchParams.get("meeting");
  if (kopplungsParam) {
    const ausToken = await kopplungstokenPruefen(kopplungsParam, env.COOKIE_GEHEIMNIS);
    // Das Handy koppelt an ein Meeting, das am Laptop schon begonnen hat – kein neues (Ticket #64: NESTOR_PAUSE
    // betrifft das nicht).
    if (ausToken) return { ticket: ausToken, neuGemintet: true, neuesMeeting: false };
    return { ticket: null, neuGemintet: false, neuesMeeting: false }; // fremd/abgelaufen – NIE als meetingId übernehmen
  }

  // Einzige Stelle, die wirklich ein brandneues Meeting mintet (Ticket #64: hier greift NESTOR_PAUSE).
  if (kunde) return { ticket: { meetingId: crypto.randomUUID(), kunde }, neuGemintet: true, neuesMeeting: true };
  return { ticket: null, neuGemintet: false, neuesMeeting: false };
}

/** Die eigentliche Zustellung, vor den Sicherheitsheadern (einzige Aufrufstelle unten im Export). */
async function kern(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  const pfad = url.pathname;

  // Ticket #65: Smoke-Test nach einem Deploy – ohne Container, ohne Login, ohne Kosten. Zeigt den SHA/die
  // Bauzeit, mit denen DIESER WORKER deployt wurde (`--var GIT_SHA:… --var BUILD_ZEIT:… --keep-vars`,
  // deploy/deploy.sh). GET /api/version auf dem Container selbst prüft zusätzlich, "falls erreichbar", ob der
  // Container denselben Stand trägt (coach/server.py).
  if (pfad === "/version") {
    return Response.json({ git_sha: env.GIT_SHA ?? null, gebaut_am: env.BUILD_ZEIT ?? null });
  }

  if (pfad.startsWith("/intern/spende/")) {
    return handleSpende(request, env, decodeURIComponent(pfad.slice("/intern/spende/".length)), ctx);
  }
  if (pfad === "/intern/meeting-start") {
    return handleMeetingStart(request, env, ctx);
  }
  if (pfad === "/intern/meeting-ende") {
    return handleMeetingEnde(request, env, ctx);
  }
  if (pfad === "/intern/kosten-deckel") {
    return handleKostenDeckel(request, env, ctx);
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
  const { ticket, neuGemintet, neuesMeeting } = await meetingAufloesen(request, url, env, kunde);
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
  // Notschalter (Ticket #64): genau hier, wo ein brandneues Meeting entstehen würde – ein Handy, das sich an
  // ein schon laufendes Meeting koppelt, oder ein Cookie für ein laufendes Meeting kommen nie hierher
  // (neuesMeeting ist dann false), laufende Meetings bleiben also unberührt.
  if (neuesMeeting && pausiert(env)) {
    return pauseSeite();
  }

  const kopfzeilen = new Headers(request.headers);
  kopfzeilen.set("X-Nestor-Geheimnis", env.WORKER_GEHEIMNIS);
  kopfzeilen.set("X-Nestor-Meeting", ticket.meetingId);
  kopfzeilen.delete("X-Nestor-Kunde");
  if (kunde) kopfzeilen.set("X-Nestor-Kunde", kunde);
  const weitergeleitet = new Request(request, { headers: kopfzeilen });

  const container = lokalerCoach(env) ?? getContainer(env.NESTOR, ticket.meetingId);
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
