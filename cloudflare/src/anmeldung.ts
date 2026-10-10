/**
 * Anmeldung und Cookies – reine Funktionen, ohne Workers-Laufzeit außer WebCrypto (auch unter Node
 * vorhanden), damit sie sich ohne Miniflare testen lassen (`npm test`).
 *
 * Ticket #75 (Entscheidung Niclas 10.10.2026): der frühere Passwortweg über ein Secret KUNDEN (feste
 * Kundenliste) ist entfernt. Einziger Zugang ist der Mail-PIN-Dialog (`pilotzugang.ts`); diese Datei liefert
 * ihm nur noch die reine Krypto (Hash, Cookie-Signatur) – die frühere `kundeFuerPasswort`-Prüfung ist Geschichte.
 */

const ENKODIERUNG = new TextEncoder();

export function hexKodieren(puffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(puffer)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", ENKODIERUNG.encode(text));
  return hexKodieren(digest);
}

/** Zeitkonstanter Vergleich zweier Strings gleicher erwarteter Länge – auch für `/intern/*` (sicherheit.ts)
 * und die Cookie-Prüfung hier genutzt, damit nirgends ein normaler `!==`/`===`-Vergleich über ein Geheimnis
 * läuft (Ticket #63). */
export function gleichZeitkonstant(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let unterschied = 0;
  for (let i = 0; i < a.length; i++) unterschied |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return unterschied === 0;
}

async function hmacSchluessel(geheimnis: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", ENKODIERUNG.encode(geheimnis), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

function base64urlKodieren(puffer: ArrayBuffer): string {
  const bin = Array.from(new Uint8Array(puffer)).map((b) => String.fromCharCode(b)).join("");
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Signiert `wert` (z. B. der Kundenname) als Cookie-Inhalt `<wert>.<signatur>`. */
export async function cookieSigniere(wert: string, geheimnis: string): Promise<string> {
  const schluessel = await hmacSchluessel(geheimnis);
  const signatur = await crypto.subtle.sign("HMAC", schluessel, ENKODIERUNG.encode(wert));
  return `${wert}.${base64urlKodieren(signatur)}`;
}

/** Prüft ein signiertes Cookie und liefert den ursprünglichen Wert oder null. */
export async function cookiePruefen(cookie: string | null | undefined, geheimnis: string): Promise<string | null> {
  if (!cookie) return null;
  const punkt = cookie.lastIndexOf(".");
  if (punkt <= 0) return null;
  const wert = cookie.slice(0, punkt);
  const erwartet = await cookieSigniere(wert, geheimnis);
  return gleichZeitkonstant(cookie, erwartet) ? wert : null;
}

/** Einen einzelnen Cookie-Wert aus der `Cookie`-Kopfzeile lesen. */
export function cookieLesen(kopfzeile: string | null, name: string): string | null {
  if (!kopfzeile) return null;
  for (const teil of kopfzeile.split(";")) {
    const [k, ...rest] = teil.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

/**
 * Signierter Wert MIT Ablaufzeit (Ticket #63, Befund 3: das bisherige Kunden-Cookie lief serverseitig nie
 * ab). `zweck` trennt die Verwendungszwecke voneinander (Domänentrennung trotz gleichem Geheimnis) – ein
 * Kunden-Cookie lässt sich so nicht als Meeting-Ticket zweitverwenden. Genutzt für `nestor_kunde` (index.ts)
 * und, über `meeting.ts`, für `nestor_meeting` und das Kopplungstoken im QR-Code.
 */
export async function signiereMitAblauf<T>(
  zweck: string,
  daten: T,
  geheimnis: string,
  jetzt: number,
  gueltigkeitMs: number,
): Promise<string> {
  const nutzlast = JSON.stringify({ zweck, daten, ablaufAt: jetzt + gueltigkeitMs });
  return cookieSigniere(nutzlast, geheimnis);
}

/** Prüft Signatur, Zweck und Ablaufzeit; liefert die ursprünglichen Daten oder null. */
export async function pruefeMitAblauf<T>(
  zweck: string,
  wert: string | null | undefined,
  geheimnis: string,
  jetzt: number,
): Promise<T | null> {
  const geprueft = await cookiePruefen(wert, geheimnis);
  if (!geprueft) return null;
  try {
    const nutzlast = JSON.parse(geprueft) as { zweck?: string; daten?: T; ablaufAt?: number };
    if (nutzlast.zweck !== zweck || typeof nutzlast.ablaufAt !== "number" || nutzlast.ablaufAt < jetzt) return null;
    return nutzlast.daten ?? null;
  } catch {
    return null;
  }
}
