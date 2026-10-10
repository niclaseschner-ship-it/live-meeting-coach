/**
 * Quer durch alle Antworten genutzte Härtung (Ticket #63): zeitkonstante Prüfung des Worker-Geheimnisses für
 * `/intern/*`, Sicherheitsheader auf jeder Antwort und die freundliche Kapazitätsseite samt Telegram-Meldung,
 * wenn der Container nicht antwortet. Bewusst ohne jede Geschäftslogik, damit `index.ts` nur schmale
 * Aufrufstellen braucht.
 */

import { gleichZeitkonstant } from "./anmeldung";

/** Zeitkonstanter Ersatz für `headers.get("X-Nestor-Geheimnis") !== env.WORKER_GEHEIMNIS` (Befund 4,
 * review/r3_sicherheit.md) – genutzt von allen `/intern/*`-Routen in index.ts. */
export function workerGeheimnisPasst(request: Request, geheimnis: string): boolean {
  const kopf = request.headers.get("X-Nestor-Geheimnis");
  return !!kopf && !!geheimnis && gleichZeitkonstant(kopf, geheimnis);
}

/** CSP passend zu den tatsächlich genutzten Quellen (geprüft: cloudflare/src/*.ts, static/*.html, static/*.js –
 * siehe cloudflare/README.md). `style-src 'unsafe-inline'` ist eine bewusste, schmale Ausnahme: Die vom Worker
 * selbst erzeugten Seiten (Anmeldung, Registrierung, PIN) tragen ihr CSS in einem `<style>`-Block statt in
 * einer eigenen Datei – dafür gibt es im Worker (anders als bei den Dateien unter static/) keine Auslieferung
 * über `/static/`. Inline-`<script>` ist dagegen NICHT ausgenommen: Die beiden Stellen, die das brauchten
 * (static/impressum.html, static/datenschutz.html), wurden nach static/rechtstexte.js verschoben.
 * `blob:` in script-src und worklet-src ist für die Audio-Worklets nötig – Chrome prüft `audioWorklet.addModule` gegen
 * script-src (static/basis.js, static/agenda.js: `addModule` lädt von
 * einer `blob:`-URL). */
const CSP = [
  "default-src 'self'",
  "script-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "worklet-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

/** Setzt die gleichen Sicherheitsheader auf jede Antwort, die den Worker verlässt – egal ob vom Worker selbst
 * erzeugt oder vom Container durchgereicht (einzige Aufrufstelle: der Export in index.ts). */
export function mitSicherheitsheadern(antwort: Response): Response {
  // WebSocket-Upgrades (101) unverändert durchreichen: ein Neuaufbau der Antwort verliert das webSocket-Feld und
  // würde Audio- und Handy-Kanal kappen. Sicherheitsheader sind für den Upgrade ohnehin ohne Wirkung.
  if (antwort.status === 101 || (antwort as Response & { webSocket?: unknown }).webSocket) return antwort;
  const kopie = new Response(antwort.body, antwort);
  kopie.headers.set("Content-Security-Policy", CSP);
  kopie.headers.set("X-Frame-Options", "DENY");
  kopie.headers.set("X-Content-Type-Options", "nosniff");
  kopie.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return kopie;
}

const KAPAZITAET_SEITE = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Nestor · gerade ausgelastet</title>
<style>
  body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; background: #0B1020; color: #E2E8F0;
         margin: 0; padding: 48px 16px; display: grid; justify-content: center; text-align: center; }
  main { max-width: 440px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  p { color: #94A3B8; line-height: 1.5; margin: 0; }
</style>
</head>
<body>
<main>
  <h1>Gerade ausgelastet</h1>
  <p>Nestor hat im Moment keinen freien Platz. Bitte versuch es in ein paar Minuten noch einmal.</p>
</main>
</body>
</html>`;

/** Ruft `aufruf()` auf; schlägt der Container fehl (Kapazität, Kaltstart-Timeout, …), gibt es statt eines
 * rohen Fehlers die freundliche Kapazitätsseite und eine Telegram-Meldung (Befund 2, review/r3_sicherheit.md /
 * U4, review/r2_architektur.md Abschnitt 6.A). */
export async function containerAufrufenOderAusweichen(
  aufruf: () => Promise<Response>,
  melden: (text: string) => void,
  kontext: string,
): Promise<Response> {
  try {
    return await aufruf();
  } catch (fehler) {
    const nachricht = fehler instanceof Error ? fehler.message : String(fehler);
    melden(`⚠️ Nestor: Container-Fehler (${kontext})\n${nachricht}`);
    return new Response(KAPAZITAET_SEITE, { status: 503, headers: { "content-type": "text/html; charset=utf-8" } });
  }
}
