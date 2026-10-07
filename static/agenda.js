"use strict";

// Agenda per Prompt (Lastenheft 4.1): Eingabefeld (tippen, einfügen, sprechen) + bearbeitbare Tabelle.
// Backend: coach/agenda_prompt.py, coach/api_agenda.py. Nutzt $, el, icon, api, RATE, WORKLET aus basis.js.
// Die Tabelle speist dasselbe Format, das /api/einrichten erwartet (siehe agendaErgebnis(), von app.js benutzt).

let agendaPunkte = [];       // [{titel, minuten, ziel}] – die Arbeitskopie, die die Tabelle zeigt
let agendaLaeuft = false;    // ein Vorschlag (Text oder Sprache) ist unterwegs
let agendaSchluesselDa = true;
let agendaHoert = false;     // Mikro-Aufnahme läuft, bis zum zweiten Klick

function agendaInit() {
  $("f-agenda").replaceChildren(
    el("div", { class: "agenda-eingabe" },
      el("textarea", {
        id: "agenda-feld", rows: "1",
        placeholder: "Was steht heute an? Tippen, einfügen oder 🎤 sprechen",
      }),
      el("div", { class: "agenda-knoepfe" },
        el("button", { id: "agenda-mikro", class: "icon", type: "button",
          "data-tip": "Sprechen – bis zum zweiten Klick" }, icon("mikro")),
        el("button", { id: "agenda-senden", class: "primaer klein", type: "button" }, "Absenden"))),
    el("p", { id: "agenda-antwort", class: "agenda-antwort", hidden: "" }),
    el("p", { id: "agenda-hinweis", class: "agenda-hinweis leise-text", hidden: "" },
      "Ohne OpenAI-Schlüssel nicht möglich – die Tabelle lässt sich weiterhin von Hand bearbeiten."),
    el("div", { id: "agenda-tabelle", class: "agenda-tabelle" }),
    el("p", { id: "agenda-summe", class: "agenda-summe leise-text" }));
  $("agenda-senden").onclick = agendaSenden;
  $("agenda-feld").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); agendaSenden(); }
  };
  $("agenda-mikro").onclick = agendaMikroKlick;
  agendaTabelleRendern();
}

// ---------- Tabelle ----------
function agendaZeile(p, i) {
  return el("div", { class: "agenda-zeile" },
    el("div", { class: "agenda-reihenfolge" },
      el("button", { class: "icon klein", type: "button", "data-tip": "Nach oben",
        ...(i === 0 ? { disabled: "" } : {}), onclick: () => agendaVerschieben(i, -1) }, "↑"),
      el("button", { class: "icon klein", type: "button", "data-tip": "Nach unten",
        ...(i === agendaPunkte.length - 1 ? { disabled: "" } : {}), onclick: () => agendaVerschieben(i, 1) }, "↓")),
    el("input", { value: p.titel ?? "", placeholder: "Punkt", oninput: (e) => { p.titel = e.target.value; } }),
    el("input", { type: "number", min: "1", max: "240", value: p.minuten ?? 10, title: "Minuten",
      oninput: (e) => { p.minuten = e.target.value; agendaSummeRendern(); } }),
    el("input", { value: p.ziel ?? "", placeholder: "Ziel (optional)", oninput: (e) => { p.ziel = e.target.value; } }),
    el("button", { class: "icon klein", type: "button", "data-tip": "Punkt entfernen",
      onclick: () => { agendaPunkte.splice(i, 1); agendaTabelleRendern(); } }, icon("zu")));
}
function agendaTabelleRendern() {
  $("agenda-tabelle").replaceChildren(
    ...(agendaPunkte.length ? agendaPunkte.map((p, i) => agendaZeile(p, i))
      : [el("p", { class: "leise-text" }, "Noch keine Punkte – oben eingeben oder von Hand hinzufügen.")]),
    el("button", { class: "leise klein agenda-plus", type: "button",
      onclick: () => { agendaPunkte.push({ titel: "", minuten: 10, ziel: "" }); agendaTabelleRendern(); } }, "+ Punkt"));
  agendaSummeRendern();
}
function agendaSummeRendern() {
  $("agenda-summe").textContent = agendaPunkte.length
    ? `Summe: ${agendaPunkte.reduce((s, p) => s + (Number(p.minuten) || 0), 0)} min`
    : "";
}
function agendaVerschieben(i, richtung) {
  const j = i + richtung;
  if (j < 0 || j >= agendaPunkte.length) return;
  [agendaPunkte[i], agendaPunkte[j]] = [agendaPunkte[j], agendaPunkte[i]];
  agendaTabelleRendern();
}

