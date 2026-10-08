"use strict";

// Gemeinsam für Dashboard (app.js) und Handy (handy.js): Hilfen, Icons, Nestors Stimme, Mikrofon.
// Klassisches Skript – die Namen hier sind für die danach geladenen Skripte global sichtbar.

const $ = (id) => document.getElementById(id);
let zustand = null;
let ws = null;

// ---------- Hilfen ----------
const mmss = (s) => { s = Math.max(0, Math.floor(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const el = (tag, attrs = {}, ...kinder) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const k of kinder) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
};
async function api(pfad, daten) {
  const r = await fetch(pfad, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(daten ?? {}) });
  if (!r.ok) { const t = await r.text(); alert(`Fehler: ${t}`); throw new Error(t); }
  return r.json();
}

// ---------- Icons (Linien-Icons im Stil von Lucide, 24×24) ----------
const PFADE = {
  mikro: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
  mikroAus: '<path d="M2 2l20 20"/><path d="M18.89 13.23A7 7 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><path d="M12 19v3"/>',
  frage: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  stopp: '<rect width="14" height="14" x="5" y="5" rx="2"/>',
  weiter: '<polygon points="6 3 20 12 6 21 6 3"/>',
  transkript: '<path d="M15 12h-5"/><path d="M15 8h-5"/><path d="M19 17V5a2 2 0 0 0-2-2H4"/><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/>',
  einstellungen: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  bild: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  neu: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  speichern: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><path d="M12 15V3"/>',
  datei: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  zu: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  muenze: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
  folie: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 8h6"/><path d="M7 12h10"/>',
  suche: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  achtung: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  handy: '<rect width="14" height="20" x="5" y="2" rx="2"/><path d="M12 18h.01"/>',
  wach: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  lautsprecher: '<path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.4 18.4a9 9 0 0 0 0-12.8"/>',
  verlauf: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  // Regeln
  ausreden: '<path d="M18 11V6a2 2 0 0 0-4 0"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-6-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
  thema: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  zeit: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  kurz: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.17a2 2 0 0 0-.59-1.42L12 12l-4.41 4.41A2 2 0 0 0 7 17.83V22"/><path d="M7 2v4.17a2 2 0 0 0 .59 1.42L12 12l4.41-4.41A2 2 0 0 0 17 6.17V2"/>',
  alle: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  ton: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  ergebnisse: '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
  seitengespraeche: '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/>',
  sachlich: '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
  eingehen: '<path d="M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0"/><path d="M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"/>',
};
const icon = (name) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "2"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
  s.innerHTML = PFADE[name] ?? ""; return s;
};
const iconSetzen = (id, name) => $(id).replaceChildren(icon(name));
// Hinweisart → Icon und Farbe des Hinweis-Bands
const HINWEIS_ICON = { ton: "ton", ausreden: "ausreden", ueberlappung: "ausreden", fokus: "thema", zeit: "zeit",
  monolog: "kurz", alle: "alle", ergebnisse: "ergebnisse" };

// ---------- Ton: Nestors Stimme ----------
// Nur der Tab, der das Meeting gestartet oder die Aufnahme abgespielt hat, spielt ab (sonst doppelt, Test 05.10.).
const RATE = 24000;
const stimme = {
  ctx: null, naechste: 0, quellen: [],
  // aus einem Klick heraus (Autoplay-Regeln); meldet diesen Tab als Lautsprecher. Trägt ein Handy den Ton, gibt
  // der Server ihn nur mit erzwingen (ausdrücklicher Klick „Hier abspielen“) an einen Laptop-Tab.
  bereit(erzwingen = false) {
    this.ctx ??= new AudioContext({ sampleRate: RATE });
    this.ctx.resume();
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ lautsprecher: true, erzwingen }));
    lautsprecher = true;
  },
  abspielen(b64) {
    if (!this.ctx) return;
    const roh = atob(b64), n = roh.length >> 1;
    const puffer = this.ctx.createBuffer(1, n, RATE), d = puffer.getChannelData(0);
    for (let i = 0; i < n; i++) {
      let v = roh.charCodeAt(2 * i) | (roh.charCodeAt(2 * i + 1) << 8);
      if (v >= 32768) v -= 65536;
      d[i] = v / 32768;
    }
    const q = this.ctx.createBufferSource();
    q.buffer = puffer; q.connect(this.ctx.destination);
    const t = Math.max(this.ctx.currentTime + 0.05, this.naechste);
    q.start(t); this.naechste = t + puffer.duration;
    this.quellen.push(q);
    q.onended = () => { this.quellen = this.quellen.filter((x) => x !== q); };
  },
  stopp() { this.quellen.forEach((q) => { try { q.stop(); } catch { /* schon zu Ende */ } }); this.quellen = []; this.naechste = 0; },
};
let lautsprecher = false;

