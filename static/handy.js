"use strict";

// Handy: Mikrofon und Fernbedienung für das laufende Meeting. Keine eigenen Funktionen – dieselben Knöpfe und
// Listen wie am Dashboard, für den Daumen. Lehren aus Teachbuddy/xbuddy: Wake Lock nach jedem Verdecken neu,
// AudioContext immer wieder aufwecken, ein verlorenes Mikrofon sichtbar melden statt es für Stille zu halten.

let reiter = "transkript";
let mikroGewollt = false;   // der Mensch will, dass dieses Handy zuhört – bei Abriss neu verbinden
let laufzeit = null;        // ms Hin und zurück zum Laptop
let wachSperre = null;
let wachStand = "";         // "an" | "fehlt" | "aus"

// ---------- Kopplung ----------
async function pruefen() {
  const r = await fetch("/api/zustand");
  if (r.status === 401) return koppelnZeigen();
  $("koppeln").hidden = true; $("app").hidden = false;
  zustand = await r.json(); rendern();
  verbinden();
}
function koppelnZeigen() {
  $("koppeln").hidden = false; $("app").hidden = true;
  $("status").textContent = "Nicht gekoppelt"; $("status").className = "pill";
  $("koppeln-falsch").hidden = !new URLSearchParams(location.search).has("falsch");
}
$("koppeln-form").onsubmit = (e) => {
  e.preventDefault();
  location.href = `/handy?k=${encodeURIComponent($("koppeln-code").value)}`;
};

// ---------- Verbindung ----------
function verbinden() {
  ws = new WebSocket(`${wsBasis()}/ws?geraet=handy`);
  ws.onopen = () => { if (lautsprecher) ws.send(JSON.stringify({ lautsprecher: true })); ping(); };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.typ === "stimme") return lautsprecher && stimme.abspielen(d.pcm);
    if (d.typ === "stimme_stopp") return stimme.stopp();
    if (d.typ === "nestor_text") return handyText(d); // was Nestor gerade sagt – kurz unter der Sprechtaste
    if (d.typ === "pong") { laufzeit = Math.round(performance.now() - d.t); return chipsRendern(); }
    zustand = d; rendern();
  };
  ws.onclose = (e) => {
    if (e.code === 4401) return koppelnZeigen();
    $("status").textContent = "Getrennt"; $("status").className = "pill stumm"; laufzeit = null;
    setTimeout(verbinden, 1000);
  };
}
function ping() { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ ping: performance.now(), laufzeit })); }
setInterval(ping, 5000);

// ---------- Mikrofon ----------
async function mikroStarten() {
  stimme.bereit(); // aus dem Tipp heraus – sonst darf das Handy keinen Ton abspielen
  try {
    await mikro.starten(zustand?.einstellungen?.assistent ?? true, "handy");
    mikroGewollt = true;
    wachHalten();
  } catch (e) {
    mikroGewollt = false;
    alert(window.isSecureContext ? `Mikrofon nicht verfügbar: ${e.message ?? e}`
      : "Das Mikrofon geht nur über HTTPS – die Adresse aus dem QR-Code verwenden (https://…ts.net).");
  }
  rendern();
}
async function mikroStoppen() { mikroGewollt = false; await mikro.stoppen(); rendern(); }
mikro.beiEnde = async (grund) => {
  await mikro.stoppen();
  if (grund === "uebernommen") { mikroGewollt = false; hinweisLokal("Der Laptop hört jetzt zu."); }
  else if (mikroGewollt) setTimeout(() => { if (mikroGewollt && !mikro.laeuft() && !document.hidden) mikroNeu(); }, 1500);
  rendern();
};
async function mikroNeu() { // nach Abriss oder Sperre: still neu verbinden, ohne neuen Tipp (Mikrofon ist erlaubt)
  try { await mikro.starten(zustand?.einstellungen?.assistent ?? true, "handy"); } catch { /* nächster Versuch beim Sichtbarwerden */ }
  rendern();
}
$("btn-mikro").onclick = () => (mikro.laeuft() ? mikroStoppen() : mikroStarten());

