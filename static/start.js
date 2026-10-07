"use strict";

// Startseite (Ticket #1, #13): Richtwerte holen, Stufe setzen (Basis/Premium), weiter zum Dashboard.
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

async function stufeWaehlen(stufe) {
  const nurKnopfdruck = stufe === "basis" && $("nur-knopfdruck").checked;
  try {
    const r = await fetch("/api/stufe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stufe, nur_knopfdruck: nurKnopfdruck }),
    });
    if (!r.ok && r.status !== 409) { alert(`Fehler: ${await r.text()}`); return; } // 409: Meeting läuft schon – trotzdem weiter
  } catch {
    // Server nicht erreichbar: das Dashboard zeigt den Fehler gleich selbst
  }
  location.href = "/meeting";
}

// Eigener OpenAI-Schlüssel (optional, Abschnitt 6): ruft den vorhandenen /api/schluessel auf, der Dashboard-Eintrag
// hat dort Vorrang vor OPENAI_API_KEY. Prüfen reicht hier – gilt nur für Nestor Premium (Basis nutzt Mistral).
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
  if (d.richtwert_basis_eur != null) $("kosten-basis").textContent = euro(d.richtwert_basis_eur);
  if (d.richtwert_premium_eur != null) $("kosten-premium").textContent = euro(d.richtwert_premium_eur);
  // Fehlt der Schlüssel einer Stufe auf dem Server, ist sie nicht wählbar (Demos laufen trotzdem im Dashboard)
  const fehlt = [];
  if (d.basis_bereit === false) { $("karte-basis").disabled = true; fehlt.push("Basis"); }
  if (d.premium_bereit === false) { $("karte-premium").disabled = true; fehlt.push("Premium"); }
  if (fehlt.length) {
    $("stufe-fehlt").hidden = false;
    $("stufe-fehlt").textContent = `Nestor ${fehlt.join(" und ")} ist auf diesem Server gerade nicht eingerichtet (kein Schlüssel).`;
  }
  $("nur-knopfdruck").checked = d.stufe === "basis" && d.modus === "knopfdruck";
  $("karte-basis").onclick = () => stufeWaehlen("basis");
  $("karte-premium").onclick = () => stufeWaehlen("premium");
  $("sk-pruefen").onclick = schluesselPruefen;
  $("sk-eingabe").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); schluesselPruefen(); } };
})();
