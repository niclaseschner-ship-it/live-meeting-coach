/**
 * Anmeldung und Cookies – reine Funktionen, ohne Workers-Laufzeit außer WebCrypto (auch unter Node
 * vorhanden), damit sie sich ohne Miniflare testen lassen (`npm test`).
 *
 * Kunden stehen im Secret KUNDEN als JSON: {"<kunde>": {"hash": "<sha256 hex>", "max_meetings": 3}}.
 * Das Passwort selbst bestimmt den Kunden – es gibt kein eigenes Namensfeld im Formular (Lastenheft:
 * "Link + Passwort"), darum wird der Hash gegen alle Kunden geprüft.
 */

export interface KundenEintrag {
  hash: string;
  max_meetings: number;
}

export type Kundenliste = Record<string, KundenEintrag>;

const ENKODIERUNG = new TextEncoder();

export function hexKodieren(puffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(puffer)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", ENKODIERUNG.encode(text));
  return hexKodieren(digest);
}

/** Zeitkonstanter Vergleich zweier Hex-Strings gleicher erwarteter Länge. */
function gleichZeitkonstant(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let unterschied = 0;
  for (let i = 0; i < a.length; i++) unterschied |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return unterschied === 0;
}

/** Passwort gegen alle Kunden prüfen – liefert den Kundennamen oder null. */
export async function kundeFuerPasswort(passwort: string, kunden: Kundenliste): Promise<string | null> {
  if (!passwort) return null;
  const hash = await sha256Hex(passwort);
  let treffer: string | null = null;
  // über alle Einträge laufen (nicht beim ersten Treffer abbrechen), damit die Laufzeit nicht verrät,
  // an welcher Stelle der Liste ein Kunde steht
  for (const [name, eintrag] of Object.entries(kunden)) {
    if (gleichZeitkonstant(hash, eintrag.hash.toLowerCase())) treffer = name;
  }
  return treffer;
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
