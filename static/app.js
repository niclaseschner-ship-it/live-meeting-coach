"use strict";

// ---------- Vorbereitung ----------
let regelkatalog = [];
function punktZeile(p = {}) {
  const z = el("div", { class: "f-punkt" },
    el("input", { placeholder: "Titel", value: p.titel ?? "" }),
    el("input", { placeholder: "Frage / Ziel des Punkts", value: p.ziel ?? "" }),
    el("input", { type: "number", min: "1", value: p.minuten ?? 10, title: "Minuten" }),
    el("button", { class: "icon klein", "data-tip": "Punkt entfernen", onclick: () => z.remove() }, icon("zu")));
  $("f-agenda").append(z);
}
function personZeile(name = "") {
  const z = el("div", { class: "f-person" }, el("input", { placeholder: "Name", value: name }),
    el("button", { class: "icon klein", "data-tip": "Person entfernen", onclick: () => z.remove() }, icon("zu")));
  $("f-teilnehmende").append(z);
}
function regelwahl(standard) {
  $("f-regelwahl").replaceChildren(...regelkatalog.map((r) => el("label",
    { class: `regel${r.umgesetzt ? "" : " folgt"}`, "data-tip": r.umgesetzt ? r.beobachtet : "folgt in einer späteren Ausbaustufe" },
    el("input", { type: "checkbox", value: r.id, ...(standard.includes(r.id) && r.umgesetzt ? { checked: "" } : {}),
      ...(r.umgesetzt ? {} : { disabled: "" }) }),
    el("span", { class: "r-icon" }, icon(r.id)),
    el("span", {}, r.titel.split(" – ")[0]),
    el("span", { class: "r-stufe" }, r.umgesetzt ? r.stufe_text : "folgt"))));
}
// Eine Seite, ein Stand: Das Formular übernimmt, was auf dem Server eingerichtet ist (anderer Tab, anderes Gerät),
// solange hier niemand gerade tippt.
let formStand = null;
function formAusServer(z) {
  if (!z.agenda?.length) return;
  const stand = JSON.stringify([z.titel, z.ziel, z.agenda.map((p) => [p.titel, p.ziel, p.minuten]), z.teilnehmende, z.regel_ids]);
  if (stand === formStand || $("einrichtung").contains(document.activeElement)) return;
  formStand = stand;
  $("f-titel").value = z.titel ?? ""; $("f-ziel").value = z.ziel ?? "";
  $("f-agenda").replaceChildren(); z.agenda.forEach((p) => punktZeile(p));
  $("f-teilnehmende").replaceChildren(); (z.teilnehmende.length ? z.teilnehmende : ["", ""]).forEach((n) => personZeile(n));
  if (regelkatalog.length && z.regel_ids) regelwahl(z.regel_ids);
}
function formularDaten() {
  return {
    titel: $("f-titel").value,
    ziel: $("f-ziel").value,
    agenda: [...$("f-agenda").children].map((z) => {
      const [t, g, m] = z.querySelectorAll("input");
      return { titel: t.value, ziel: g.value, minuten: Number(m.value) || 10 };
    }),
    regeln: $("f-regeln").value.split("\n"),
    regel_ids: [...$("f-regelwahl").querySelectorAll("input:checked")].map((i) => i.value),
    assistent: $("f-assistent").checked,
    teilnehmende: [...$("f-teilnehmende").querySelectorAll("input")].map((i) => i.value),
  };
}
const einrichten = () => api("/api/einrichten", formularDaten());

// ---------- Knöpfe ----------
let einrichtungOffen = false;
let leisteOffen = false;
let reiter = "transkript";
let hinweisWeg = 0; // id des zuletzt weggeklickten Hinweises

