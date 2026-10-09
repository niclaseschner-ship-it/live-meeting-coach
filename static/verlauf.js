"use strict";

// Ticket #27: Verlauf (Mitte) und Band (oben) – gemeinsam für Dashboard (app.js) und Handy (handy.js).
// Verlauf: alles, was Inhalt ist, ist eine Karte (Antwort, Zusammenfassung, Recherche, Folie, Bild, Überblick,
// Festgehalten). Neueste vorn, mit ‹ › (und Wischen) blättert man zurück wie durch Bilder in einer Chatgruppe;
// nichts muss man wegklicken. Ein neues Ergebnis springt nach vorn und leuchtet kurz. Still Geliefertes (Bild,
// Recherche, Abschnitts-Zusammenfassung, unterbrochener Bogen) springt nur nach vorn, wenn die vordere Karte älter
// als ~60 s ist – sonst reiht es sich dahinter ein, mit dem Merker „1 neu ›“ (Nachtrag E).
// Band: Regel-Hinweise und Nestors stille Angebote, verschwinden von selbst, höchstens ein Knopf.

const ART_ZEICHEN = { aufgabe: "☐", entscheidung: "✓", offen: "?", risiko: "!" };
const ART_TYP = { aufgabe: "Aufgabe", entscheidung: "Entscheidung", offen: "Offener Punkt", risiko: "Risiko" };
const ART_LUECKE = { was: "was genau?", wer: "wer?", bis: "bis wann?", status: "beschlossen?", reaktion: "Reaktion?" };
const VK_ART = { antwort: "Nestor antwortet", recherche: "Recherche", folie: "Folie", stand: "Wo stehen wir?",
  regeln: "Regeln", protokoll: "Protokoll", ueberblick: "Überblick", zusammenfassung: "Zusammenfassung",
  fehlt: "Was noch fehlt", festgehalten: "Festgehalten", punkt: "Zusammenfassung", bild: "Live-Bild",
  beispiel: "So nutzt ihr Nestor" };
const STILL_VORN_SEKUNDEN = 60;
let ergebnisSignal = false; // nur durch Klick einschaltbar, keine zusätzliche KI
let signalAudio = null;
function neuesErgebnisSignal() {
  if (!ergebnisSignal || !signalAudio) return;
  const o = signalAudio.createOscillator(), g = signalAudio.createGain();
  o.frequency.value = 660; g.gain.value = 0.035;
  o.connect(g); g.connect(signalAudio.destination);
  o.start(); o.stop(signalAudio.currentTime + 0.12);
}

const verlauf = {
  ordnung: [],        // Karten-ids in Anzeige-Reihenfolge, [0] = vorn
  index: 0,           // angezeigte Karte
  gesehen: null,      // höchste schon eingeordnete id
  neu: [],            // still eingereihte, noch nicht angesehene ids („1 neu ›“)
  leuchten: null,     // id, die gerade nach vorn kam
  edit: null,         // {karte, id} – Lücke in einer Karte wird bearbeitet ("neu" für einen neuen Eintrag)
  richtung: 0,
  wurzel: null,
  sig: null,          // zuletzt gezeichnete Karte
};

