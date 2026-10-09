export interface TelegramEnv {
  TELEGRAM_BOT_TOKEN?: string;
  TELEGRAM_CHAT_ID?: string;
}

/** Kurze Betriebsnachricht an Niclas. Fehler dürfen Anmeldung oder Meeting niemals blockieren. */
export async function telegramMelden(env: TelegramEnv, text: string): Promise<void> {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  const antwort = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text, disable_web_page_preview: true }),
  });
  if (!antwort.ok) throw new Error(`Telegram HTTP ${antwort.status}`);
  const daten = await antwort.json() as { ok?: boolean };
  if (daten.ok !== true) throw new Error("Telegram hat die Nachricht nicht bestätigt");
  // Keine Nachrichteninhalte, Chat-IDs oder Token in Betriebslogs.
  console.info("Telegram-Meldung bestätigt");
}

export function meetingKurz(meetingId: string): string {
  return meetingId.slice(0, 8);
}