// ---------- Display wach halten ----------
// Ein Wake Lock überlebt das Verdecken nicht – bei jedem Sichtbarwerden neu anfordern; Zustand sichtbar machen.
async function wachHalten() {
  if (!("wakeLock" in navigator)) { wachStand = "fehlt"; return chipsRendern(); }
  if (document.hidden || wachSperre) return;
  try {
    wachSperre = await navigator.wakeLock.request("screen");
    wachStand = "an";
    wachSperre.addEventListener("release", () => { wachSperre = null; wachStand = "aus"; chipsRendern(); });
  } catch { wachStand = "aus"; }
  chipsRendern();
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (mikro.laeuft() || mikroGewollt || zustand?.hoeren) wachHalten();
  stimme.ctx?.resume(); mikro.ctx?.resume();
  if (mikroGewollt && !mikro.laeuft()) mikroNeu();
  ping();
});
// Android startet AudioContexts gern angehalten; Pegel und Ausgabe immer wieder aufwecken
setInterval(() => { if (mikro.ctx?.state === "suspended") mikro.ctx.resume(); if (stimme.ctx?.state === "suspended") stimme.ctx.resume(); }, 1000);

// ---------- Knöpfe ----------
// nur das zuhörende Handy übernimmt die Stimme – ein zweites Handy als reine Fernbedienung nimmt sie nicht weg
// Sprechtaste (Ticket #13/#27): halten, fragen, loslassen → ein Antwortbogen wie bei „Nestor, …“; drücken unterbricht
// Nestor. In Basis der einzige Weg (Funkgerät), in Premium die Alternative zum Namen. Mit „Nur auf Knopfdruck“ kommt
// die Antwort als Karte. Was beim Halten gesagt wird, wertet der Server nicht noch einmal als Zuruf.
let haelt = false;
async function haltenAn(e) {
  e.preventDefault();
  if (haelt || $("btn-fragen").disabled) return;
  haelt = true;
  $("btn-fragen").classList.add("haelt"); $("fragen-text").textContent = "Ich höre … loslassen zum Senden";
  if (mikro.laeuft()) stimme.bereit();
  stimme.stopp(); // die Taste unterbricht Nestor
  try {
    await halten.start();
    await fetch("/api/frage/halten", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ an: true }) });
  } catch (err) {
    haelt = false; halten.teile = null; haltenText();
    hinweisLokal(`Mikrofon nicht verfügbar: ${err.message ?? err}`);
  }
}
function haltenText() {
  $("btn-fragen").classList.remove("haelt"); $("fragen-text").textContent = "Sprechtaste – halten und sprechen";
}
async function haltenAus() {
  if (!haelt) return;
  haelt = false; haltenText();
  const wav = await halten.ende();
  if (wav.byteLength < 44 + RATE * 2 * 0.5) { // unter einer halben Sekunde: versehentlich getippt
    fetch("/api/frage/halten", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ an: false }) });
    return hinweisLokal("Zum Fragen gedrückt halten, sprechen, dann loslassen.");
  }
  $("knopf-stand").hidden = false; $("knopf-stand").textContent = "Nestor hört die Frage …";
  try {
    const r = await fetch("/api/frage/audio", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
    const d = await r.json().catch(() => ({}));
    $("knopf-stand").textContent = !r.ok ? (d.detail ?? `Fehler ${r.status}`) : !d.ok ? d.grund : `„${d.frage}“`;
  } catch {
    $("knopf-stand").textContent = "Laptop nicht erreichbar.";
  }
  setTimeout(() => { $("knopf-stand").hidden = true; }, 8000);
}
$("btn-fragen").addEventListener("pointerdown", haltenAn);
for (const ev of ["pointerup", "pointercancel", "pointerleave"]) $("btn-fragen").addEventListener(ev, haltenAus);
$("btn-fragen").addEventListener("contextmenu", (e) => e.preventDefault());
document.querySelectorAll(".h-knopf").forEach((b) => { b.onclick = () => { stimme.bereit(); api(`/api/knopf/${b.dataset.knopf}`); }; });
$("btn-still").onclick = () => { stimme.stopp(); api("/api/assistent/stopp"); };
$("btn-fortsetzen").onclick = () => api("/api/assistent/fortsetzen");
$("btn-ton-hier").onclick = () => stimme.bereit();
$("btn-stumm").onclick = () => api("/api/stumm", { an: !zustand?.stumm });
$("btn-start").onclick = async () => {
  if (!mikro.laeuft()) await mikroStarten(); // erst melden, dann starten – der Laptop hält sich dann raus
  await api("/api/start");
};
$("btn-stopp").onclick = async () => {
  if (!confirm("Meeting beenden? Danach entstehen Zusammenfassung und Abschlussbild am Laptop.")) return;
  await mikroStoppen();
  await api("/api/stopp");
};
for (const r of ["hinweise", "transkript"]) $(`r-${r}`).onclick = () => { reiter = r; rendern(); };