function verlaufEinordnen(z) {
  const karten = z.karten ?? [];
  const nachId = new Map(karten.map((k) => [k.id, k]));
  if (!karten.length) { verlauf.ordnung = []; verlauf.index = 0; verlauf.neu = []; verlauf.gesehen = 0; return; }
  if (verlauf.gesehen === null) { // beim Laden: alle Karten, neueste vorn, nichts leuchtet
    verlauf.ordnung = karten.map((k) => k.id).reverse();
    verlauf.gesehen = Math.max(...karten.map((k) => k.id));
    return;
  }
  if (karten.length && Math.max(...karten.map((k) => k.id)) < verlauf.gesehen) { // neues Meeting
    verlauf.ordnung = []; verlauf.gesehen = 0; verlauf.index = 0; verlauf.neu = [];
  }
  for (const k of karten.filter((x) => x.id > verlauf.gesehen).sort((a, b) => a.id - b.id)) {
    verlauf.gesehen = k.id;
    const vorn = nachId.get(verlauf.ordnung[0]);
    const vornAlt = !vorn || (z.zeit - vorn.zeit) > STILL_VORN_SEKUNDEN;
    if (!k.still || vornAlt || !verlauf.ordnung.length) {
      verlauf.ordnung.unshift(k.id);
      verlauf.index = 0;
      verlauf.leuchten = k.id;
      verlauf.richtung = 1;
      setTimeout(() => { if (verlauf.leuchten === k.id) { verlauf.leuchten = null; } }, 2500);
    } else {
      verlauf.ordnung.splice(1, 0, k.id); // dahinter einreihen, Merker zeigen
      verlauf.neu.push(k.id);
      if (verlauf.index > 0) verlauf.index += 1; // die angezeigte Karte bleibt dieselbe
    }
  }
  verlauf.ordnung = verlauf.ordnung.filter((id) => nachId.has(id));
  verlauf.neu = verlauf.neu.filter((id) => verlauf.ordnung.includes(id));
  verlauf.index = Math.min(verlauf.index, Math.max(0, verlauf.ordnung.length - 1));
}

function verlaufZeigen(id) {
  const i = verlauf.ordnung.indexOf(id);
  if (i < 0) return;
  verlauf.sig = null;
  verlauf.richtung = i > verlauf.index ? -1 : 1;
  verlauf.index = i;
  verlauf.leuchten = id;
  verlauf.neu = verlauf.neu.filter((x) => x !== id);
  setTimeout(() => { if (verlauf.leuchten === id) verlauf.leuchten = null; }, 2500);
  if (zustand) verlaufRendern(zustand);
}

function verlaufBlaettern(schritt) { // +1 = älter (‹), −1 = neuer (›)
  const ziel = Math.min(Math.max(0, verlauf.index + schritt), Math.max(0, verlauf.ordnung.length - 1));
  if (ziel === verlauf.index) return;
  verlauf.richtung = schritt > 0 ? -1 : 1;
  verlauf.index = ziel;
  verlauf.sig = null;
  verlauf.neu = verlauf.neu.filter((x) => x !== verlauf.ordnung[ziel]);
  if (zustand) verlaufRendern(zustand);
}

// Wurzel: {buehne, zaehler, zurueck, vor, neu} – Elemente der Seite. Einmal verdrahten.
function verlaufVerdrahten(wurzel) {
  verlauf.wurzel = wurzel;
  wurzel.zurueck.onclick = () => verlaufBlaettern(1);
  wurzel.vor.onclick = () => verlaufBlaettern(-1);
  wurzel.neu.onclick = () => { const id = verlauf.neu[0]; if (id) verlaufZeigen(id); };
  const signal = el("button", { class: "klein", type: "button", "aria-pressed": "false",
    title: "Optionaler 0,12-Sekunden-Ton bei neuen Ergebnissen, keine API-Kosten" }, "Ergebnis-Ton: aus");
  signal.onclick = async () => {
    ergebnisSignal = !ergebnisSignal;
    if (ergebnisSignal) { signalAudio ??= new AudioContext(); await signalAudio.resume(); }
    signal.textContent = `Ergebnis-Ton: ${ergebnisSignal ? "an" : "aus"}`;
    signal.setAttribute("aria-pressed", String(ergebnisSignal));
  };
  wurzel.neu.after(signal);
  let x0 = null, y0 = null;
  wurzel.buehne.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  wurzel.buehne.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) verlaufBlaettern(dx > 0 ? 1 : -1); // rechts = zurück
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest?.("input, textarea, select")) return;
    if (e.key === "ArrowLeft") verlaufBlaettern(1);
    if (e.key === "ArrowRight") verlaufBlaettern(-1);
  });
}

