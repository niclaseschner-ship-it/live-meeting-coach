import { sha256Hex } from "./anmeldung";

export interface PilotEnv {
  SPENDEN: R2Bucket;
  PIN_GEHEIMNIS: string;
  GMAIL_SMTP_PASSWORT: string;
  MAIL_VON: string;
  AUTO_FREIGABE?: string;
  TESTZUGANG?: string; // Secret/Var – NUR Dev/Staging (Ticket #75), siehe testzugangLesen() unten
  WORKER_NAME?: string; // Var – muss in wrangler.jsonc exakt den Worker-Namen tragen; "nestor" blockiert TESTZUGANG hart
}

export interface Anmeldung {
  name: string;
  email: string;
  herkunft: string;
}

export interface Interessent extends Anmeldung {
  status: "aktiv" | "wartet" | "gesperrt";
  erstellt_at: number;
  letzter_pin_at: number;
  letzter_login_at?: number;
  pin_hash: string;
  pin_bis: number;
  pin_versuche: number;
}

async function schluessel(email: string): Promise<string> {
  return `pilot/interessenten/${await sha256Hex(email)}.json`;
}

export async function interessentLesen(env: PilotEnv, email: string): Promise<Interessent | null> {
  const objekt = await env.SPENDEN.get(await schluessel(email));
  return objekt ? objekt.json<Interessent>() : null;
}

async function interessentSchreiben(env: PilotEnv, eintrag: Interessent): Promise<void> {
  await env.SPENDEN.put(await schluessel(eintrag.email), JSON.stringify(eintrag), {
    httpMetadata: { contentType: "application/json" },
  });
}

export function normalisiereAnmeldung(form: FormData): Anmeldung | null {
  const name = String(form.get("name") ?? "").trim().replace(/\s+/g, " ");
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  const herkunft = String(form.get("herkunft") ?? "").trim().replace(/\s+/g, " ");
  if (form.get("datenschutz") !== "ja") return null;
  if (name.length < 2 || name.length > 100 || herkunft.length < 2 || herkunft.length > 300) return null;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) return null;
  return { name, email, herkunft };
}

export function pinErzeugen(): string {
  const bytes = new Uint32Array(1);
  crypto.getRandomValues(bytes);
  return String(100000 + (bytes[0] % 900000));
}

export async function pinHash(email: string, pin: string, geheimnis: string): Promise<string> {
  return sha256Hex(`${geheimnis}:${email}:${pin}`);
}

export async function interessentSpeichern(env: PilotEnv, a: Anmeldung, pin: string, jetzt = Date.now()): Promise<void> {
  const alt = await interessentLesen(env, a.email);
  const status = alt?.status ?? (env.AUTO_FREIGABE === "0" ? "wartet" : "aktiv");
  const hash = await pinHash(a.email, pin, env.PIN_GEHEIMNIS);
  await interessentSchreiben(env, {
    ...a, status, erstellt_at: alt?.erstellt_at ?? jetzt, letzter_pin_at: jetzt,
    letzter_login_at: alt?.letzter_login_at, pin_hash: hash, pin_bis: jetzt + 10 * 60_000,
    pin_versuche: 0,
  });
}

export async function pinPruefen(env: PilotEnv, email: string, pin: string, jetzt = Date.now()): Promise<"ok" | "wartet" | "falsch"> {
  const row = await interessentLesen(env, email);
  if (!row || row.pin_bis < jetzt || row.pin_versuche >= 5) return "falsch";
  const hash = await pinHash(email, pin, env.PIN_GEHEIMNIS);
  if (hash !== row.pin_hash) {
    row.pin_versuche++;
    await interessentSchreiben(env, row);
    return "falsch";
  }
  if (row.status !== "aktiv") return "wartet";
  row.letzter_login_at = jetzt;
  row.pin_hash = "";
  row.pin_bis = 0;
  row.pin_versuche = 0;
  await interessentSchreiben(env, row);
  return "ok";
}

/**
 * Ticket #63 (Befund 3, review/r3_sicherheit.md; U2, review/r2_architektur.md Abschnitt 6.A): „gesperrt“ muss
 * sofort wirken, nicht erst wenn das (jetzt ablaufende) Kunden-Cookie nach 30 Tagen neu ausgehandelt wird. Statt
 * bei jeder Anfrage R2 zu lesen, hält ein kurzlebiger Cache (≤5 min) den Status vor – ein Sperren wirkt so
 * binnen höchstens fünf Minuten, ohne jede Anfrage zu verlangsamen. Der Cache wird vom Aufrufer gehalten (ein
 * Objekt je Worker-Isolate in index.ts), damit sich die Funktion hier ohne Workers-Laufzeit testen lässt.
 */