// ---------- Mikrofon: durchgehender Strom, PCM 16 bit, 24 kHz, mono ----------
const WORKLET = `class Sammler extends AudioWorkletProcessor {
  process(inputs) { const k = inputs[0] && inputs[0][0]; if (k) this.port.postMessage(k.slice(0)); return true; }
} registerProcessor("sammler", Sammler);`;
const PAKET = 2400; // 100 ms
const wsBasis = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
// Ein Mikrofon zur Zeit: der Server schließt die alte Quelle mit 4001, wenn eine andere (Laptop/Handy) übernimmt.
const mikro = {
  ctx: null, stream: null, ws: null, puffer: new Int16Array(PAKET), n: 0,
  faktor: 1, pos: 0, pegel: 0, quelle: null,
  beiEnde: null, // (grund) => …  "uebernommen" | "getrennt" | "mikro" – nur bei Ende ohne stoppen()
  async starten(echo, quelle = "laptop") {
    this.quelle = quelle;
    this.ws = new WebSocket(`${wsBasis()}/ws/audio?quelle=${quelle}`);
    this.ws.binaryType = "arraybuffer";
    await new Promise((ok, fehler) => { this.ws.onopen = ok; this.ws.onerror = () => fehler(new Error("Server nicht erreichbar")); });
    this.ws.onclose = (e) => { if (this.stream) this.beiEnde?.(e.code === 4001 ? "uebernommen" : "getrennt"); };
    // Raum statt Nahbesprechung: Filter aus – mit Nestor aber Echo-Unterdrückung an, damit er sich nicht selbst hört
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: echo, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    this.stream.getAudioTracks()[0].onended = () => { if (this.stream) this.beiEnde?.("mikro"); };
    let quelleKnoten;
    try { // 24 kHz direkt; Browser, die Mikrofon und Kontext nicht umrechnen (Firefox), bekommen die Gerätefrequenz
      this.ctx = new AudioContext({ sampleRate: RATE });
      quelleKnoten = this.ctx.createMediaStreamSource(this.stream);
    } catch {
      await this.ctx?.close();
      this.ctx = new AudioContext();
      quelleKnoten = this.ctx.createMediaStreamSource(this.stream);
    }
    this.faktor = this.ctx.sampleRate / RATE; this.pos = 0;
    await this.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    const knoten = new AudioWorkletNode(this.ctx, "sammler");
    const leise = this.ctx.createGain(); leise.gain.value = 0;
    quelleKnoten.connect(knoten); knoten.connect(leise); leise.connect(this.ctx.destination);
    knoten.port.onmessage = (e) => this.daten(e.data);
  },
  daten(f) {
    let spitze = 0;
    // auf 24 kHz umrechnen (linear); bei 24-kHz-Kontext ist faktor 1 und jeder Wert wird genommen
    let p = this.pos;
    for (; p < f.length; p += this.faktor) {
      const i = Math.floor(p), a = f[i], b = f[i + 1] ?? a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * (p - i)));
      spitze = Math.max(spitze, Math.abs(v));
      this.puffer[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === PAKET) {
        if (halten.teile) halten.teile.push(this.puffer.slice()); // „Nestor fragen“ wird gehalten: mitschneiden
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(this.puffer.slice().buffer);
        this.n = 0;
      }
    }
    this.pos = p - f.length;
    this.pegel = Math.max(spitze, this.pegel * 0.85);
  },
  laeuft() { return !!this.stream && this.ws?.readyState === WebSocket.OPEN; },
  async stoppen() {
    const s = this.stream; this.stream = null;
    s?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    this.ws?.close();
    this.ctx = this.ws = this.quelle = null; this.n = 0; this.pegel = 0;
  },
};