function verlaufRendern(z) {
  const w = verlauf.wurzel; if (!w) return;
  const vorher = verlauf.gesehen;
  verlaufEinordnen(z);
  if (vorher !== null && verlauf.gesehen > vorher) neuesErgebnisSignal();
  const nachId = new Map((z.karten ?? []).map((k) => [k.id, k]));
  const n = verlauf.ordnung.length;
  w.zaehler.textContent = n ? `${verlauf.index + 1} / ${n}` : "";
  w.zurueck.disabled = verlauf.index >= n - 1;
  w.vor.disabled = verlauf.index <= 0;
  w.zurueck.hidden = w.vor.hidden = n < 2;
  w.neu.hidden = !verlauf.neu.length;
  w.neu.textContent = `${verlauf.neu.length} neues Ergebnis – jetzt ansehen ›`;
  w.neu.setAttribute("aria-live", "polite");
  // Nicht neu zeichnen, während jemand in einer Karte tippt – sonst verschwindet die Eingabe
  if (verlauf.edit && w.buehne.contains(document.activeElement) && document.activeElement.matches("input, select")) return;
  const k = n ? nachId.get(verlauf.ordnung[verlauf.index]) : beispielKarte(z);
  // Nur neu zeichnen, wenn sich die angezeigte Karte geändert hat (sonst flackert sie, und das Leuchten beginnt neu)
  const sig = JSON.stringify([k, k?.ids ? z.artefakte?.liste : null, verlauf.edit, z.knopf?.protokoll, z.stufe, z.modus, verlauf.leuchten]);
  if (sig === verlauf.sig && w.buehne.firstChild) return;
  verlauf.sig = sig;
  const karte = karteBauen(k, z);
  if (k && k.id === verlauf.leuchten) karte.classList.add("leuchtet");
  if (verlauf.richtung) { karte.classList.add(verlauf.richtung > 0 ? "von-links" : "von-rechts"); verlauf.richtung = 0; }
  w.buehne.replaceChildren(karte);
  const feld = typeof verlauf.edit?.fokus === "string" ? verlauf.edit.fokus : "was";
  const fokus = karte.querySelector(`.art-form input[name=${feld}]`) ?? karte.querySelector(".art-form input[name=was]");
  if (fokus && verlauf.edit?.fokus) { fokus.focus(); verlauf.edit.fokus = false; }
}

// Erste Karte im leeren Verlauf (Nachtrag): vier Beispiele, je Stufe passend
function beispielKarte(z) {
  const basis = z?.stufe === "basis";
  const knopf = z?.modus === "knopfdruck";
  const zeilen = knopf ? ["Knopf „Wo stehen wir?“ – Stand und nächster Schritt", "Knopf „Protokoll“ – was festgehalten ist",
    "„Nestor fragen …“ oben eintippen", "Knopf „Überblick“ – Entschiedenes, Offenes, Aufgaben"]
    : basis ? ["Taste halten: „Wo stehen wir?“ – loslassen", "Taste halten: „Fass mal zusammen.“",
      "Taste halten: „Recherchier die Mietpreise in Hannover.“", "Taste halten: „Anna macht das bis Freitag.“"]
    : ["„Nestor, wo stehen wir?“", "„Nestor, fass mal zusammen.“", "„Nestor, mach ein Bild davon.“",
      "„Nestor, Anna macht das bis Freitag.“"];
  return { id: 0, art: "beispiel", zeit: z?.zeit ?? 0, titel: basis ? "Wie ein Funkgerät" : knopf ? "Auf Knopfdruck" : "Wie ein Telefon",
    frage: basis ? "Taste halten, sprechen, loslassen – Nestor redet dann aus." : knopf ? ""
      : "„Nestor“ und eure Frage – direkt danach geht eine Nachfrage ohne Namen.", punkte: zeilen };
}

