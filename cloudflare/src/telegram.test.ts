import { afterEach, describe, expect, it, vi } from "vitest";
import { meetingKurz, telegramMelden } from "./telegram";

afterEach(() => vi.restoreAllMocks());

describe("Telegram-Betriebsnachrichten", () => {
  it("tut ohne konfigurierte Secrets nichts", async () => {
    const f = vi.spyOn(globalThis, "fetch");
    await telegramMelden({}, "Test");
    expect(f).not.toHaveBeenCalled();
  });

  it("sendet an den privaten Chat ohne Linkvorschau", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    await telegramMelden({ TELEGRAM_BOT_TOKEN: "bot-secret", TELEGRAM_CHAT_ID: "123" }, "Nestor startet");
    expect(f).toHaveBeenCalledOnce();
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/botbot-secret/sendMessage");
    expect(JSON.parse(String(init?.body))).toEqual({
      chat_id: "123", text: "Nestor startet", disable_web_page_preview: true,
    });
  });

  it("kürzt Meeting-IDs für die Meldung", () => expect(meetingKurz("12345678-abcd")).toBe("12345678"));
  it("erkennt auch unbestätigte Antworten mit HTTP 200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"ok":false}', { status: 200 }));
    await expect(telegramMelden({ TELEGRAM_BOT_TOKEN: "test", TELEGRAM_CHAT_ID: "123" }, "Test"))
      .rejects.toThrow("nicht bestätigt");
  });
});