// ---------- „Nestor fragen“ halten (Ticket #13) ----------
// Halten, fragen, loslassen: der Ton der Frage geht als WAV an /api/frage/audio. Hört dieses Gerät ohnehin zu, wird
// der laufende Mikrofonstrom mitgeschnitten; sonst öffnet das Halten das Mikrofon nur für die Frage.
const halten = {
  teile: null, eigen: null,
  async start() {
    this.teile = [];
    if (mikro.laeuft()) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    const quelle = ctx.createMediaStreamSource(stream), knoten = new AudioWorkletNode(ctx, "sammler");
    const leise = ctx.createGain(); leise.gain.value = 0;
    quelle.connect(knoten); knoten.connect(leise); leise.connect(ctx.destination);
    const roh = [];
    knoten.port.onmessage = (e) => roh.push(e.data);
    this.eigen = { stream, ctx, roh };
  },
  async ende() {
    const teile = this.teile ?? []; this.teile = null;
    let pcm;
    if (this.eigen) {
      const { stream, ctx, roh } = this.eigen; this.eigen = null;
      stream.getTracks().forEach((t) => t.stop());
      const faktor = ctx.sampleRate / RATE; await ctx.close();
      const n = roh.reduce((a, f) => a + f.length, 0), alle = new Float32Array(n);
      let o = 0; for (const f of roh) { alle.set(f, o); o += f.length; }
      pcm = new Int16Array(Math.floor(n / faktor));
      for (let i = 0; i < pcm.length; i++) {
        const p = i * faktor, j = Math.floor(p), a = alle[j], b = alle[j + 1] ?? a;
        const v = Math.max(-1, Math.min(1, a + (b - a) * (p - j)));
        pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
    } else {
      pcm = new Int16Array(teile.reduce((a, t) => a + t.length, 0));
      let o = 0; for (const t of teile) { pcm.set(t, o); o += t.length; }
    }
    return wavAus(pcm);
  },
};
function wavAus(pcm) { // PCM 16 bit, 24 kHz, mono → WAV
  const b = new ArrayBuffer(44 + pcm.length * 2), d = new DataView(b);
  const text = (o, s) => { for (let i = 0; i < s.length; i++) d.setUint8(o + i, s.charCodeAt(i)); };
  text(0, "RIFF"); d.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVE"); text(12, "fmt ");
  d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true); d.setUint32(24, RATE, true);
  d.setUint32(28, RATE * 2, true); d.setUint16(32, 2, true); d.setUint16(34, 16, true); text(36, "data");
  d.setUint32(40, pcm.length * 2, true);
  new Int16Array(b, 44).set(pcm);
  return b;
}

const KARTEN_ART = { antwort: "Nestor antwortet", recherche: "Recherche", folie: "Folie", stand: "Wo stehen wir?",
  regeln: "Regeln", protokoll: "Protokoll", ueberblick: "Überblick" };
const KARTEN_ICON = { antwort: "frage", recherche: "suche", folie: "folie" };
const NESTOR_TEXT = {
  bereit: "hört zu", angesprochen: "hört dir zu …", denkt: "denkt nach …", spricht: "spricht",
  begruessung: "begrüßt die Runde", einwand: "wartet auf ein Nein …", pausiert: "hört nicht mit",
  recherchiert: "recherchiert …", gespraech: "im Gespräch",
};
