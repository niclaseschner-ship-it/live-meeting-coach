"use strict";

// Agenda per Prompt (Lastenheft 4.1): Eingabefeld (tippen, einfügen, sprechen) + bearbeitbare Tabelle.
// Backend: coach/agenda_prompt.py, coach/api_agenda.py. Nutzt $, el, icon, api, RATE, WORKLET aus basis.js.
// Das Eingabefeld (#f-agenda-eingabe) steht groß und zentral ganz oben im Einrichten-Bereich (Ticket #10);
// die Tabelle (#f-agenda) darunter, nach Titel/Ziel. Die Tabelle speist dasselbe Format, das /api/einrichten
// erwartet (siehe agendaErgebnis(), von app.js benutzt). Titel, Ziel und Teilnehmende übernimmt dieselbe
// Eingabe gleich mit (siehe agendaUebernehmen()) – die Entscheidung, ob über­schrieben wird, trifft das
// Sprachmodell (coach/agenda_prompt.py), nicht diese Oberfläche.

let agendaPunkte = [];       // [{titel, minuten, ziel}] – die Arbeitskopie, die die Tabelle zeigt
let agendaLaeuft = false;    // ein Vorschlag (Text oder Sprache) ist unterwegs
let agendaSchluesselDa = true;
let agendaDialog = [];      // nur im offenen Tab, nicht dauerhaft gespeichert

function agendaInit() {
  $("f-agenda-eingabe").replaceChildren(
    el("div", { class: "agenda-eingabe" },
      el("textarea", {
        id: "agenda-feld", rows: "2",
        placeholder: "Beschreibe euer Vorhaben – Nestor entwirft eine Agenda und fragt bei Unklarheiten nach. Auch Einladungen lassen sich einfügen.",
      }),
      el("div", { class: "agenda-knoepfe" },
        el("button", { id: "agenda-mikro", class: "icon", type: "button",
          "data-tip": "Sprechtaste: halten, sprechen, loslassen", "aria-label": "Sprechtaste halten" }, icon("mikro")),
        el("button", { id: "agenda-senden", class: "primaer klein", type: "button" }, "Absenden"))),
    el("p", { id: "agenda-antwort", class: "agenda-antwort", role: "status", "aria-live": "polite", hidden: "" }),
    el("p", { id: "agenda-hinweis", class: "agenda-hinweis leise-text", hidden: "" },
      "Ohne KI-Verbindung nicht möglich – die Tabelle lässt sich weiterhin von Hand bearbeiten."));
  $("f-agenda").replaceChildren(
    el("div", { id: "agenda-tabelle", class: "agenda-tabelle" }),
    el("p", { id: "agenda-summe", class: "agenda-summe leise-text" }));
  $("agenda-senden").onclick = agendaSenden;
  $("agenda-feld").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); agendaSenden(); }
  };
  // Ticket #66: dasselbe Bedienmodell wie jede Sprechtaste (basis.js: sprechknopf) – halten, sprechen, loslassen
  sprechknopf($("agenda-mikro"), {
    anzeige: (text) => { $("agenda-antwort").hidden = false; $("agenda-antwort").textContent = text; },
    ruhe: () => null, // die Antwort (Rückfrage, Entwurf) bleibt stehen
    bereit: () => !agendaLaeuft && agendaSchluesselDa,
    start: () => agendaAufnahme.starten(),
    ende: () => agendaAufnahme.stoppen(),
    senden: agendaSpracheSenden,
  });
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
  agendaDialog = [];
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
// Gibt dem Sprachmodell den vollen Stand mit (Titel, Ziel, Teilnehmende, Tabelle), damit es entscheiden kann,
// ob eine neue Eingabe sie überschreibt oder unverändert lässt (coach/agenda_prompt.py: nur bei leerem Feld
// oder eindeutig neuem Meeting; ein gezielter Änderungswunsch trifft nur das gemeinte Feld).
function agendaBisherWert() {
  const titel = $("f-titel").value.trim();
  const ziel = $("f-ziel").value.trim();
  const teilnehmende = [...$("f-teilnehmende").querySelectorAll("input")].map((i) => i.value).filter(Boolean);
  if (!agendaPunkte.length && !titel && !ziel && !teilnehmende.length) return null;
  return { titel, ziel, punkte: agendaPunkte, teilnehmende };
}
function agendaUebernehmen(d, eingabe = "") {
  agendaPunkte = (d.punkte ?? []).map((p) => ({ titel: p.titel ?? "", ziel: p.ziel ?? "", minuten: p.minuten ?? 10 }));
  if (d.titel) $("f-titel").value = d.titel;
  if (d.ziel) $("f-ziel").value = d.ziel;
  if (d.teilnehmende?.length) teilnehmendeSetzen(d.teilnehmende);
  $("agenda-antwort").hidden = !d.antwort;
  $("agenda-antwort").textContent = (d.status === "rueckfrage" ? "Rückfrage: " : "") + (d.antwort ?? "");
  $("agenda-feld").placeholder = d.status === "rueckfrage"
    ? "Antworte hier auf Nestors Rückfrage …" : "Agenda ergänzen oder ändern – oder ein neues Vorhaben beschreiben …";
  if (eingabe && d.status !== "fehler") {
    agendaDialog.push({ role: "user", content: eingabe }, { role: "assistant", content: d.antwort ?? "" });
    agendaDialog = agendaDialog.slice(-8);
  }
  if (d.status === "rueckfrage") $("agenda-feld").focus();
  agendaTabelleRendern();
}
function agendaLaufendSetzen(an) {
  agendaLaeuft = an;
  agendaSchluesselRendern(agendaSchluesselDa);
  $("agenda-senden").textContent = an ? "Agenda wird vorbereitet …" : "Absenden";
}
async function agendaSenden() {
  const text = $("agenda-feld").value.trim();
  if (!text || agendaLaeuft) return;
  agendaLaufendSetzen(true);
  try {
    const d = await api("/api/agenda/vorschlag", { eingabe: text, bisher: agendaBisherWert(), verlauf: agendaDialog });
    if (!d) return; // api zeigt Fehler; Eingabe für erneuten Versuch behalten
    if (d.status !== "fehler") $("agenda-feld").value = "";
    agendaUebernehmen(d, text);
  } finally {
    agendaLaufendSetzen(false);
    if ($("agenda-antwort").textContent.startsWith("Rückfrage:")) $("agenda-feld").focus();
  }
}