$("btn-punkt-neu").onclick = () => punktZeile();
$("btn-person-neu").onclick = () => personZeile();
$("btn-simulation").onclick = async () => { await einrichten(); api("/api/simulation", { name: $("f-szenario").value, tempo: 10 }); };
$("btn-abspielen").onclick = () => { stimme.bereit(); api("/api/abspielen", { name: $("f-aufnahme").value, tempo: 1, auto_wechsel: $("f-auto").checked }); };
$("btn-start").onclick = async () => {
  stimme.bereit();
  await einrichten();
  await api("/api/start");
  if (zustand?.mikro?.quelle === "handy") return; // gemeldetes Handy trägt Mikro und Ton
  try { await mikro.starten($("f-assistent").checked); } catch (e) { alert(`Mikrofon nicht verfügbar: ${e}`); await api("/api/stopp"); }
};
$("btn-stopp").onclick = async () => { await mikro.stoppen(); await api("/api/stopp"); location.href = "/abschluss"; };
$("btn-neu").onclick = () => { einrichtungOffen = true; rendern(); window.scrollTo(0, 0); };
$("btn-mikro").onclick = () => api("/api/stumm", { an: !zustand?.stumm });
$("btn-fragen").onclick = () => { stimme.bereit(); api("/api/assistent/fragen"); };
$("btn-still").onclick = () => { stimme.stopp(); api("/api/assistent/stopp"); };
$("btn-fortsetzen").onclick = () => api("/api/assistent/fortsetzen");
$("btn-transkript").onclick = () => { leisteOffen = !leisteOffen; rendern(); };
$("leiste-zu").onclick = () => { leisteOffen = false; rendern(); };
$("reiter-transkript").onclick = () => { reiter = "transkript"; rendern(); };
$("reiter-hinweise").onclick = () => { reiter = "hinweise"; rendern(); };
$("reiter-nestor").onclick = () => { reiter = "nestor"; rendern(); };
$("karte-zu").onclick = () => karteSchliessen();
$("btn-einstellungen").onclick = () => { $("einstellungen").hidden = !$("einstellungen").hidden; $("kosten").hidden = $("handy-fenster").hidden = true; };
$("btn-kosten").onclick = () => { $("kosten").hidden = !$("kosten").hidden; $("einstellungen").hidden = true; if (zustand) kostenRendern(zustand); };
$("btn-schluessel").onclick = (e) => { e.stopPropagation(); $("einstellungen").hidden = false; $("s-eingabe").focus(); };
$("hinweis-zu").onclick = () => { hinweisWeg = zustand?.hinweise.at(-1)?.id ?? 0; rendern(); };
$("btn-bild").onclick = () => api("/api/onepager");
$("btn-folie").onclick = () => api("/api/folie");
$("tab-bild").onclick = () => { ansicht = "bild"; if (zustand) bildRendern(zustand); };
$("tab-folie").onclick = () => { ansicht = "folie"; if (zustand) bildRendern(zustand); };
$("btn-bild-png").onclick = () => bildAlsPng();
// Handy koppeln: QR-Code mit Kopplungscode; das Handy kann dann das Mikrofon übernehmen
let kopplungGeladen = false;
async function handyFensterZeigen() {
  $("handy-fenster").hidden = !$("handy-fenster").hidden; $("einstellungen").hidden = $("kosten").hidden = true;
  if ($("handy-fenster").hidden || kopplungGeladen) return;
  const k = await fetch("/api/kopplung").then((r) => r.json());
  kopplungGeladen = !!k.adresse; // ohne Freigabe beim nächsten Öffnen erneut nachsehen
  $("hf-code").textContent = k.code.replace(/(.{4})/, "$1-");
  $("hf-qr").innerHTML = k.qr ?? "";
  $("hf-text").replaceChildren(...(k.adresse ? ["Adresse: ", el("strong", {}, k.adresse)]
    : ["Kein Tailscale gefunden. HTTPS ist Pflicht fürs Handy-Mikrofon: ", el("code", {}, k.befehl),
      " einrichten oder LMC_HANDY_URL setzen."]));
}
$("btn-handy").onclick = handyFensterZeigen;
$("btn-ton-hier").onclick = () => stimme.bereit(true);
$("btn-mikro-quelle").onclick = handyFensterZeigen;
$("hf-laptop").onclick = async () => {
  stimme.bereit(true);
  try { await mikro.starten(zustand?.einstellungen?.assistent ?? true, "laptop"); } catch (e) { alert(`Mikrofon nicht verfügbar: ${e}`); }
};
// Laptop-Mikro endet ohne eigenes Stoppen: Handy hat übernommen oder die Verbindung riss ab
mikro.beiEnde = (grund) => { mikro.stoppen(); if (grund !== "uebernommen") console.warn("Laptop-Mikrofon beendet:", grund); };
document.addEventListener("click", (e) => {
  if (!$("handy-fenster").hidden && !$("handy-fenster").contains(e.target) && !$("btn-handy").contains(e.target)
      && !$("btn-mikro-quelle").contains(e.target)) $("handy-fenster").hidden = true;
  if (!$("einstellungen").hidden && !$("einstellungen").contains(e.target) && !$("btn-einstellungen").contains(e.target)) $("einstellungen").hidden = true;
  if (!$("kosten").hidden && !$("kosten").contains(e.target) && !$("btn-kosten").contains(e.target)) $("kosten").hidden = true;
});
// Einstellungen: jede Änderung sofort an den Server
const einstellen = (feld, wert) => api("/api/einstellungen", { [feld]: wert });
$("e-assistent").onchange = (e) => einstellen("assistent", e.target.checked);
$("e-modus").onchange = (e) => einstellen("modus", e.target.value);
$("e-stimme").onchange = (e) => einstellen("stimme", e.target.value);
$("e-bild").onchange = (e) => einstellen("bild_minuten", Number(e.target.value));
$("e-monolog").onchange = (e) => einstellen("monolog_sekunden", Number(e.target.value));
$("e-bild-anbieter").onchange = (e) => einstellen("bild_anbieter", e.target.value);
$("e-aufnahme").onchange = (e) => einstellen("aufnahme", e.target.checked);
$("btn-ablage").onclick = () => api("/api/ablage/oeffnen");
$("e-live-art").onchange = (e) => { $("e-live-hinweis").hidden = e.target.value !== "sparsam"; einstellen("live_art", e.target.value); };

