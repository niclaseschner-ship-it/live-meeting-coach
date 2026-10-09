/** Bestätigte Auswahl überlebt Container-Ruhe/Neustart, ohne Kundendaten oder Schlüssel abzulegen. */
export interface Variantenwahl { stufe: "basis" | "premium"; modus: "live" | "knopfdruck" }
export interface WahlSpeicher {
  get<T>(key: string): Promise<T | undefined>;
  put(key: string, value: Variantenwahl): Promise<unknown>;
}
export async function mitVariantenwahl(request: Request, storage: WahlSpeicher,
  weiter: (request: Request) => Promise<Response>): Promise<Response> {
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