function karteBauen(k, z) {
  const a = el("article", { class: `vk vk-${k.art}${k.still ? " still" : ""}` });
  const kopf = el("header", { class: "vk-kopf" }, el("span", { class: "vk-art" }, VK_ART[k.art] ?? "Nestor"),
    ...(k.art !== "beispiel" ? [el("span", { class: "vk-zeit" }, mmss(k.zeit))] : []));
  a.append(kopf);
  if (k.art === "folie" && k.folie) { a.append(folieInhalt(k.folie)); return a; }
  if (k.art === "ueberblick" && k.ueberblick) { a.append(ueberblickInhalt(k.ueberblick)); return a; }
  a.append(el("h3", {}, k.titel ?? ""));
  if (k.frage && k.frage !== k.titel && !["zusammenfassung", "punkt", "fehlt", "festgehalten", "bild"].includes(k.art)) {
    a.append(el("p", { class: "vk-frage" }, k.art === "beispiel" ? k.frage : `„${k.frage}“`));
  }
  if (k.art === "bild") {
    const src = `/api/onepager.${k.format === "svg" ? "svg" : "png"}?v=${k.version}`;
    a.append(el("a", { class: "vk-bild", href: src, target: "_blank", rel: "noopener" }, el("img", { src, alt: k.titel ?? "Live-Bild" })));
    return a;
  }
  if (k.ids) { a.append(artefaktListe(k, z)); return a; }
  if (k.punkte?.length) a.append(el("ul", { class: "vk-punkte" }, ...k.punkte.map((p) => el("li", {}, p))));
  if (k.details) a.append(el("div", { class: "vk-recherche-text" }, k.details));
  if (k.quellen?.length) {
    a.append(el("div", { class: "vk-quellen" }, el("strong", {}, "Quellen"), ...k.quellen.map((q) => el("div", {},
      el("a", { href: q.url, target: "_blank", rel: "noopener" }, q.titel), " ", el("small", {}, q.seite ?? "")))));
  }
  if (k.art === "protokoll" && z?.knopf?.protokoll) {
    a.append(el("a", { class: "knopf-link", href: "/api/knopf/protokoll.md", target: "_blank" }, "Ganzes Protokoll öffnen"));
  }
  return a;
}

// --- Karten mit Meeting-Artefakten: live aus dem aktuellen Stand, Lücken antippen und eintragen (Nachtrag A) -------
function artefaktListe(k, z) {
  const alle = new Map(((z.artefakte ?? {}).liste ?? []).map((x) => [x.id, x]));
  const liste = k.art === "festgehalten" ? [...alle.values()] : k.ids.map((id) => alle.get(id)).filter(Boolean);
  const box = el("div", { class: "vk-artefakte" });
  if (!liste.length) box.append(el("p", { class: "vk-leer" }, (k.punkte ?? [])[0] ?? "Noch nichts festgehalten."));
  const ul = el("ul", { class: "artefakte" });
  for (const x of liste) {
    if (verlauf.edit?.karte === k.id && verlauf.edit.id === x.id) ul.append(el("li", { class: "art bearbeiten" }, artFormular(x)));
    else ul.append(artZeile(x, k));
  }
  if (verlauf.edit?.karte === k.id && verlauf.edit.id === "neu") ul.prepend(el("li", { class: "art bearbeiten" }, artFormular(null)));
  box.append(ul);
  if (k.art === "festgehalten") {
    box.append(el("div", { class: "vk-fuss" },
      el("button", { class: "klein", onclick: () => { verlauf.edit = { karte: k.id, id: "neu", fokus: true }; verlaufRendern(zustand); } }, "+ Eintragen"),
      el("a", { class: "knopf-link", href: "/api/knopf/protokoll.md", target: "_blank" }, "Ganzes Protokoll öffnen")));
  }
  return box;
}