// OpenAI-Schlüssel: geht nur an den eigenen Server (läuft auf diesem Rechner) und kommt nie zurück
async function schluesselSenden(wert) {
  const m = $("s-meldung");
  m.hidden = false; m.className = "s-meldung"; m.textContent = wert ? "Prüfe bei OpenAI …" : "Entferne …";
  $("s-speichern").disabled = true;
  try {
    const r = await fetch("/api/schluessel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schluessel: wert }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { m.textContent = d.detail ?? `Fehler ${r.status}`; return; }
    $("s-eingabe").value = "";
    m.className = "s-meldung ok"; m.textContent = wert ? "Schlüssel funktioniert und ist gespeichert." : "Entfernt.";
  } finally { $("s-speichern").disabled = false; }
}
$("s-speichern").onclick = () => { const v = $("s-eingabe").value.trim(); if (v) schluesselSenden(v); };
$("s-eingabe").onkeydown = (e) => { if (e.key === "Enter") $("s-speichern").click(); };
$("s-entfernen").onclick = () => schluesselSenden("");

function schluesselRendern(z) {
  const s = z.schluessel ?? {};
  $("schluessel-fehlt").hidden = !!s.vorhanden || !!s.offline;
  $("s-status").textContent = s.offline ? "Offline-Modus (LMC_OFFLINE=1): keine KI-Aufrufe."
    : !s.vorhanden ? "Noch kein Schlüssel – nur Demos möglich."
    : s.quelle === "dashboard" ? `Eingetragen (…${s.ende ?? ""}), gilt für alle Funktionen.`
    : `Aus der Datei .env (…${s.ende ?? ""}). Ein hier eingetragener Schlüssel hat Vorrang.`;
  $("s-entfernen").hidden = s.quelle !== "dashboard";
}

// ---------- Kosten ----------
const dollar = (v, stellen = 2) => `${(v ?? 0).toLocaleString("de-DE", { minimumFractionDigits: stellen, maximumFractionDigits: stellen })} $`;
function kostenRendern(z) {
  const k = z.kosten; if (!k) return;
  $("kosten-wert").textContent = dollar(k.meeting);
  if ($("kosten").hidden) return;
  $("k-meeting").textContent = dollar(k.meeting);
  const teile = [];
  if (k.pro_stunde != null) teile.push(`≈ ${dollar(k.pro_stunde)} pro Stunde`);
  if (k.hochrechnung != null) teile.push(`ganzes Meeting ≈ ${dollar(k.hochrechnung)}`);
  $("k-rate").textContent = teile.join(" · ") || "dieses Meeting";
  const max = Math.max(...k.bereiche.map((b) => b.usd), 0.0001);
  $("k-bereiche").replaceChildren(...k.bereiche.map((b) => {
    const balken = el("span", { class: "balken" }, el("span"));
    balken.firstChild.style.width = `${(100 * b.usd / max).toFixed(1)}%`;
    return el("li", { class: b.usd ? "" : "null" }, el("span", {}, b.name), el("span", { class: "wert" }, dollar(b.usd, 3)), balken);
  }));
  $("k-heute").textContent = dollar(k.heute);
  $("k-gesamt").textContent = dollar(k.gesamt);
}

// ---------- Live-Bild ----------
let bildVersion = 0;
let ansicht = "bild"; // Live-Bild oder Recherche-Folie
let folieVersion = 0;
function folieBauen(f) {
  const quellen = f.quellen.length ? el("ol", {}, ...f.quellen.map((q) => el("li", {},
    el("a", { href: q.url, target: "_blank", rel: "noopener" }, q.titel), el("small", {}, q.seite))))
    : el("p", {}, "Keine Quellen gemeldet.");
  $("folie").replaceChildren(
    el("div", { class: "folie-kopf" }, el("span", { class: "marke-klein" }, el("i", {}, "N"), "Recherche · Nestor"), el("span", {}, f.datum)),
    el("h3", {}, f.titel),
    el("p", { class: "kern" }, f.kernaussage),
    el("div", { class: "folie-inhalt" },
      el("div", {}, el("ul", { class: "folie-punkte" }, ...f.punkte.map((p) => el("li", {}, p))),
        ...(f.offen ? [el("div", { class: "folie-offen" }, "Offen: ", f.offen)] : [])),
      el("div", { class: "folie-quellen" }, el("h4", {}, "Quellen"), quellen)),
    el("div", { class: "folie-fuss" }, `Frage: „${f.frage}“ · Websuche, Stand ${f.datum} – Angaben ohne Gewähr, Quellen prüfen.`),
  );
}
function bildAlsPng() {
  const img = $("live-bild");
  if (!img.naturalWidth) return;
  const c = document.createElement("canvas");
  c.width = img.naturalWidth * 1.5; c.height = img.naturalHeight * 1.5;
  const g = c.getContext("2d"); g.fillStyle = "#F8FAFC"; g.fillRect(0, 0, c.width, c.height);
  g.drawImage(img, 0, 0, c.width, c.height);
  c.toBlob((blob) => { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `live-bild-${bildVersion}.png`; a.click(); });
}
function bildRendern(z) {
  if (z.onepager_version && z.onepager_version !== bildVersion) {
    bildVersion = z.onepager_version; ansicht = "bild"; // neues Live-Bild wird gezeigt
    const img = $("live-bild");
    img.onload = () => { img.hidden = false; $("bild-leer").hidden = true; $("btn-bild-png").disabled = false; };
    img.src = `${z.onepager_format === "png" ? "/api/onepager.png" : "/api/onepager.svg"}?v=${bildVersion}`;
    $("btn-bild-analyse").hidden = false;
  }
  // Recherche-Folie: neue Folie wird sofort gezeigt; Umschalter, sobald es eine gibt
  if (z.folie && z.folie_version !== folieVersion) { folieVersion = z.folie_version; folieBauen(z.folie); ansicht = "folie"; }
  const folieZeigen = ansicht === "folie" && !!z.folie;
  $("ansicht-wahl").hidden = !z.folie;
  $("bild-titel").hidden = !!z.folie;
  $("tab-bild").classList.toggle("aktiv", !folieZeigen); $("tab-folie").classList.toggle("aktiv", folieZeigen);
  $("folie").hidden = !folieZeigen;
  $("live-bild").style.visibility = folieZeigen ? "hidden" : "";
  $("bild-leer").style.visibility = folieZeigen ? "hidden" : "";
  $("btn-folie").hidden = !z.recherche_da;
  $("btn-folie").disabled = !!z.folie_laeuft;
  $("folie-arbeitet").hidden = !z.folie_laeuft;
  $("bild-arbeitet").hidden = !z.onepager_laeuft;
  if (!bildVersion) platzhalterRendern(z);
  $("btn-bild").disabled = !!z.onepager_laeuft || !z.segmente.length;
  let status = z.onepager_stand != null ? `· Stand ${mmss(z.onepager_stand)}` : "";
  if (z.onepager_fokus) status += ` · Fokus: ${z.onepager_fokus}`;
  $("bild-status").textContent = z.onepager_fehler ? `· ${z.onepager_fehler}` : status;
}

// Platzhalter vor dem ersten Bild: einladend statt leer – zeigt, dass das Bild kommt
const SPRUECHE = [
  "Legt los – Nestor hört zu und zeichnet mit.",
  "Ihr redet, Nestor skizziert.",
  "Jeder Gedanke zählt – hier entsteht euer Meeting-Bild.",
  "Gute Gespräche ergeben gute Bilder. Eures entsteht gerade.",
];
function platzhalterRendern(z) {
  const spruch = !z.segmente.length ? SPRUECHE[0] : SPRUECHE[Math.floor(z.zeit / 60) % SPRUECHE.length];
  $("bild-spruch").textContent = z.onepager_laeuft ? "Nestor zeichnet euer erstes Bild …" : spruch;
  const takt = (z.onepager_minuten ?? 0) * 60;
  const weg = takt ? Math.min(1, z.zeit / takt) : 0;
  $("bild-weg").style.width = `${z.onepager_laeuft ? 100 : Math.round(weg * 100)}%`;
  $("bild-weg").parentElement.hidden = !takt;
  const rest = Math.ceil((takt - z.zeit) / 60);
  $("bild-wann").textContent = z.onepager_laeuft ? "gleich da – ca. 1 Minute"
    : !takt ? "Das Bild entsteht, sobald ihr es euch wünscht."
    : !z.segmente.length ? `Das erste Bild kommt nach ${Math.round(takt / 60)} Minuten Gespräch.`
    : rest > 1 ? `Das erste Bild kommt in ca. ${rest} Minuten.` : "Das erste Bild kommt gleich.";
}

// ---------- Nestor-Karten (Pop-up) ----------
let karteOffen = null;      // id der gezeigten Karte
let karteGesehen = null;    // höchste id, die schon automatisch gezeigt wurde
let karteTimer = null;
function karteZeigen(k, automatisch) {
  karteOffen = k.id;
  $("karte-art").textContent = KARTEN_ART[k.art] ?? "Nestor";
  $("karte-zeit").textContent = mmss(k.zeit);
  $("karte-titel").textContent = k.titel;
  $("karte-frage").textContent = k.frage && k.frage !== k.titel ? `„${k.frage}“` : "";
  $("karte-frage").hidden = !$("karte-frage").textContent;
  $("karte-punkte").replaceChildren(...(k.punkte ?? []).map((p) => el("li", {}, p)));
  const q = k.quellen ?? [];
  $("karte-quellen").hidden = !q.length;
  $("karte-quellen").replaceChildren(el("strong", {}, "Quellen"), ...q.map((x) => el("div", {},
    el("a", { href: x.url, target: "_blank", rel: "noopener" }, x.titel), " ", el("small", {}, x.seite))));
  $("karte-folie").hidden = k.art !== "folie";
  $("karte-folie").onclick = () => { folieBauen(k.folie); ansicht = "folie"; karteSchliessen(); if (zustand) bildRendern(zustand); };
  $("karte").hidden = false;
  clearTimeout(karteTimer);
  // automatisch geöffnete Karten treten nach einer Minute zurück in den Verlauf; selbst geöffnete bleiben
  if (automatisch) karteTimer = setTimeout(karteSchliessen, 60000);
}
function karteSchliessen() { $("karte").hidden = true; karteOffen = null; clearTimeout(karteTimer); }
function kartenRendern(z) {
  const karten = z.karten ?? [];
  const neueste = karten.at(-1);
  if (karteGesehen === null) { karteGesehen = neueste?.id ?? 0; return; } // beim Laden keine alten Karten aufpoppen
  if (neueste && neueste.id > karteGesehen) {
    karteGesehen = neueste.id;
    if (neueste.art !== "folie") karteZeigen(neueste, true); // die Folie erscheint schon groß im Bildbereich
  }
  if (!karten.length && karteOffen !== null) karteSchliessen(); // neues Meeting
}

// ---------- Darstellung ----------

function rendern() {
  const z = zustand; if (!z) return;
  const aktiv = z.laeuft || z.simulation || z.hoeren;
  const beendet = !aktiv && z.segmente.length > 0;
  if (aktiv) einrichtungOffen = false;
  const vorbereitung = !aktiv && (!beendet || einrichtungOffen);
  $("einrichtung").hidden = !vorbereitung;
  $("live").hidden = vorbereitung;

  // Kopfleiste
  $("titel-anzeige").textContent = z.titel || "Neues Meeting";
  $("ziel-anzeige").textContent = z.ziel || "";
  $("btn-start").hidden = !vorbereitung;
  $("btn-neu").hidden = !(beendet && !einrichtungOffen);
  // Ablage: läuft die Aufnahme, und wo liegt das Meeting danach?
  const ab = z.archiv;
  $("aufnahme-pill").hidden = !(ab?.aufnahme && z.hoeren);
  $("btn-ablage").hidden = !(ab && !z.hoeren);
  $("btn-ablage").textContent = ab?.fertig ? "Abgelegt – Ordner öffnen" : "Wird abgelegt …";
  $("btn-stopp").hidden = !z.hoeren || z.simulation;
  const pill = $("status-pill");
  pill.className = "pill" + (z.stumm ? " stumm" : z.simulation && z.hoeren ? " wiedergabe" : z.hoeren ? " live" : "");
  pill.textContent = z.stumm ? "Stumm" : z.simulation && z.hoeren ? "Wiedergabe" : z.hoeren ? "Live"
    : z.simulation ? "Demo" : z.laeuft ? "Läuft" : beendet ? "Beendet" : "Vorbereitung";
  $("btn-mikro").hidden = !z.hoeren;
  $("btn-mikro").classList.toggle("an", !!z.stumm);
  $("btn-mikro").replaceChildren(icon(z.stumm ? "mikroAus" : "mikro"));
  $("btn-mikro").dataset.tip = z.stumm ? "Mikro ist stumm – klicken, damit Nestor wieder zuhört" : "Mikro stumm schalten – nichts wird gehört oder ausgewertet";
  $("fehler").hidden = !z.fehler; $("fehler").textContent = z.fehler ?? "";
  // Mikrofon: welche Quelle hört gerade, und kommt überhaupt Ton an?
  const m = z.mikro ?? {};
  // Handy verbunden (gekoppelt, Seite offen) – auch bevor es Mikro und Ton übernimmt
  $("btn-mikro-quelle").hidden = z.simulation || (!m.quelle && !z.handys) || (!z.hoeren && m.quelle !== "handy" && !z.handys);
  $("mq-text").textContent = m.quelle === "handy" ? "Mikro: Handy"
    : m.quelle === "laptop" && z.hoeren ? "Mikro: Laptop" : `Handy verbunden${z.handys > 1 ? ` (${z.handys})` : ""}`;
  $("btn-mikro-quelle").dataset.tip = m.quelle === "handy" ? "Das Handy hört zu – klicken zum Zurückholen" : "Der Laptop hört zu – klicken, um ein Handy zu koppeln";
  $("hf-laptop").hidden = !(z.hoeren && !z.simulation && m.quelle !== "laptop");
  $("mq-text").textContent += z.lautsprecher ? ` · Ton: ${z.lautsprecher === "handy" ? "Handy" : "Laptop"}` : "";
  // Nestor ohne Lautsprecher (Tab zu, Handy neu geladen): sichtbar machen und hier übernehmen lassen
  $("ton-fehlt").hidden = !(z.hoeren && z.assistent?.aktiv && !z.lautsprecher);
  $("mikro-weg").hidden = !m.weg;
  $("mikro-weg").textContent = !m.weg ? "" : m.quelle === null
    ? "Kein Mikrofon verbunden – Nestor hört nichts. Am Handy „Dieses Handy übernimmt Mikro und Ton“ tippen oder hier zurückholen (Handy-Symbol)."
    : `Seit ${Math.round(m.luecke)} s kein Ton vom ${m.quelle === "handy" ? "Handy – ist es gesperrt oder die App im Hintergrund?" : "Laptop-Mikrofon."}`;

  // Nestor
  const a = z.assistent;
  const nestorDa = a?.aktiv && z.hoeren;
  $("nestor").hidden = !nestorDa;
  $("btn-fragen").hidden = !nestorDa || a.zustand === "pausiert";
  $("btn-still").hidden = !nestorDa || !["spricht", "denkt", "recherchiert", "gespraech", "begruessung"].includes(a.zustand);
  $("btn-fortsetzen").hidden = !nestorDa || a.zustand !== "pausiert";
  if (nestorDa) {
    $("nestor").className = `nestor ${a.zustand}`;
    $("nestor-zustand").textContent = `${a.name} ${NESTOR_TEXT[a.zustand] ?? a.zustand}`;
  }
  // Untertitel: was Nestor gerade gesagt hat – nur kurz, damit nicht zu viel zu lesen ist
  const l = a?.letzte;
  const frisch = aktiv && l && (z.zeit - l.zeit < 25 || ["spricht", "gespraech"].includes(a.zustand));
  $("untertitel").hidden = !frisch || karteOffen !== null; // die Karte zeigt es schon, nicht doppelt lesen
  if (frisch) $("untertitel").replaceChildren(el("span", { class: "wer" }, a.name), l.antwort,
    ...((l.quellen ?? []).length ? [el("span", { class: "quellen" }, "Quellen: ",
      ...l.quellen.flatMap((q, i) => [i ? " · " : "", el("a", { href: q.url, target: "_blank", rel: "noopener" }, q.titel)]))] : []));

  // Hinweis-Band: neuester Hinweis, 45 s lang sichtbar
  const h = z.hinweise.at(-1);
  const zeigen = h && h.id !== hinweisWeg && z.zeit - h.zeit < 45 && aktiv;
  $("hinweis-band").hidden = !zeigen;
  if (zeigen) {
    const rot = h.art === "ton" || h.stufe === "warnung";
    $("hinweis-band").className = `hinweis-band${rot ? " rot" : ""}`;
    $("hinweis-icon").replaceChildren(icon(HINWEIS_ICON[h.art] ?? "achtung"));
    $("hinweis-text").textContent = h.text;
  }

  if (!vorbereitung) liveRendern(z);
  leisteRendern(z);
  kostenRendern(z);
  schluesselRendern(z);
  kartenRendern(z);
}

function liveRendern(z) {
  // Zeit – nur an dieser Stelle
  $("laufzeit").textContent = mmss(z.zeit);
  const akt = z.agenda[z.aktiver_punkt];
  $("punkt-titel").textContent = akt ? `${z.aktiver_punkt + 1}. ${akt.titel}` : "Keine Agenda";
  if (akt) {
    const rest = akt.verbleibend;
    $("countdown").className = `countdown ${akt.ampel}`;
    $("countdown").replaceChildren(
      el("span", { class: "zahl" }, rest >= 0 ? mmss(rest) : `+${mmss(-rest)}`),
      el("span", { class: "einheit" }, rest >= 0 ? "übrig" : "drüber"));
    $("zeit-fortschritt").style.width = `${Math.min(100, (akt.genutzt / Math.max(1, akt.minuten * 60)) * 100)}%`;
    $("zeit-fortschritt").className = akt.ampel;
    // Prognose fürs ganze Meeting: Gelaufenes + Rest des aktuellen Punkts + offene Punkte nach Plan
    const plan = z.agenda.reduce((s, p) => s + p.minuten * 60, 0);
    const offen = z.agenda.reduce((s, p, i) => s + (p.status === "offen" && i !== z.aktiver_punkt ? p.minuten * 60 : 0), 0);
    const prognose = z.zeit + Math.max(0, rest) + offen;
    const diff = Math.round((prognose - plan) / 60);
    $("prognose").className = `prognose${diff > 2 ? " rot" : ""}`;
    $("prognose").textContent = `Plan ${Math.round(plan / 60)} min · ${diff > 0 ? `voraussichtlich ${diff} min drüber` : diff < 0 ? `${-diff} min Puffer` : "im Plan"}`;
  } else { $("countdown").replaceChildren(); $("zeit-fortschritt").style.width = "0"; $("prognose").textContent = ""; }

  $("agenda").replaceChildren(...z.agenda.map((p, i) => el("li", {
      class: p.status, "data-tip": "Klicken: diesen Punkt als aktuell setzen",
      onclick: () => api("/api/punkt", { index: i }),
    },
    el("span", { class: "nr" }, p.status === "abgeschlossen" ? "✓" : String(i + 1)),
    el("span", { class: "punkt-titel" }, p.titel,
      ...(p.ergebnis?.ergebnis ? [el("span", { class: "punkt-ergebnis" }, p.ergebnis.ergebnis)] : [])),
    el("span", { class: "min" }, p.status === "offen" ? `${p.minuten} min` : `${mmss(p.genutzt)} / ${p.minuten}`))));

  const v = z.vorschlag;
  $("vorschlag").hidden = !v;
  if (v) $("vorschlag").replaceChildren(
    el("span", {}, `Weiter zu „${v.titel}“?`),
    el("div", { class: "knoepfe" },
      el("button", { class: "klein primaer", onclick: () => api("/api/punkt", { index: v.punkt }) }, "Ja, weiter"),
      el("button", { class: "klein", onclick: () => api("/api/vorschlag/verwerfen") }, "Nein")));

  // Regeln als Ampeln (Zeit steht nur links)
  $("regel-ampeln").replaceChildren(...(z.regel_status ?? []).map((r) => el("div", { class: `ampel ${r.farbe}`,
    "data-tip": (r.detail || r.titel) + (r.experimentell ? " – experimentell: im Raum noch nicht geprüft" : "") },
    el("span", { class: "a-icon" }, icon(r.id)),
    el("strong", {}, r.titel, ...(r.experimentell ? [el("span", { class: "exp" }, "exp.")] : [])),
    el("span", { class: "detail" }, r.detail))));
  $("erinnerungen").replaceChildren(...(z.regeln ?? []).map((t) => el("span", { "data-tip": "Erinnerung – wird nicht geprüft" }, t)));

  // Redeanteile, ohne Bewertung
  const anteile = Object.entries(z.redeanteile).sort((x, y) => y[1] - x[1]);
  const summe = anteile.reduce((s, [, x]) => s + x, 0) || 1;
  $("redeanteile").replaceChildren(...(anteile.length ? anteile.map(([wer, sek]) => el("div", { class: wer === "Person ?" ? "balken unsicher" : "balken",
    "data-tip": wer === "Person ?" ? `${mmss(sek)} min nicht sicher zuzuordnen – zu kurz oder mehrere gleichzeitig` : `${mmss(sek)} min gesprochen` },
    el("span", {}, wer.replace("Person ", "P ")),
    el("span", { class: "spur" }, Object.assign(el("span"), { style: `width:${(sek / summe) * 100}%` })),
    el("span", { class: "wert" }, `${Math.round((sek / summe) * 100)} %`))) : [el("span", { class: "leise-text" }, "Noch niemand erkannt.")]));

  dynamikRendern(z.dynamik);
  bildRendern(z);
}

const KLIMA_HOEHE = { ruhig: 30, lebhaft: 65, hitzig: 100 };
function dynamikRendern(d) {
  if (!d) return;
  const k = d.klima ?? { stufe: "ruhig", gruende: [] };
  const box = $("klima");
  box.className = `klima ${k.stufe}`;
  const thermo = el("span", { class: "thermo" }, el("span"));
  thermo.firstChild.style.height = `${KLIMA_HOEHE[k.stufe] ?? 30}%`;
  box.dataset.tip = "Letzte 3 Minuten: gleichzeitiges Sprechen, Ins-Wort-Fallen, Lautstärke und Ton";
  box.replaceChildren(thermo, el("div", {}, el("div", { class: "stufe" }, k.stufe[0].toUpperCase() + k.stufe.slice(1)),
    el("div", { class: "gruende" }, k.gruende.length ? k.gruende.join(" · ") : "keine Auffälligkeiten")));
  $("dynamik").replaceChildren(
    el("div", { "data-tip": "Vorfälle, in denen zwei gleichzeitig sprachen (seit Beginn / letzte 10 min)" },
      el("strong", {}, d.ueberlappungen), el("span", {}, `gleichzeitig gesprochen · ${d.ueberlappungen_10min} in 10 min`)),
    el("div", { "data-tip": "Wechsel ohne Pause, nach denen die neue Person das Wort behält (seit Beginn / letzte 10 min)" },
      el("strong", {}, d.unterbrechungen), el("span", {}, `ins Wort gefallen · ${d.unterbrechungen_10min} in 10 min`)));
}

function leisteRendern(z) {
  $("leiste").hidden = !leisteOffen;
  $("btn-transkript").classList.toggle("an", leisteOffen);
  if (!leisteOffen) return;
  $("reiter-transkript").classList.toggle("aktiv", reiter === "transkript");
  $("reiter-hinweise").classList.toggle("aktiv", reiter === "hinweise");
  $("reiter-nestor").classList.toggle("aktiv", reiter === "nestor");
  $("transkript").hidden = reiter !== "transkript";
  $("hinweise").hidden = reiter !== "hinweise";
  $("nestor-verlauf").hidden = reiter !== "nestor";
  const karten = z.karten ?? [];
  $("nestor-verlauf").replaceChildren(...(karten.length ? [...karten].reverse().map((k) =>
    el("li", { onclick: () => karteZeigen(k, false), title: "Karte wieder öffnen" }, icon(KARTEN_ICON[k.art] ?? "frage"),
      el("strong", {}, k.titel), el("span", {}, `${mmss(k.zeit)} · ${KARTEN_ART[k.art] ?? "Nestor"}`)))
    : [el("li", { class: "leer" }, el("span", {}, "Noch keine Karten – sie entstehen, wenn Nestor etwas erklärt oder recherchiert."))]));
  const tr = $("transkript");
  const unten = tr.scrollTop + tr.clientHeight >= tr.scrollHeight - 20;
  const zeilen = z.segmente.map((s) => el("li", {},
    el("span", { class: "wann" }, mmss(s.start)), el("span", { class: "wer" }, s.sprecher), el("span", {}, s.text)));
  if (z.teiltext) zeilen.push(el("li", { class: "teiltext" }, el("span", { class: "wann" }, "live"), el("span"), el("span", {}, z.teiltext)));
  tr.replaceChildren(...zeilen);
  if (unten) tr.scrollTop = tr.scrollHeight;
  $("hinweise").replaceChildren(...[...z.hinweise].reverse().map((h) => el("li", { class: h.art === "ton" || h.stufe === "warnung" ? "rot" : "" },
    el("span", { class: "meta" }, mmss(h.zeit)), h.text)));
}

function einstellungenRendern(e) {
  if (!e || !$("einstellungen").hidden) return; // nicht überschreiben, während jemand einstellt
  $("e-assistent").checked = e.assistent;
  $("e-modus").value = e.modus;
  $("e-stimme").value = e.stimme;
  $("e-bild").value = e.bild_minuten;
  $("e-monolog").value = e.monolog_sekunden;
  $("e-bild-anbieter").value = e.bild_anbieter;
  $("e-live-art").value = e.live_art;
  $("e-aufnahme").checked = !!e.aufnahme;
  $("e-live-hinweis").hidden = e.live_art !== "sparsam";
}

// Pegel des ankommenden Tons (vom Handy oder Laptop-Mikro), vom Server ~5× pro Sekunde; fällt sanft ab
let pegelWert = 0, pegelZeit = 0;
function pegelAnzeigen(w) {
  pegelWert = Math.max(w, pegelWert); pegelZeit = performance.now();
  $("mq-pegel").style.width = `${Math.round(pegelWert * 100)}%`; // direkt – Animation pausiert in verdeckten Fenstern
}
(function pegelZeichnen() {
  if (performance.now() - pegelZeit > 600) pegelWert = 0;  // kein Ton mehr angekommen: Balken leer
  $("mq-pegel").style.width = `${Math.round(pegelWert * 100)}%`;
  pegelWert *= 0.96;  // zwischen zwei Meldungen (200 ms) sanft abklingen
  requestAnimationFrame(pegelZeichnen);
})();

function verbinden() {
  ws = new WebSocket(`${wsBasis()}/ws`);
  ws.onopen = () => { if (lautsprecher) ws.send(JSON.stringify({ lautsprecher: true })); };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.typ === "stimme") return stimme.abspielen(d.pcm);
    if (d.typ === "stimme_stopp") return stimme.stopp();
    if (d.typ === "pegel") { pegelAnzeigen(d.wert); return; }
    zustand = d; formAusServer(d); rendern(); einstellungenRendern(d.einstellungen);
  };
  ws.onclose = () => setTimeout(verbinden, 1000);
}

