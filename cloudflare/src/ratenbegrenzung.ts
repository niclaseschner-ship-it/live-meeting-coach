/**
 * IpZaehler: ein Durable Object je IP-Adresse (idFromName(ip)), zählt deren Versuche je Zweck in einem
 * gleitenden Zeitfenster (Ticket #63). Dünne Hülle um die reine, getestete Logik in
 * `ratenbegrenzung-logik.ts` – gleiches Muster wie `zaehler.ts`/`zaehler-logik.ts`.
 */

import { DurableObject } from "cloudflare:workers";
import { pruefenUndErhoehen, type Grenze, type Zustand } from "./ratenbegrenzung-logik";

export { pruefenUndErhoehen, type Grenze, type Zustand } from "./ratenbegrenzung-logik";

export class IpZaehler extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/pruefen") {
      return new Response("Nur POST /pruefen.", { status: 404 });
    }
    const { zweck, limit, fensterMs } = (await request.json()) as Grenze & { zweck: string };
    const zustand = ((await this.ctx.storage.get<Zustand>("zustand")) ?? {}) as Zustand;
    const ergebnis = pruefenUndErhoehen(zustand, zweck, Date.now(), { limit, fensterMs });
    await this.ctx.storage.put("zustand", ergebnis.zustand);
    return Response.json({ erlaubt: ergebnis.erlaubt });
  }
}