// Was Nestor gerade sagt (nestor_text), kurz unter der Sprechtaste
let gesagt = { text: "", seit: 0 };
function handyText(d) {
  gesagt.text = d.neu ? d.text : gesagt.text + (d.delta ? d.text : ` ${d.text}`);
  gesagt.seit = Date.now();
  $("gesagt").hidden = false; $("gesagt").textContent = gesagt.text;
}
setInterval(() => { if (!$("gesagt").hidden && Date.now() - gesagt.seit > 12000) $("gesagt").hidden = true; }, 1000);

// ---------- Installieren ----------
let installieren = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installieren = e; $("btn-installieren").hidden = false; });
$("btn-installieren").onclick = async () => { await installieren?.prompt(); installieren = null; $("btn-installieren").hidden = true; };
const alsApp = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
$("ios-installieren").hidden = alsApp || !/iPhone|iPad/.test(navigator.userAgent);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/handy" }).catch(() => {});

// ---------- Darstellung ----------
let lokalerHinweis = null;
function hinweisLokal(text) { lokalerHinweis = { text, bis: Date.now() + 6000 }; rendern(); }

function chipsRendern() {
  $("wach").textContent = { an: "Display bleibt an", aus: "Display kann ausgehen", fehlt: "Display-Timeout hochsetzen" }[wachStand] ?? "";
  $("wach").className = `chip ${wachStand === "an" ? "gut" : wachStand ? "warn" : ""}`;
  $("wach").hidden = !wachStand;
  $("laufzeit").textContent = laufzeit === null ? "–" : `${laufzeit} ms`;
  $("laufzeit").className = `chip ${laufzeit === null ? "" : laufzeit < 80 ? "gut" : laufzeit < 250 ? "warn" : "schlecht"}`;
  $("laufzeit").title = "Laufzeit zum Laptop, hin und zurück";
}

