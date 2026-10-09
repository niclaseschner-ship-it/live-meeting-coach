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
let stufeWirdGesetzt = false;

async function stufeWaehlen(stufe) {
  if (stufeWirdGesetzt) return;
  stufeWirdGesetzt = true;
  const karten = [$("karte-basis"), $("karte-premium")];
  const vorher = karten.map(k => k.disabled);
  karten.forEach(k => { k.disabled = true; });
  const meldung = $("stufe-fehlt");
  meldung.hidden = false;
  meldung.textContent = `Nestor ${stufe === "premium" ? "Premium" : "Basis"} wird vorbereitet …`;
  const nurKnopfdruck = stufe === "basis" && $("nur-knopfdruck").checked;
  try {
    const r = await fetch("/api/stufe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stufe, nur_knopfdruck: nurKnopfdruck }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Auswahl nicht übernommen (Fehler ${r.status}).`);
    const modus = nurKnopfdruck ? "knopfdruck" : "live";
    if (d.ok !== true || d.stufe !== stufe || d.modus !== modus) {
      throw new Error("Der Server hat die gewählte Variante nicht bestätigt. Bitte erneut wählen.");
    }
    try { sessionStorage.setItem("nestor-gewaehlte-stufe", stufe); } catch { /* privater Browser: bestätigte Serverwahl bleibt gültig */ }
    location.href = "/meeting";
  } catch (e) {
    meldung.textContent = e instanceof TypeError ? "Server nicht erreichbar. Die Variante wurde nicht übernommen; bitte erneut wählen." : e.message;
    karten.forEach((k, i) => { k.disabled = vorher[i]; });
    stufeWirdGesetzt = false;
  }
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
    $("karte-premium").disabled = false; // mit eigenem Schlüssel ist Premium auch ohne Niclas' Schlüssel wählbar
    m.textContent = d.ende ? `Schlüssel …${d.ende} wird verwendet.` : "Schlüssel wird verwendet.";
  } catch {
    m.textContent = "Server gerade nicht erreichbar.";
  } finally {
    $("sk-pruefen").disabled = false;
  }
}

// Sofort anhängen, nicht erst nach /api/start: beim Kaltstart des Containers dauert das Sekunden, und ein Klick in
// dieser Zeit verpuffte (Cloudtest 08.10. abends).
$("karte-basis").onclick = () => stufeWaehlen("basis");
$("karte-premium").onclick = () => stufeWaehlen("premium");
$("sk-pruefen").onclick = schluesselPruefen;
$("sk-eingabe").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); schluesselPruefen(); } };

(async () => {
  const d = await richtwerteHolen();
  if (d.richtwert_basis_eur != null) $("kosten-basis").textContent = euro(d.richtwert_basis_eur);
  if (d.richtwert_premium_eur != null) $("kosten-premium").textContent = euro(d.richtwert_premium_eur);
  // Fehlt der Schlüssel einer Stufe auf dem Server, ist sie nicht wählbar (Demos laufen trotzdem im Dashboard)
  const fehlt = [];
  if (!stufeWirdGesetzt && d.basis_bereit === false) { $("karte-basis").disabled = true; fehlt.push("Basis"); }
  if (!stufeWirdGesetzt && d.premium_bereit === false) { $("karte-premium").disabled = true; fehlt.push("Premium"); }
  if (fehlt.length && !stufeWirdGesetzt) {
    $("stufe-fehlt").hidden = false;
    $("stufe-fehlt").textContent = `Nestor ${fehlt.join(" und ")} ist auf diesem Server gerade nicht eingerichtet (kein Schlüssel).`;
  }
  // „Nur auf Knopfdruck“ ist vorerst aus dem Angebot (Ticket #27) – der Schalter bleibt ausgeblendet und aus
  $("nur-knopfdruck").checked = false;
})();
