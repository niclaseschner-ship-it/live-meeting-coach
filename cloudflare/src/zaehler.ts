/**
 * KundenZaehler: ein Durable Object je Kunde, zählt dessen gleichzeitig laufende Meetings gegen
 * `max_meetings` (Secret KUNDEN). Durchsetzung "mit vertretbarem Aufwand" (Ticket #5) – bewusst einfach:
 *
 * - Ein Meeting zählt erst, wenn es wirklich gestartet wurde: `/pruefen`, aufgerufen von `/intern/meeting-start`
 *   in `index.ts`, das wiederum der Coach beim echten `/api/start` aufruft (Ticket #12) – nicht mehr schon beim
 *   bloßen Ansehen der Startseite.
 * - Es zählt weiter, bis entweder `/beenden` kommt (aktives Ende, `/intern/meeting-ende`, vom Coach bei
 *   `/api/abschluss/fertig` ausgelöst) oder `VERFALL_MS` lang keine Anfrage mehr für dieses Meeting kam.
 *
 * `VERFALL_MS` ist die Rückfalllösung für den Fall, dass der Coach sein Ende nie meldet (Browser zu, Absturz,
 * Netz weg) – seit Ticket #12 kein exaktes "Meeting beendet" mehr nötig, weil der häufige Fall (reguläres
 * Ende über "Fertig") jetzt sofort über `/beenden` freigegeben wird; nur der Rest läuft weiter über die
 * (jetzt kürzere) Verfallszeit ab.
 *
 * Die eigentliche Zähl-Logik steht in `zaehler-logik.ts` (ohne Workers-Laufzeit, testbar mit `npm test`);
 * hier nur die dünne Durable-Object-Hülle darum.
 */

import { DurableObject } from "cloudflare:workers";
import {
  beenden, pruefenUndAktualisieren, tagesdeckelErreicht, tageskostenBuchen, type Tageskosten, type Zustand,
} from "./zaehler-logik";

export {
  TAGESDECKEL_USD, VERFALL_MS, beenden, pruefenUndAktualisieren, tagesdeckelErreicht, tageskostenBuchen,
  type Tageskosten, type Zustand,
} from "./zaehler-logik";

export class KundenZaehler extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method !== "POST") {
      return new Response("Nur POST /pruefen oder /beenden.", { status: 404 });
    }
    const zustand = ((await this.ctx.storage.get<Zustand>("zustand")) ?? {}) as Zustand;

    if (url.pathname === "/pruefen") {
      const { meetingId, maxMeetings } = (await request.json()) as { meetingId: string; maxMeetings: number };
      // Ticket #64: Tagesdeckel vor dem Gleichzeitigkeits-Limit prüfen – ein erschöpfter Tagesdeckel lässt kein
      // neues Meeting zu, unabhängig von max_meetings. Laufende Meetings sind davon nicht betroffen (nur /pruefen
      // beim Start fragt das ab).
      const tageskosten = await this.ctx.storage.get<Tageskosten>("tageskosten");
      if (tagesdeckelErreicht(tageskosten, Date.now())) {
        return Response.json({ erlaubt: false, aktive: Object.keys(zustand).length, tagesdeckel: true });
      }
      const ergebnis = pruefenUndAktualisieren(zustand, meetingId, maxMeetings, Date.now());
      await this.ctx.storage.put("zustand", ergebnis.zustand);
      return Response.json({ erlaubt: ergebnis.erlaubt, aktive: ergebnis.aktive });
    }
    if (url.pathname === "/beenden") {
      const { meetingId, kostenUsd } = (await request.json()) as { meetingId: string; kostenUsd?: number };
      const ergebnis = beenden(zustand, meetingId, Date.now());
      await this.ctx.storage.put("zustand", ergebnis.zustand);
      // Ticket #64: Kosten des beendeten Meetings auf den Tagesdeckel buchen (coach/api_abschluss.py liefert
      // kostenUsd mit `/intern/meeting-ende`); ohne Angabe oder mit 0 nichts zu buchen.
      if (typeof kostenUsd === "number" && kostenUsd > 0) {
        const bisher = await this.ctx.storage.get<Tageskosten>("tageskosten");
        await this.ctx.storage.put("tageskosten", tageskostenBuchen(bisher, kostenUsd, Date.now()));
      }
      return Response.json({ aktive: ergebnis.aktive });
    }
    return new Response("Nur POST /pruefen oder /beenden.", { status: 404 });
  }
}
