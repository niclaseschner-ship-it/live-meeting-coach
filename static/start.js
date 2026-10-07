"use strict";

// Startseite (Ticket #1): Richtwerte holen, Modus setzen, weiter zum Dashboard.
// Eigenständig statt basis.js – das ist für Mikrofon und Nestors Stimme gedacht, hier braucht es das nicht.

const $ = (id) => document.getElementById(id);

async function richtwerteHolen() {
  try {
    const r = await fetch("/api/start");
    return r.ok ? await r.json() : {};
  } catch {
    return {}; // Server gerade nicht erreichbar – die Vorgabewerte im HTML bleiben stehen
  }
}

const euro = (betrag) => `etwa ${betrag.toLocaleString("de-DE", { maximumFractionDigits: 1 })} € je Meetingstunde`;

async function modusWaehlen(modus) {
  try {
    const r = await fetch("/api/modus", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modus }),
    });
    if (!r.ok && r.status !== 409) { alert(`Fehler: ${await r.text()}`); return; } // 409: Meeting läuft schon – trotzdem weiter
  } catch {
    // Server nicht erreichbar: das Dashboard zeigt den Fehler gleich selbst
  }
  location.href = "/meeting";
}

(async () => {
  const d = await richtwerteHolen();
  if (d.richtwert_live_eur != null) $("kosten-live").textContent = euro(d.richtwert_live_eur);
  if (d.richtwert_knopfdruck_eur != null) $("kosten-knopfdruck").textContent = euro(d.richtwert_knopfdruck_eur);
  $("karte-live").onclick = () => modusWaehlen("live");
  $("karte-knopfdruck").onclick = () => modusWaehlen("knopfdruck");
})();