function artFeld(name, wert, platzhalter) {
  return el("input", { name, value: wert ?? "", placeholder: platzhalter, autocomplete: "off" });
}
function artFormular(a) {
  const typ = el("select", { name: "typ" }, ...Object.entries(ART_TYP).map(([k, t]) =>
    el("option", { value: k, ...(k === (a?.typ ?? "aufgabe") ? { selected: "" } : {}) }, t)));
  const status = el("select", { name: "status" }, ...[["endgueltig", "beschlossen"], ["vorlaeufig", "vorläufig"],
    ["vorschlag", "nur Vorschlag"]].map(([k, t]) => el("option", { value: k, ...(k === (a?.status ?? "endgueltig") ? { selected: "" } : {}) }, t)));
  const f = el("form", { class: "art-form" }, typ, artFeld("was", a?.was, "Was?"),
    el("div", { class: "art-zwei" }, artFeld("wer", a?.wer, "Wer?"), artFeld("bis", a?.bis, "Bis wann?")),
    status, artFeld("reaktion", a?.reaktion, "Reaktion (vermeiden, verringern, in Kauf nehmen)"),
    el("div", { class: "art-knoepfe" },
      el("button", { class: "primaer klein", type: "submit" }, "Speichern"),
      ...(a ? [el("button", { class: "klein leise", type: "button", onclick: async () => {
        verlauf.edit = null; await api("/api/artefakte/ablehnen", { id: a.id }); } }, "Nicht nötig"),
      el("button", { class: "klein leise", type: "button", onclick: async () => {
        verlauf.edit = null; await api("/api/artefakte/loeschen", { id: a.id }); } }, "Löschen")] : []),
      el("button", { class: "klein leise", type: "button", onclick: () => { verlauf.edit = null; verlaufRendern(zustand); } }, "Abbrechen")));
  const sichtbar = () => { status.hidden = typ.value !== "entscheidung"; f.reaktion.hidden = typ.value !== "risiko"; };
  typ.onchange = sichtbar; sichtbar();
  f.onsubmit = async (e) => {
    e.preventDefault();
    const d = { typ: typ.value, was: f.was.value.trim(), wer: f.wer.value.trim(), bis: f.bis.value.trim() };
    if (typ.value === "entscheidung") d.status = status.value;
    if (typ.value === "risiko") d.reaktion = f.reaktion.value.trim();
    if (!d.was) { f.was.focus(); return; }
    verlauf.edit = null;
    await api(a ? "/api/artefakte/bearbeiten" : "/api/artefakte/neu", a ? { id: a.id, ...d } : d);
  };
  return f;
}

function artZeile(a, k) {
  const luecken = a.luecken ?? [];
  const vorher = (k.luecken_vorher ?? {})[String(a.id)] ?? [];
  const zeigen = k.luecken_zeigen !== false;
  const bearbeiten = (feld = "was") => { verlauf.edit = { karte: k.id, id: a.id, fokus: feld }; verlaufRendern(zustand); };
  const meta = [];
  const wert = { wer: a.wer, bis: a.bis ? `bis ${a.bis}` : null, reaktion: a.reaktion,
    status: a.status === "endgueltig" ? "beschlossen" : a.status === "vorlaeufig" ? "vorläufig" : null };
  for (const f of ["wer", "bis", "status", "reaktion"]) {
    if (luecken.includes(f)) continue;
    if (!wert[f] || (f === "status" && a.typ !== "entscheidung")) continue;
    // Nachtrag A: eine Lücke, die die Runde geschlossen hat, wird in derselben Karte grün
    meta.push(el("span", { class: vorher.includes(f) && zeigen ? "luecke zu" : "" }, wert[f]));
  }
  if (a.ausserhalb) meta.push(el("span", { class: "art-park" }, "Parkplatz"));
  const fehlt = zeigen ? luecken.map((l) => el("button", { class: `luecke${a.abgelehnt ? " still" : ""}`, type: "button",
    "data-tip": a.abgelehnt ? "Die Runde wollte das offen lassen" : "Fehlt noch – antippen zum Eintragen",
    onclick: (e) => { e.stopPropagation(); bearbeiten(["wer", "bis", "reaktion"].includes(l) ? l : "was"); } },
    ART_LUECKE[l] ?? l)) : [];
  const unsicher = a.konfidenz < 0.6 && !a.bestaetigt;
  return el("li", { class: `art ${a.typ}${luecken.length && zeigen ? " unvollstaendig" : ""}${unsicher ? " unsicher" : ""}${a.erledigt ? " erledigt" : ""}`,
      tabindex: "0", "data-tip": `${ART_TYP[a.typ]} · ${a.zeit_text}${a.zitat ? ` · „${a.zitat}“` : ""}${unsicher ? " · unsicher erkannt" : ""}`,
      onclick: () => bearbeiten(), onkeydown: (e) => { if (e.key === "Enter") bearbeiten(); } },
    el("span", { class: "art-zeichen", "aria-label": ART_TYP[a.typ] }, ART_ZEICHEN[a.typ]),
    el("span", { class: "art-inhalt" }, el("span", { class: "art-was" }, a.was,
      ...(a.bestaetigt ? [el("span", { class: "art-ok", "data-tip": "von der Runde bestätigt" }, " ✓")] : [])),
      el("span", { class: "art-meta" }, ...meta, ...fehlt)));
}