// Start: Icons setzen, Formular vorbelegen, Regeln, Szenarien und Aufnahmen laden
(async () => {
  iconSetzen("btn-fragen", "frage"); iconSetzen("btn-still", "stopp"); iconSetzen("btn-fortsetzen", "weiter");
  iconSetzen("btn-transkript", "transkript"); iconSetzen("btn-einstellungen", "einstellungen"); iconSetzen("btn-handy", "handy");
  iconSetzen("btn-bild", "neu"); iconSetzen("btn-bild-png", "speichern"); iconSetzen("btn-bild-analyse", "datei");
  iconSetzen("kosten-icon", "muenze"); iconSetzen("btn-folie", "folie");
  document.querySelectorAll(".bl-kann li").forEach((li) => li.prepend(icon(li.dataset.icon)));
  iconSetzen("hinweis-zu", "zu"); iconSetzen("leiste-zu", "zu"); iconSetzen("karte-zu", "zu");
  $("f-titel").value = "Testmeeting";
  punktZeile({ titel: "Ziel und Ablauf klären", ziel: "Gemeinsames Verständnis, worüber heute entschieden wird", minuten: 2 });
  punktZeile({ titel: "Hauptthema", ziel: "Optionen sammeln und bewerten", minuten: 5 });
  punktZeile({ titel: "Nächste Schritte", ziel: "Wer macht was bis wann", minuten: 2 });
  const rk = await fetch("/api/regeln").then((r) => r.json());
  regelkatalog = rk.katalog; regelwahl(rk.standard);
  personZeile(); personZeile();
  const [szenarien, aufnahmen] = await Promise.all([fetch("/api/szenarien").then((r) => r.json()), fetch("/api/aufnahmen").then((r) => r.json())]);
  $("f-szenario").replaceChildren(...szenarien.map((n) => el("option", { value: n }, n)));
  $("f-aufnahme").replaceChildren(...aufnahmen.map((n) => el("option", { value: n }, n)));
  $("zeile-aufnahme").hidden = !aufnahmen.length;
  verbinden();
})();
