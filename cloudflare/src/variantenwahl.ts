/** Bestätigte Auswahl überlebt Container-Ruhe/Neustart, ohne Kundendaten oder Schlüssel abzulegen.
 *
 * Ticket #60: Der Container hat keine Vorgabe-Stufe (`LMC_STUFE` entfällt). Gibt es hier keine gespeicherte Wahl,
 * geht auch keine Kopfzeile mit – der Coach bleibt unbestimmt und weist einen Meetingstart mit 409 ab, statt still in
 * einer Stufe zu laufen. Nach „Fertig“ ist das Meeting beendet: jede weitere Anfrage mit seinem (30 Tage gültigen)
 * Cookie bekommt 410 und erreicht den Container nicht mehr – ein altes Handy landet nicht in einem frischen Container. */
export interface Variantenwahl { stufe: "basis" | "premium"; modus: "live" | "knopfdruck" }
export interface WahlSpeicher {
  get<T>(key: string): Promise<T | undefined>;
  put(key: string, value: Variantenwahl | boolean): Promise<unknown>;
}

const MEETING_COOKIE = "nestor_meeting";

/** Vom Worker bei `/intern/meeting-ende` gesetzt (Durable Object des Meetings, siehe `Nestor.meetingBeenden`). */
export async function meetingBeenden(storage: WahlSpeicher): Promise<void> {
  await storage.put("beendet", true);
}

export function beendetAntwort(): Response {
  return new Response(
    "Dieses Meeting ist beendet. Für ein neues Meeting am Laptop starten und den QR-Code neu scannen.",
    {
      status: 410,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Set-Cookie": `${MEETING_COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax`,
      },
    },
  );
}

/** Für die Telegram-Startmeldung: welche Variante lief (Ticket #60, Forensik des Pilotabends 09.10.). */
export function varianteText(stufe: unknown, modus?: unknown): string {
  if (stufe === "premium") return "Premium (OpenAI)";
  if (stufe === "basis") return modus === "knopfdruck" ? "Basis (Mistral) · Nur auf Knopfdruck" : "Basis (Mistral)";
  return "unbekannt";
}

export async function mitVariantenwahl(request: Request, storage: WahlSpeicher,
  weiter: (request: Request) => Promise<Response>): Promise<Response> {
  if (await storage.get<boolean>("beendet")) return beendetAntwort();
  const headers = new Headers(request.headers);
  // Ausschließlich gespeicherte, serverseitig bestätigte Werte, niemals Browser-Header übernehmen.
  headers.delete("X-Nestor-Stufe");
  headers.delete("X-Nestor-Modus");
  const wahl = await storage.get<Variantenwahl>("variantenwahl");
  if (wahl) {
    headers.set("X-Nestor-Stufe", wahl.stufe);
    headers.set("X-Nestor-Modus", wahl.modus);
  }
  const response = await weiter(new Request(request, { headers }));
  if (request.method === "POST" && new URL(request.url).pathname === "/api/stufe" && response.ok) {
    const data = await response.clone().json() as Record<string, unknown>;
    if (data.ok === true && (data.stufe === "basis" || data.stufe === "premium") &&
        (data.modus === "live" || (data.modus === "knopfdruck" && data.stufe === "basis"))) {
      await storage.put("variantenwahl", { stufe: data.stufe, modus: data.modus });
    } else {
      return Response.json({ detail: "Der Server hat keine gültige Variante bestätigt." }, { status: 502 });
    }
  }
  return response;
}