function rendern() {
  const z = zustand; if (!z) return;
  const aktiv = z.laeuft || z.simulation || z.hoeren;
  const beendet = !aktiv && z.segmente.length > 0;
  const m = z.mikro ?? {};
  $("titel").textContent = z.titel || "Nestor";
  $("untertitel-kopf").textContent = z.ziel || "Meeting-Coach";
  const pill = $("status");
  pill.className = "pill" + (z.stumm ? " stumm" : z.hoeren ? " live" : "");
  pill.textContent = z.stumm ? "Stumm" : z.simulation && z.hoeren ? "Wiedergabe" : z.hoeren ? "Live" : beendet ? "Beendet" : "Mit Laptop verbunden";
  if (!z.stumm && !z.hoeren) pill.className = "pill verbunden";
  $("zeit").textContent = mmss(z.zeit);
  $("aufnahme").hidden = !(z.archiv?.aufnahme && z.hoeren);

  // Warnung: Mikrofon weg, eigener Hinweis oder Fehler vom Server
  const eigenesWeg = mikroGewollt && !mikro.laeuft();
  const warnung = lokalerHinweis && Date.now() < lokalerHinweis.bis ? lokalerHinweis.text
    : eigenesWeg ? "Mikrofon unterbrochen – verbinde neu …"
    : m.weg ? (m.quelle ? `Seit ${Math.round(m.luecke)} s kein Ton vom ${m.quelle === "handy" ? "Handy" : "Laptop"}.` : "Kein Mikrofon verbunden – Nestor hört nichts.")
    : z.fehler ?? null;
  $("warnung").hidden = !warnung; $("warnung").textContent = warnung ?? "";
  $("ton-fehlt").hidden = !(z.hoeren && z.assistent?.aktiv && !z.lautsprecher);

  // Band (Ticket #27)
  bandRendern(z, $("band"));

  // Nestor
  const a = z.assistent;
  const nestorDa = a?.aktiv && z.hoeren;
  $("nestor").className = `nestor ${nestorDa ? a.zustand : "pausiert"}`;
  $("nestor-zustand").textContent = nestorDa ? `${a.name} ${NESTOR_TEXT[a.zustand] ?? a.zustand}` : z.hoeren ? "Nestor ist aus" : "Nestor wartet aufs Meeting";
  // Knöpfe: in beiden Stufen; „Nestor fragen“ auch bei „Nur auf Knopfdruck“ (dann ohne Stimme, als Karte)
  const nurKnopf = z.modus === "knopfdruck";
  const fragenDa = z.hoeren && (nurKnopf || (a?.aktiv && a.zustand !== "pausiert"));
  $("btn-fragen").disabled = !fragenDa && !haelt;
  const bogen = !nurKnopf && a?.bogen;
  document.querySelectorAll(".h-knopf").forEach((b) => {
    b.disabled = !z.hoeren || !!z.knopf?.laeuft || !!bogen;
    if (b.dataset.knopf === "bild") b.hidden = z.stufe === "basis"; // Basis: kein Bildmodell
    if (["zusammenfassen", "fehlt"].includes(b.dataset.knopf)) b.hidden = nurKnopf;
  });
  if (bogen) { $("knopf-stand").hidden = false; $("knopf-stand").textContent = `Nestor ist bei „${bogen.name}“ …`; }
  else if (z.knopf?.laeuft) { $("knopf-stand").hidden = false; $("knopf-stand").textContent = "Nestor arbeitet …"; }
  else if (z.knopf?.fehler) { $("knopf-stand").hidden = false; $("knopf-stand").textContent = z.knopf.fehler; }
  $("btn-still").hidden = !nestorDa || !["spricht", "denkt", "recherchiert", "gespraech", "begruessung"].includes(a.zustand);
  $("btn-fortsetzen").hidden = !nestorDa || a.zustand !== "pausiert";

  // Mikrofon
  const hier = mikro.laeuft();
  $("btn-mikro").classList.toggle("an", hier);
  $("btn-mikro").querySelector(".i").replaceChildren(icon(hier ? "mikro" : "mikroAus"));
  $("mikro-text").textContent = !hier ? "Dieses Handy übernimmt Mikro und Ton"
    : z.hoeren ? "Handy hört zu – tippen zum Beenden" : "Bereit – hört zu, sobald das Meeting startet";
  $("quelle").textContent = !z.hoeren && !m.quelle ? "" : m.quelle === "handy" ? (hier ? "dieses Handy" : "ein anderes Handy")
    : m.quelle === "laptop" ? "Laptop hört zu" : "niemand hört zu";
  $("btn-stumm").hidden = !z.hoeren;
  $("btn-stumm").textContent = z.stumm ? "Stumm aus – wieder zuhören" : "Stumm schalten";

  // Meeting
  $("btn-start").hidden = aktiv;
  $("btn-stopp").hidden = !z.hoeren || z.simulation;
  $("meeting-text").textContent = aktiv ? "" : beendet ? "Meeting beendet – Zusammenfassung am Laptop. Neues Meeting dort einrichten."
    : "Agenda und Personen am Laptop einrichten; starten geht auch hier.";

  // Verlauf (Ticket #27): dieselben Karten wie im Dashboard, wischen zum Blättern
  verlaufRendern(z);
  for (const r of ["hinweise", "transkript"]) { $(`r-${r}`).classList.toggle("aktiv", reiter === r); $(`l-${r}`).hidden = reiter !== r; }
  $("l-hinweise").replaceChildren(...(z.hinweise.length ? [...z.hinweise].reverse().map((x) =>
    el("li", { class: x.art === "ton" || x.stufe === "warnung" ? "rot" : "" }, el("span", { class: "wann" }, mmss(x.zeit)), x.text))
    : [el("li", { class: "leer" }, "Noch keine Hinweise.")]));
  if (reiter === "transkript") {
    const tr = $("l-transkript");
    const unten = tr.scrollTop + tr.clientHeight >= tr.scrollHeight - 20;
    const zeilen = z.segmente.slice(-80).map((s) => el("li", {}, el("span", { class: "wann" }, mmss(s.start)),
      el("strong", {}, s.sprecher), " ", s.text));
    if (z.teiltext) zeilen.push(el("li", { class: "teiltext" }, el("span", { class: "wann" }, "live"), z.teiltext));
    tr.replaceChildren(...(zeilen.length ? zeilen : [el("li", { class: "leer" }, "Noch nichts gesagt.")]));
    if (unten) tr.scrollTop = tr.scrollHeight;
  }
  if (aktiv || hier) wachHalten();
  chipsRendern();
}

// Pegel flüssig, unabhängig vom Serverstand
(function pegel() { $("pegel").style.width = `${Math.min(100, Math.round(mikro.pegel * 140))}%`; requestAnimationFrame(pegel); })();

// Start
verlaufVerdrahten({ buehne: $("vl-buehne"), zaehler: $("vl-zaehler"), zurueck: $("vl-zurueck"), vor: $("vl-vor"), neu: $("vl-neu") });
document.querySelector("#btn-fragen .i").replaceChildren(icon("mikro"));
document.querySelector("#btn-still .i").replaceChildren(icon("stopp"));
document.querySelector("#btn-fortsetzen .i").replaceChildren(icon("weiter"));
pruefen().catch(() => { $("status").textContent = "Laptop nicht erreichbar"; setTimeout(() => location.reload(), 5000); });