// --- Folie und Überblick als Karte ----------------------------------------------------------------------------------
function folieInhalt(f) {
  const quellen = f.quellen?.length ? el("ol", {}, ...f.quellen.map((q) => el("li", {},
    el("a", { href: q.url, target: "_blank", rel: "noopener" }, q.titel), el("small", {}, q.seite ?? ""))))
    : el("p", {}, "Keine Quellen gemeldet.");
  return el("div", { class: "vk-folie" },
    el("h3", {}, f.titel), el("p", { class: "kern" }, f.kernaussage ?? ""),
    el("div", { class: "folie-inhalt" },
      el("div", {}, el("ul", { class: "folie-punkte" }, ...(f.punkte ?? []).map((p) => el("li", {}, p))),
        ...(f.offen ? [el("div", { class: "folie-offen" }, "Offen: ", f.offen)] : [])),
      el("div", { class: "folie-quellen" }, el("h4", {}, "Quellen"), quellen)),
    el("div", { class: "folie-fuss" }, `Frage: „${f.frage}“ · Websuche, Stand ${f.datum ?? ""} – Angaben ohne Gewähr, Quellen prüfen.`));
}

function ueberblickInhalt(u) {
  const liste = (eintraege, leer, zeile) => eintraege?.length ? el("ul", {}, ...eintraege.map((e) => el("li", {}, ...zeile(e))))
    : el("p", { class: "ub-leer" }, leer);
  const block = (klasse, zeichen, titel, inhalt) => el("section", { class: `ub-block ${klasse}` },
    el("h4", {}, el("span", { class: "ub-zeichen", "aria-hidden": "true" }, zeichen), titel), inhalt);
  return el("div", { class: "vk-ueberblick" },
    el("div", { class: "ub-kopf" },
      el("div", {}, el("h3", {}, u.titel), ...(u.kernaussage ? [el("p", { class: "ub-kern" }, u.kernaussage)] : []),
        ...(u.fokus ? [el("p", { class: "ub-fokus" }, `Fokus: ${u.fokus}`)] : [])),
      el("div", { class: "ub-stand" }, el("strong", {}, `Stand ${u.laufzeit}`), ...(u.punkt ? [el("span", {}, `jetzt ${u.punkt}`)] : []))),
    el("div", { class: "ub-raster" },
      block("gruen", "✅", "Entschieden", liste(u.entschieden, "Noch nichts ausdrücklich beschlossen.", (e) => [e.was])),
      block("bernstein", "🟡", "Offen", liste(u.offen, "Keine offenen Fragen genannt.", (e) => [e.was])),
      block("blau", "📌", "Aufgaben", liste(u.aufgaben, "Noch keine Aufgaben verteilt.", (a) => [a.was,
        el("small", {}, ` – ${a.wer ?? "wer: offen"}${a.bis ? ` · bis ${a.bis}` : ""}`)])),
      block("grau", "↪", "Außerhalb der Agenda", liste(u.ausserhalb, "Keine Abschweifung.", (a) => [
        ...(a.zeit ? [el("small", {}, `${a.zeit} `)] : []), a.was]))),
    ...(u.neu?.length ? [el("p", { class: "ub-neu" }, el("strong", {}, "Neu seit dem letzten Stand: "), u.neu.join(" · "))] : []));
}