// ---------- Eingabe: Sprache (eigener kurzer Mitschnitt, kein Dauerstrom wie das Meeting-Mikro) ----------
const agendaAufnahme = {
  ctx: null, stream: null, worklet: null, proben: [], faktor: 1, pos: 0,
  async starten() {
    this.proben = [];
    try { this.ctx = new AudioContext({ sampleRate: RATE }); } catch { this.ctx = new AudioContext(); }
    try {
      // AudioContext direkt im Tastendruck aktivieren, bevor die Mikrofonfreigabe asynchron wartet.
      await this.ctx.resume();
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
      const quelle = this.ctx.createMediaStreamSource(this.stream);
      this.faktor = this.ctx.sampleRate / RATE; this.pos = 0;
      await this.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
      this.worklet = new AudioWorkletNode(this.ctx, "sammler");
      const leise = this.ctx.createGain(); leise.gain.value = 0;
      quelle.connect(this.worklet); this.worklet.connect(leise); leise.connect(this.ctx.destination);
      this.worklet.port.onmessage = (e) => this._daten(e.data);
    } catch (err) {
      this.stream?.getTracks().forEach((t) => t.stop());
      try { await this.ctx?.close(); } catch { /* Kontext kann bereits beendet sein */ }
      this.ctx = this.stream = this.worklet = null; this.proben = [];
      throw err;
    }
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
async function agendaSpracheSenden(wav) {
  $("agenda-antwort").hidden = false; $("agenda-antwort").textContent = "Agenda wird vorbereitet …";
  agendaLaufendSetzen(true);
  try {
    const form = new FormData();
    form.append("datei", wav, "agenda.wav");
    form.append("bisher", JSON.stringify(agendaBisherWert()));
    form.append("verlauf", JSON.stringify(agendaDialog));
    const r = await fetch("/api/agenda/sprache", { method: "POST", body: form });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return { text: `Fehler: ${d.detail ?? r.status}`, fehler: true };
    agendaUebernehmen(d, d.eingabe);
  } catch (err) {
    return { text: `Fehler: ${err.message ?? err}`, fehler: true };
  } finally { agendaLaufendSetzen(false); }
}