// Vom Server übernommene Agenda (anderer Tab, anderes Gerät) – aufgerufen aus app.js: formAusServer().
function agendaVonServer(agenda) {
  agendaPunkte = agenda.map((p) => ({ titel: p.titel ?? "", ziel: p.ziel ?? "", minuten: p.minuten ?? 10 }));
  agendaTabelleRendern();
}
// Was /api/einrichten unter "agenda" bekommt – aufgerufen aus app.js: formularDaten().
function agendaErgebnis() {
  return agendaPunkte.map((p) => ({ titel: p.titel ?? "", ziel: p.ziel ?? "", minuten: Number(p.minuten) || 10 }));
}
// Ohne Schlüssel bzw. LMC_OFFLINE=1: Eingabefeld ausgegraut, Tabelle bleibt von Hand bedienbar.
function agendaSchluesselRendern(vorhanden) {
  agendaSchluesselDa = !!vorhanden;
  const aus = !agendaSchluesselDa || agendaLaeuft;
  $("agenda-feld").disabled = $("agenda-senden").disabled = $("agenda-mikro").disabled = aus;
  $("agenda-hinweis").hidden = agendaSchluesselDa;
}

// ---------- Eingabe: Text ----------
function agendaBisherWert() {
  return agendaPunkte.length ? { titel: $("f-titel").value, punkte: agendaPunkte } : null;
}
function agendaUebernehmen(d) {
  agendaPunkte = (d.punkte ?? []).map((p) => ({ titel: p.titel ?? "", ziel: p.ziel ?? "", minuten: p.minuten ?? 10 }));
  if (d.titel && !$("f-titel").value.trim()) $("f-titel").value = d.titel;
  $("agenda-antwort").hidden = !d.antwort;
  $("agenda-antwort").textContent = d.antwort ?? "";
  agendaTabelleRendern();
}
function agendaLaufendSetzen(an) {
  agendaLaeuft = an;
  agendaSchluesselRendern(agendaSchluesselDa);
  $("agenda-senden").textContent = an ? "…" : "Absenden";
}
async function agendaSenden() {
  const text = $("agenda-feld").value.trim();
  if (!text || agendaLaeuft) return;
  agendaLaufendSetzen(true);
  try {
    const d = await api("/api/agenda/vorschlag", { eingabe: text, bisher: agendaBisherWert() });
    $("agenda-feld").value = "";
    agendaUebernehmen(d);
  } finally { agendaLaufendSetzen(false); }
}

// ---------- Eingabe: Sprache (eigener kurzer Mitschnitt, kein Dauerstrom wie das Meeting-Mikro) ----------
const agendaAufnahme = {
  ctx: null, stream: null, worklet: null, proben: [], faktor: 1, pos: 0,
  async starten() {
    this.proben = [];
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
    try { this.ctx = new AudioContext({ sampleRate: RATE }); } catch { this.ctx = new AudioContext(); }
    const quelle = this.ctx.createMediaStreamSource(this.stream);
    this.faktor = this.ctx.sampleRate / RATE; this.pos = 0;
    await this.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    this.worklet = new AudioWorkletNode(this.ctx, "sammler");
    const leise = this.ctx.createGain(); leise.gain.value = 0;
    quelle.connect(this.worklet); this.worklet.connect(leise); leise.connect(this.ctx.destination);
    this.worklet.port.onmessage = (e) => this._daten(e.data);
  },
  _daten(f) {
    let p = this.pos;
    for (; p < f.length; p += this.faktor) {
      const i = Math.floor(p), a = f[i], b = f[i + 1] ?? a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * (p - i)));
      this.proben.push(v < 0 ? v * 0x8000 : v * 0x7fff);
    }
    this.pos = p - f.length;
  },
  async stoppen() {
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    const proben = this.proben;
    this.ctx = this.stream = this.worklet = null; this.proben = [];
    return agendaWavBauen(proben, RATE);
  },
};
function agendaWavBauen(proben, rate) {
  const puffer = new ArrayBuffer(44 + proben.length * 2);
  const d = new DataView(puffer);
  const text = (o, s) => { for (let i = 0; i < s.length; i++) d.setUint8(o + i, s.charCodeAt(i)); };
  text(0, "RIFF"); d.setUint32(4, 36 + proben.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true);
  d.setUint32(24, rate, true); d.setUint32(28, rate * 2, true); d.setUint16(32, 2, true); d.setUint16(34, 16, true);
  text(36, "data"); d.setUint32(40, proben.length * 2, true);
  for (let i = 0; i < proben.length; i++) d.setInt16(44 + i * 2, proben[i], true);
  return new Blob([puffer], { type: "audio/wav" });
}
async function agendaMikroKlick() {
  if (agendaHoert) {
    agendaHoert = false;
    iconSetzen("agenda-mikro", "mikro");
    const wav = await agendaAufnahme.stoppen();
    await agendaSpracheSenden(wav);
    return;
  }
  try {
    await agendaAufnahme.starten();
    agendaHoert = true;
    iconSetzen("agenda-mikro", "mikroAus");
  } catch (e) { alert(`Mikrofon nicht verfügbar: ${e}`); }
}
async function agendaSpracheSenden(wav) {
  agendaLaufendSetzen(true);
  try {
    const form = new FormData();
    form.append("datei", wav, "agenda.wav");
    form.append("bisher", JSON.stringify(agendaBisherWert()));
    const r = await fetch("/api/agenda/sprache", { method: "POST", body: form });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { alert(`Fehler: ${d.detail ?? r.status}`); return; }
    agendaUebernehmen(d);
  } finally { agendaLaufendSetzen(false); }
}
