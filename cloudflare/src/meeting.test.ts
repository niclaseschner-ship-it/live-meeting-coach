import { describe, expect, it } from "vitest";
import {
  KOPPLUNGSTOKEN_GUELTIGKEIT_MS, kopplungstokenPruefen, kopplungstokenSigniere,
  meetingCookiePruefen, meetingCookieSigniere, MEETING_COOKIE_GUELTIGKEIT_MS,
} from "./meeting";

const GEHEIMNIS = "meeting-geheimnis";
const JETZT = 1_700_000_000_000;

describe("Meeting-Cookie (nestor_meeting)", () => {
  it("signiert und prüft dasselbe Ticket erfolgreich, innerhalb der Gültigkeit", async () => {
    const cookie = await meetingCookieSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await meetingCookiePruefen(cookie, GEHEIMNIS, JETZT + 1000)).toEqual({ meetingId: "m1", kunde: "acme" });
  });

  it("verwirft ein abgelaufenes Cookie", async () => {
    const cookie = await meetingCookieSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await meetingCookiePruefen(cookie, GEHEIMNIS, JETZT + MEETING_COOKIE_GUELTIGKEIT_MS + 1)).toBeNull();
  });

  it("verwirft ein fremdes/unsigniertes Cookie", async () => {
    expect(await meetingCookiePruefen("m1.falsche-signatur", GEHEIMNIS, JETZT)).toBeNull();
    expect(await meetingCookiePruefen(null, GEHEIMNIS, JETZT)).toBeNull();
    const fremdGeheimnis = await meetingCookieSigniere({ meetingId: "m1", kunde: "acme" }, "anderes-geheimnis", JETZT);
    expect(await meetingCookiePruefen(fremdGeheimnis, GEHEIMNIS, JETZT)).toBeNull();
  });

  it("ein Kopplungstoken lässt sich nicht als Meeting-Cookie weiterverwenden (Domänentrennung)", async () => {
    const token = await kopplungstokenSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await meetingCookiePruefen(token, GEHEIMNIS, JETZT)).toBeNull();
  });
});

describe("Kopplungstoken (QR-Code)", () => {
  it("signiert und prüft dasselbe Ticket erfolgreich", async () => {
    const token = await kopplungstokenSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await kopplungstokenPruefen(token, GEHEIMNIS, JETZT + 1000)).toEqual({ meetingId: "m1", kunde: "acme" });
  });

  it("ist kurzlebig und verfällt nach KOPPLUNGSTOKEN_GUELTIGKEIT_MS", async () => {
    const token = await kopplungstokenSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await kopplungstokenPruefen(token, GEHEIMNIS, JETZT + KOPPLUNGSTOKEN_GUELTIGKEIT_MS + 1)).toBeNull();
  });

  it("ein Meeting-Cookie lässt sich nicht als Kopplungstoken weiterverwenden (Domänentrennung)", async () => {
    const cookie = await meetingCookieSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    expect(await kopplungstokenPruefen(cookie, GEHEIMNIS, JETZT)).toBeNull();
  });

  it("verwirft ein manipuliertes Token (andere Meeting-ID, alte Signatur)", async () => {
    const token = await kopplungstokenSigniere({ meetingId: "m1", kunde: "acme" }, GEHEIMNIS, JETZT);
    const signatur = token.slice(token.lastIndexOf("."));
    const manipuliert = `${JSON.stringify({ zweck: "kopplung", daten: { meetingId: "fremd", kunde: "acme" }, ablaufAt: JETZT + 1000 })}${signatur}`;
    expect(await kopplungstokenPruefen(manipuliert, GEHEIMNIS, JETZT)).toBeNull();
  });
});
