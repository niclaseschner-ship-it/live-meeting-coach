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

// Eigener OpenAI-Schlüssel (optional, Abschnitt 6): ruft den vorhandenen /api/schluessel auf, der Dashboard-Eintrag
// hat dort Vorrang vor OPENAI_API_KEY. Prüfen reicht hier – die Moduswahl darunter bleibt unverändert.
async function schluesselPruefen() {
  const wert = $("sk-eingabe").value.trim();
  if (!wert) return;
  const m = $("sk-meldung");
  m.hidden = false; m.className = "s-meldung"; m.textContent = "Prüfe bei OpenAI …";
  $("sk-pruefen").disabled = true;
  try {
    const r = await fetch("/api/schluessel", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schluessel: wert }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { m.textContent = d.detail ?? `Fehler ${r.status}`; return; }
    m.className = "s-meldung ok";
    m.textContent = d.ende ? `Schlüssel …${d.ende} wird verwendet.` : "Schlüssel wird verwendet.";
  } catch {
    m.textContent = "Server gerade nicht erreichbar.";
  } finally {
    $("sk-pruefen").disabled = false;
  }
}

(async () => {
  const d = await richtwerteHolen();
  if (d.richtwert_live_eur != null) $("kosten-live").textContent = euro(d.richtwert_live_eur);
  if (d.richtwert_knopfdruck_eur != null) $("kosten-knopfdruck").textContent = euro(d.richtwert_knopfdruck_eur);
  $("karte-live").onclick = () => modusWaehlen("live");
  $("karte-knopfdruck").onclick = () => modusWaehlen("knopfdruck");
  $("sk-pruefen").onclick = schluesselPruefen;
  $("sk-eingabe").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); schluesselPruefen(); } };
})();