export interface StatusCache {
  daten: Map<string, { aktiv: boolean; bis: number }>;
}

export function statusCacheErzeugen(): StatusCache {
  return { daten: new Map() };
}

const STATUS_CACHE_MS = 5 * 60 * 1000;

/** `true`, solange der Kunde kein Interessenten-Datensatz mit Status "gesperrt"/"wartet" hat. Ein Zugang ohne
 * jeden Datensatz (z. B. der Testzugang unten, Ticket #75 – er legt bewusst nie einen R2-Eintrag an) bleibt
 * damit vertraut, genau wie früher die Legacy-Passwortkunden. */
export async function kundeAktiv(env: PilotEnv, kunde: string, cache: StatusCache, jetzt = Date.now()): Promise<boolean> {
  // Testzugang (nur Dev/Staging) ist immer aktiv – ein Altdatensatz aus einem Lauf ohne TESTZUGANG sperrt ihn nicht
  if (testzugangMailPasst(env, kunde)) return true;
  const treffer = cache.daten.get(kunde);
  if (treffer && treffer.bis > jetzt) return treffer.aktiv;
  const row = await interessentLesen(env, kunde);
  const aktiv = row ? row.status === "aktiv" : true;
  cache.daten.set(kunde, { aktiv, bis: jetzt + STATUS_CACHE_MS });
  return aktiv;
}

/**
 * Testzugang für die Test-Pipeline (Ticket #75, Entscheidung Niclas 10.10.2026): Mail + fester, gehashter PIN
 * aus dem Secret/Var TESTZUGANG (JSON `{"mail":"...","pinHash":"<sha256 hex des PIN>"}`). Legt NIE einen
 * R2-Datensatz an und verschickt NIE eine Mail – `handleAnmelden`/`handlePin` (index.ts) fragen ihn vor dem
 * echten Pilotzugang ab. In PROD darf er nie wirken: zusätzlich zur Abwesenheit in `wrangler.jsonc` blockiert
 * `WORKER_NAME === "nestor"` ihn hart im Code, auch falls das Secret versehentlich dort gesetzt wäre.
 */
export interface Testzugang {
  mail: string;
  pinHash: string;
}

export function testzugangLesen(env: Pick<PilotEnv, "TESTZUGANG">): Testzugang | null {
  if (!env.TESTZUGANG) return null;
  try {
    const t = JSON.parse(env.TESTZUGANG) as Partial<Testzugang>;
    if (typeof t.mail === "string" && typeof t.pinHash === "string") {
      return { mail: t.mail.toLowerCase(), pinHash: t.pinHash.toLowerCase() };
    }
  } catch { /* kaputtes Secret – wie "nicht gesetzt" behandeln */ }
  return null;
}

export function testzugangErlaubt(workerName: string | undefined): boolean {
  // Geschlossen im Zweifel: ohne ausdrücklichen Nicht-prod-Namen kein Testzugang
  return !!workerName && workerName !== "nestor";
}

/** `true`, wenn `email` der konfigurierte Testzugang ist und er in dieser Umgebung wirken darf. */
export function testzugangMailPasst(env: Pick<PilotEnv, "TESTZUGANG" | "WORKER_NAME">, email: string): boolean {
  const t = testzugangLesen(env);
  if (!t) return false;
  if (!testzugangErlaubt(env.WORKER_NAME)) {
    console.error("Ticket #75: TESTZUGANG ist gesetzt, aber WORKER_NAME ist \"nestor\" (prod) – wird ignoriert.");
    return false;
  }
  return email.toLowerCase() === t.mail;
}

/** null = kein Testzugang zuständig (normaler Mail-PIN-Fluss prüft weiter), sonst "ok"/"falsch". */
export async function testzugangPinPruefen(
  env: Pick<PilotEnv, "TESTZUGANG" | "WORKER_NAME">, email: string, pin: string,
): Promise<"ok" | "falsch" | null> {
  if (!testzugangMailPasst(env, email)) return null;
  const t = testzugangLesen(env)!;
  return (await sha256Hex(pin)) === t.pinHash ? "ok" : "falsch";
}

export async function interessentenListe(env: PilotEnv): Promise<Interessent[]> {
  const aus: Interessent[] = [];
  let cursor: string | undefined;
  do {
    const seite = await env.SPENDEN.list({ prefix: "pilot/interessenten/", cursor });
    for (const objekt of seite.objects) {
      const wert = await env.SPENDEN.get(objekt.key);
      if (wert) aus.push(await wert.json<Interessent>());
    }
    cursor = seite.truncated ? seite.cursor : undefined;
  } while (cursor);
  return aus.sort((a, b) => b.erstellt_at - a.erstellt_at);
}