// --- Band (oben) ------------------------------------------------------------------------------------------------
const bandWeg = new Set(); // weggeklickte Einträge (Hinweis-ids, "vorschlag-<punkt>")
const BAND_ICON = { ton: "ton", ausreden: "ausreden", ueberlappung: "ausreden", fokus: "thema", zeit: "zeit",
  monolog: "kurz", alle: "alle", ergebnisse: "ergebnisse", luecken: "ergebnisse", fuenf: "zeit", namen: "alle",
  taste: "mikro", vorschlag: "weiter" };

function bandEintraege(z) {
  const aktiv = z.laeuft || z.simulation || z.hoeren;
  if (!aktiv) return [];
  const aus = [];
  const v = z.vorschlag;
  if (v && !bandWeg.has(`vorschlag-${v.punkt}`)) {
    aus.push({ schluessel: `vorschlag-${v.punkt}`, art: "vorschlag", text: `Weiter zu „${v.titel}“?`,
      knopf: { text: "Weiter", lauf: () => api("/api/punkt", { index: v.punkt }) },
      weg: () => api("/api/vorschlag/verwerfen") });
  }
  for (const h of [...(z.hinweise ?? [])].reverse()) {
    if (aus.length >= 3) break;
    if (bandWeg.has(h.id) || z.zeit - h.zeit > (h.dauer ?? 45)) continue;
    if (h.punkt != null && h.punkt !== z.aktiver_punkt) continue; // gilt nur für den Punkt, bei dem er entstand
    const a = h.aktion;
    let knopf = null;
    if (a?.bogen) knopf = { text: a.text, lauf: () => bandBogen(a.bogen, h.id) };
    else if (a?.karte) knopf = { text: a.text ?? "Zur Karte", lauf: () => verlaufZeigen(a.karte) };
    aus.push({ schluessel: h.id, art: h.art, text: h.text, rot: h.art === "ton" || h.stufe === "warnung", knopf,
      still: ["namen", "taste"].includes(h.art) });
  }
  return aus;
}

async function bandBogen(art, id) {
  bandWeg.add(id);
  const knopfdruck = zustand?.modus === "knopfdruck";
  // Nur auf Knopfdruck: Nestor spricht nicht – „Zusammenfassen“ ist dort das Protokoll
  try { await api(`/api/knopf/${knopfdruck ? "protokoll" : art}`, { band: true }); } catch { /* Meldung zeigt api() */ }
}

function bandRendern(z, box) {
  const eintraege = bandEintraege(z);
  box.hidden = !eintraege.length;
  // nur neu aufbauen, wenn sich etwas ändert – sonst beginnt das Einblenden bei jeder Zustandsmeldung neu
  const sig = JSON.stringify(eintraege.map((b) => [b.schluessel, b.text, b.knopf?.text]));
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.replaceChildren(...eintraege.map((b) => el("div", { class: `band-eintrag ${b.art}${b.rot ? " rot" : ""}${b.still ? " leise" : ""}` },
    el("span", { class: "band-icon" }, icon(BAND_ICON[b.art] ?? "achtung")),
    el("span", { class: "band-text" }, b.text),
    ...(b.knopf ? [el("span", { class: "band-punkt", "aria-hidden": "true" }, "·"),
      el("button", { class: "band-knopf", onclick: () => b.knopf.lauf() }, `${b.knopf.text} ›`)] : []),
    el("button", { class: "icon klein band-zu", "data-tip": "Ausblenden", "aria-label": "Ausblenden",
      onclick: () => { bandWeg.add(b.schluessel); b.weg?.(); bandRendern(zustand, box); } }, icon("zu")))));
}