export async function pinMailSenden(env: PilotEnv, a: Anmeldung, pin: string): Promise<void> {
  const { connect } = await import("cloudflare:sockets");
  const benutzer = env.MAIL_VON.trim();
  const sauber = (s: string) => s.replace(/[\r\n]/g, " ");
  const inhalt = [
    `From: Nestor <${benutzer}>`, `To: ${sauber(a.email)}`, `Subject: ${pin} - dein Nestor-Zugang`,
    "MIME-Version: 1.0", "Content-Type: text/plain; charset=UTF-8", "",
    `Hallo ${sauber(a.name)},`, "", `dein Anmeldecode fuer Nestor lautet: ${pin}`, "",
    "Der Code gilt zehn Minuten.", "", "Viele Gruesse", "Niclas",
  ].join("\r\n");
  const socket = connect({ hostname: "smtp.gmail.com", port: 465 }, { secureTransport: "on", allowHalfOpen: false });
  await socket.opened;
  const reader = socket.readable.getReader();
  const writer = socket.writable.getWriter();
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let puffer = "";
  const antwort = async (): Promise<string> => {
    while (true) {
      const zeilen = puffer.split("\r\n");
      const ende = zeilen.findIndex((z) => /^\d{3} /.test(z));
      if (ende >= 0) {
        const text = zeilen.slice(0, ende + 1).join("\r\n");
        puffer = zeilen.slice(ende + 1).join("\r\n");
        if (!/^[23]/.test(text)) throw new Error(`SMTP: ${text.slice(0, 120)}`);
        return text;
      }
      const teil = await reader.read();
      if (teil.done) throw new Error("SMTP-Verbindung unerwartet beendet");
      puffer += decoder.decode(teil.value, { stream: true });
    }
  };
  const senden = async (zeile: string) => {
    await writer.write(encoder.encode(`${zeile}\r\n`));
    return antwort();
  };
  const b64 = (text: string) => btoa(text);
  try {
    await antwort();
    await senden("EHLO nestor");
    await senden("AUTH LOGIN");
    await senden(b64(benutzer));
    await senden(b64(env.GMAIL_SMTP_PASSWORT.replace(/\s/g, "")));
    await senden(`MAIL FROM:<${benutzer}>`);
    await senden(`RCPT TO:<${sauber(a.email)}>`);
    await senden("DATA");
    await senden(`${inhalt}\r\n.`);
    await writer.write(encoder.encode("QUIT\r\n"));
  } finally {
    reader.releaseLock();
    writer.releaseLock();
    await socket.close();
  }
}

const ESC = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const KOPF = `<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Nestor testen</title><style>body{font:16px system-ui;background:#f8fafc;color:#0f172a;margin:0;padding:32px 16px}main{max-width:460px;margin:auto}form{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:24px}label{display:block;margin:14px 0 5px}input,textarea,button{box-sizing:border-box;width:100%;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}button{margin-top:18px;background:#1e1b4b;color:white;border:0}.hinweis{color:#475569;line-height:1.5}.fehler{color:#b91c1c}</style>`;

export function registrierungsSeite(fehler = ""): string {
  return `<!doctype html><html lang="de"><head>${KOPF}</head><body><main><h1>Nestor testen</h1><p class="hinweis">Trag dich für den Pilotzugang ein. Du erhältst einen sechsstelligen Anmeldecode per E-Mail.</p><form method="post" action="/anmelden">${fehler ? `<p class="fehler">${ESC(fehler)}</p>` : ""}<label>Name</label><input name="name" autocomplete="name" required minlength="2"><label>E-Mail-Adresse</label><input name="email" type="email" autocomplete="email" required><label>Woher kennst du Niclas?</label><textarea name="herkunft" required minlength="2" rows="3"></textarea><label><input style="width:auto" type="checkbox" name="datenschutz" value="ja" required> Meine Angaben dürfen für den Nestor-Pilottest und die Zugangsmail gespeichert werden.</label><button>Code anfordern</button></form></main></body></html>`;
}

export function pinSeite(email: string, meldung = ""): string {
  return `<!doctype html><html lang="de"><head>${KOPF}</head><body><main><h1>Code eingeben</h1><p class="hinweis">Wir haben einen Code an ${ESC(email)} geschickt.</p><form method="post" action="/pin">${meldung ? `<p class="fehler">${ESC(meldung)}</p>` : ""}<input type="hidden" name="email" value="${ESC(email)}"><label>Sechsstelliger Code</label><input name="pin" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" required autofocus><button>Anmelden</button></form></main></body></html>`;
}
