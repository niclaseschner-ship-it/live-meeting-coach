"use strict";

// ---------- Konfidenz (Ticket „Konfidenz“, Lastenheft 4.3) ----------
// Eine Quelle im Backend (coach/regeln.py, coach/konfidenz.py), hier nur nachschlagen und zeigen.
function signal(z, id) { return (z.signale ?? []).find((s) => s.id === id); }
// Anzeige-Wort "Beta" statt "experimentell" (Ticket #10) – der Schlüssel "experimentell" bleibt in
// coach/regeln.py und coach/konfidenz.py unverändert, nur was man liest, heißt jetzt Beta.
function konfSchild(klasse = "") { return el("span", { class: `konf-schild ${klasse}`.trim() }, "Beta"); }

// ---------- Vorbereitung ----------
let regelkatalog = [];
function personZeile(name = "") {
  const z = el("div", { class: "f-person" }, el("input", { placeholder: "Name", value: name }),
    el("button", { class: "icon klein", "data-tip": "Person entfernen", onclick: () => z.remove() }, icon("zu")));
  $("f-teilnehmende").append(z);
}
// Ersetzt die Teilnehmenden-Liste komplett – vom Server (formAusServer) oder aus der Agenda per Prompt
// (agenda.js: agendaUebernehmen(), wenn die Einladung Namen nennt).
function teilnehmendeSetzen(namen) {
  $("f-teilnehmende").replaceChildren();
  (namen.length ? namen : ["", ""]).forEach((n) => personZeile(n));
}
// Eine Regel-Kachel – gleiche Einstufung wie im Dashboard (verlässlich/Beta) statt eigener Prüfstufen-Texte;
// Kurzsatz aus Lastenheft 4.3 im Tipp, wenn Beta (Schlüssel bleibt "experimentell", coach/regeln.py). Nur
// umgesetzte Regeln kommen überhaupt hier an (regelwahl() filtert) – noch nicht umgesetzte bleiben im Katalog,
// erscheinen aber nicht zur Auswahl (Rückmeldung 08.10.2026, vorher ausgegraut mit "folgt").
function regelKachel(r, standard) {
  return el("label",
    { class: "regel", "data-tip": r.stufe === "experimentell" && r.kurzsatz ? r.kurzsatz : r.beobachtet },
    el("input", { type: "checkbox", value: r.id, ...(standard.includes(r.id) ? { checked: "" } : {}) }),
    el("span", { class: "r-icon" }, icon(r.id)),
    el("span", {}, r.titel.split(" – ")[0]),
    el("span", { class: "r-stufe" }, r.stufe_text));
}
// „Weitere Regeln“ (Ticket #10, ersetzt das frühere „Eigene Regeln“): Freitext, den Nestor einmal am Anfang
// vorliest, aber nicht prüft. Eigene, neutrale Gruppe statt Kachel unter den prüfbaren Regeln (Rückmeldung
// 08.10.2026): Lautsprecher-Symbol statt Datei-Symbol, Untertitel auf der Gruppe selbst sagt, dass Nestor das
// nur vorliest und nicht prüft. #f-regeln wird unverändert von formularDaten() gelesen.
function weitereRegelnKachel() {
  return el("div", { class: "regel-weitere" },
    el("span", { class: "r-icon" }, icon("lautsprecher")),
    el("textarea", { id: "f-regeln", rows: "2", "aria-label": "Weitere Regeln",
      placeholder: "Eine pro Zeile, z. B. Handys bleiben in der Tasche" }));
}
function regelwahl(standard) {
  const vorherigeWeitere = $("f-regeln")?.value ?? "";
  $("f-regelwahl-verlaesslich").replaceChildren(
    ...regelkatalog.filter((r) => r.stufe === "verlaesslich" && r.umgesetzt).map((r) => regelKachel(r, standard)));
  $("f-regelwahl-beta").replaceChildren(
    ...regelkatalog.filter((r) => r.stufe === "experimentell" && r.umgesetzt).map((r) => regelKachel(r, standard)));
  $("f-regel-weitere").replaceChildren(weitereRegelnKachel());
  $("f-regeln").value = vorherigeWeitere;
}
// Eine Seite, ein Stand: Das Formular übernimmt, was auf dem Server eingerichtet ist (anderer Tab, anderes Gerät),
// solange hier niemand gerade tippt.
let formStand = null;
function formAusServer(z) {
  agendaSchluesselRendern(z.schluessel_vorhanden);  // unabhängig vom Rest: greift auch ohne Agenda vom Server
  if (!z.agenda?.length) return;
  const stand = JSON.stringify([z.titel, z.ziel, z.agenda.map((p) => [p.titel, p.ziel, p.minuten]), z.teilnehmende, z.regel_ids]);
  if (stand === formStand || $("einrichtung").contains(document.activeElement)) return;
  formStand = stand;
  $("f-titel").value = z.titel ?? ""; $("f-ziel").value = z.ziel ?? "";
  agendaVonServer(z.agenda);
  teilnehmendeSetzen(z.teilnehmende ?? []);
  if (regelkatalog.length && z.regel_ids) regelwahl(z.regel_ids);
}
function formularDaten() {
  return {
    titel: $("f-titel").value,
    ziel: $("f-ziel").value,
    agenda: agendaErgebnis(),
    regeln: $("f-regeln").value.split("\n"),
    regel_ids: [...document.querySelectorAll("#f-regelwahl-verlaesslich input:checked, #f-regelwahl-beta input:checked")]
      .map((i) => i.value),
    assistent: $("f-assistent").checked,
    teilnehmende: [...$("f-teilnehmende").querySelectorAll("input")].map((i) => i.value),
  };
}
const einrichten = () => api("/api/einrichten", formularDaten());

// ---------- Knöpfe ----------
let einrichtungOffen = false;
let leisteOffen = false;
let reiter = "transkript";

$("btn-person-neu").onclick = () => personZeile();
$("btn-simulation").onclick = async () => { await einrichten(); api("/api/simulation", { name: $("f-szenario").value, tempo: 10 }); };
$("btn-abspielen").onclick = () => { stimme.bereit(); api("/api/abspielen", { name: $("f-aufnahme").value, tempo: 1, auto_wechsel: $("f-auto").checked }); };
$("btn-start").onclick = async () => {
  await einrichten();
  await api("/api/start");
};
$("btn-stopp").onclick = async () => { await mikro.stoppen(); await api("/api/stopp"); location.href = "/abschluss"; };
$("btn-neu").onclick = () => { einrichtungOffen = true; rendern(); window.scrollTo(0, 0); };
$("btn-mikro").onclick = () => api("/api/stumm", { an: !zustand?.stumm });
$("btn-fragen").onclick = () => { stimme.bereit(); api("/api/assistent/fragen"); };
$("btn-still").onclick = () => { stimme.stopp(); nestorStopp(); api("/api/assistent/stopp"); };
$("btn-fortsetzen").onclick = () => api("/api/assistent/fortsetzen");
$("btn-transkript").onclick = () => { leisteOffen = !leisteOffen; rendern(); };
$("leiste-zu").onclick = () => { leisteOffen = false; rendern(); };
$("reiter-transkript").onclick = () => { reiter = "transkript"; rendern(); };
$("reiter-hinweise").onclick = () => { reiter = "hinweise"; rendern(); };
// Kopfleiste entschlackt (Ticket #17 Punkt 4): Handy koppeln und Einstellungen stecken im „Mehr“-Menü – beides
// seltene, vorbereitende Aktionen statt Aktionen je Minute. Ein Klick darauf wählt aus und schließt das Menü.
$("btn-mehr").onclick = () => { $("mehr-menu").hidden = !$("mehr-menu").hidden; $("kosten").hidden = $("einstellungen").hidden = $("handy-fenster").hidden = true; };
$("btn-einstellungen").onclick = () => { $("mehr-menu").hidden = true; $("einstellungen").hidden = !$("einstellungen").hidden; $("kosten").hidden = $("handy-fenster").hidden = true; };
$("btn-kosten").onclick = () => { $("kosten").hidden = !$("kosten").hidden; $("einstellungen").hidden = $("mehr-menu").hidden = true; if (zustand) kostenRendern(zustand); };
$("btn-schluessel").onclick = (e) => { e.stopPropagation(); $("einstellungen").hidden = false; $("s-eingabe").focus(); };
// Handy koppeln: QR-Code mit Kopplungscode; das Handy kann dann das Mikrofon übernehmen
let kopplungGeladen = false;
async function handyFensterZeigen() {
  $("handy-fenster").hidden = !$("handy-fenster").hidden; $("einstellungen").hidden = $("kosten").hidden = true;
  if ($("handy-fenster").hidden || kopplungGeladen) return;
  const k = await fetch("/api/kopplung").then((r) => r.json());
  kopplungGeladen = !!k.adresse; // ohne Freigabe beim nächsten Öffnen erneut nachsehen
  $("hf-code").textContent = k.code.replace(/(.{4})/, "$1-");
  $("hf-qr").innerHTML = k.qr ?? "";
  $("hf-text").replaceChildren(...(k.adresse ? [el("a", { href: k.adresse, target: "_blank", rel: "noopener" }, "Handy-Link öffnen oder kopieren")]
    : ["Kein Tailscale gefunden. HTTPS ist Pflicht fürs Handy-Mikrofon: ", el("code", {}, k.befehl),
      " einrichten oder LMC_HANDY_URL setzen."]));
}
$("btn-handy").onclick = () => { $("mehr-menu").hidden = true; handyFensterZeigen(); };
$("btn-handy-vorbereitung").onclick = handyFensterZeigen;
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
      && !$("btn-mikro-quelle").contains(e.target) && !$("btn-handy-vorbereitung").contains(e.target)) $("handy-fenster").hidden = true;
  if (!$("einstellungen").hidden && !$("einstellungen").contains(e.target) && !$("btn-einstellungen").contains(e.target)) $("einstellungen").hidden = true;
  if (!$("kosten").hidden && !$("kosten").contains(e.target) && !$("btn-kosten").contains(e.target)) $("kosten").hidden = true;
  if (!$("mehr-menu").hidden && !$("mehr-menu").contains(e.target) && !$("btn-mehr").contains(e.target)) $("mehr-menu").hidden = true;
  if (!$("arbeit-liste").hidden && !$("arbeit-liste").contains(e.target) && !$("arbeitsring").contains(e.target)) $("arbeit-liste").hidden = true;
});
// Einstellungen: jede Änderung sofort an den Server
const einstellen = (feld, wert) => api("/api/einstellungen", { [feld]: wert });
$("e-assistent").onchange = (e) => einstellen("assistent", e.target.checked);
$("e-modus").onchange = (e) => einstellen("modus", e.target.value);
$("e-stimme").onchange = (e) => einstellen("stimme", e.target.value);
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
  // „eigener Schlüssel“ steht seit der entschlackten Kopfleiste (Ticket #17) an der Stufen-Pille (siehe rendern())
  $("schluessel-fehlt").hidden = !!s.vorhanden || !!s.offline || basisStufe(z); // Basis: Mistral-Schlüssel liegt am Server
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
  const basis = basisStufe(z);
  $("btn-kosten").dataset.tip = `Geschätzte ${basis ? "Mistral" : "OpenAI"}-Kosten dieses Meetings – klicken für Details`;
  $("k-anbieter").textContent = basis ? "Mistral" : "OpenAI";
  $("k-abrechnung").href = basis ? "https://admin.mistral.ai/organization/usage" : "https://platform.openai.com/usage";
  $("k-abrechnung").textContent = basis ? "admin.mistral.ai" : "platform.openai.com/usage";
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

// ---------- Stufe ----------
const basisStufe = (z) => z?.stufe === "basis";
const knopfdruck = (z) => z?.modus === "knopfdruck";

// ---------- Knöpfe (Ticket #6; seit #13 in beiden Stufen gleich; seit #27 jeder Knopf ein Antwortbogen) ----------
// Ein Knopf startet einen Bogen: Bestätigung, Karte im Verlauf, ein bis zwei Sätze. Während ein Bogen läuft, sind die
// Knöpfe gesperrt. Mit „Nur auf Knopfdruck“ (Basis) transkribiert der Knopf vorher den offenen Ton, die Antwort kommt
// als Karte ohne Stimme, und es gibt das Verwerfen.
const KNOPF_PFAD = { stand: "/api/knopf/stand", regeln: "/api/knopf/regeln", ueberblick: "/api/knopf/ueberblick",
  protokoll: "/api/knopf/protokoll", bild: "/api/knopf/bild", frage: "/api/knopf/frage",
  zusammenfassen: "/api/knopf/zusammenfassen", fehlt: "/api/knopf/fehlt" };
const KNOPF_NAME = { stand: "Wo stehen wir?", regeln: "Regeln prüfen", ueberblick: "Überblick", protokoll: "Gesamtprotokoll",
  bild: "Meetingbild", frage: "Nestor fragen", zusammenfassen: "Ergebnisse bündeln", fehlt: "Lücken klären" };
let knopfWartet = null;
function knopfDruecken(art, daten = {}) {
  if (knopfWartet) return Promise.resolve(false);
  knopfWartet = art;
  if (art === "ueberblick" && !daten.umfang) {
    daten.umfang = $("ueberblick-umfang").value;
  }
  if (knopfdruck(zustand) && zustand?.knopf) zustand.knopf = { ...zustand.knopf, laeuft: art, schritt: "transkribiere", anteil: 0, fehler: null };
  if (!knopfdruck(zustand) && zustand?.assistent) zustand.assistent = { ...zustand.assistent, bogen: { art, name: KNOPF_NAME[art] } };
  knopfRendern(zustand);
  return api(KNOPF_PFAD[art], daten).then(() => true, () => false).finally(() => {
    knopfWartet = null; if (zustand) knopfRendern(zustand);
  }); // Fehler zeigt api() schon an
}
document.querySelectorAll("#knopf-leiste .knopf-art").forEach((b) => { b.onclick = () => knopfDruecken(b.dataset.knopf); });
$("ueberblick-umfang").onchange = () => aktionshilfeRendern(zustand, "#knopf-leiste .knopf-art, #knopf-fragen", $("ueberblick-umfang").value);
$("knopf-frage-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("knopf-frage").value.trim();
  if (!text) return;
  stimme.bereit();
  knopfDruecken("frage", { text }).then((ok) => { if (ok) $("knopf-frage").value = ""; });
};
$("knopf-verwerfen-5").onclick = () => api("/api/knopf/verwerfen", { minuten: 5 });
$("knopf-verwerfen-alles").onclick = () => {
  if (confirm("Alles bisher Gesagte verwerfen? Ton, Transkript und Auswertungen dieses Meetings werden gelöscht. Redeanteile bleiben.")) {
    api("/api/knopf/verwerfen", { minuten: null });
  }
};
// Fortschritt zwischen zwei Zustandsmeldungen: in den Stand einarbeiten, der nächste Schnappschuss bestätigt ihn
function knopfMeldung(d) {
  if (!zustand?.knopf) return;
  zustand.knopf = { ...zustand.knopf, laeuft: d.schritt === "fertig" ? null : d.art, schritt: d.schritt, anteil: d.anteil,
    fertig: d.fertig, gesamt: d.gesamt, fehler: d.fehler ?? null };
  knopfRendern(zustand);
}
function knopfOffenText(k) {
  if (!k.seit_sekunden) return "Alles ausgewertet";
  return k.seit_sekunden < 60 ? "Unter 1 Minute noch nicht ausgewertet"
    : `${Math.round(k.seit_sekunden / 60)} Minuten noch nicht ausgewertet`;
}
function knopfRendern(z) {
  aktionshilfeRendern(z, "#knopf-leiste .knopf-art, #knopf-fragen", $("ueberblick-umfang").value);
  const an = !!z.hoeren;
  $("knopf-leiste").hidden = !an;
  if (!an) return;
  const k = z.knopf ?? {};
  const nurKnopf = knopfdruck(z);
  const basis = basisStufe(z);
  const a = z.assistent ?? {};
  $("knopf-offen").hidden = !nurKnopf; $("knopf-verwerfen").hidden = !nurKnopf;
  $("knopf-offen").textContent = knopfOffenText(k);
  $("knopf-offen").dataset.tip = k.aeusserungen ? `${k.aeusserungen} Äußerungen, ${mmss(k.sprache_sekunden)} min Sprache – werden beim nächsten Knopf transkribiert` : "";
  // Basis: kein Bildmodell (der Überblick steht für das Bild); Regeln-Knopf nur, wenn Regeln gewählt sind (Ticket #27)
  document.querySelector('#knopf-leiste [data-knopf="bild"]').hidden = basis;
  document.querySelector('#knopf-leiste [data-knopf="regeln"]').hidden = !(z.regel_ids ?? []).length;
  // Nur auf Knopfdruck kennt nur das Protokoll – Zusammenfassen und Was fehlt sind dort dasselbe
  document.querySelector('#knopf-leiste [data-knopf="zusammenfassen"]').hidden = nurKnopf;
  document.querySelector('#knopf-leiste [data-knopf="fehlt"]').hidden = nurKnopf;
  const bogen = !nurKnopf && a.bogen;
  const laeuft = !!knopfWartet || (nurKnopf ? !!k.laeuft : !!bogen);
  document.querySelectorAll("#knopf-leiste .knopf-art, #knopf-fragen").forEach((b) => {
    b.disabled = laeuft; b.classList.toggle("knopf-aktiv", (nurKnopf ? k.laeuft : bogen?.art) === b.dataset.knopf);
  });
  $("knopf-bogen").hidden = !bogen && !knopfWartet;
  $("knopf-bogen").textContent = knopfWartet ? "Letzten Redebeitrag übernehmen …" : bogen ? `Nestor ist bei „${bogen.name}“ …` : "";
  $("knopf-fortschritt").hidden = !(nurKnopf && k.laeuft);
  if (nurKnopf && k.laeuft) {
    const transkribiert = k.schritt === "transkribiere";
    $("knopf-balken").style.width = `${Math.round((transkribiert ? (k.anteil ?? 0) : 1) * 100)}%`;
    $("knopf-balken").parentElement.classList.toggle("denkt", !transkribiert);
    $("knopf-schritt").textContent = `${KNOPF_NAME[k.laeuft] ?? ""}: ` + (transkribiert
      ? `transkribiere${k.gesamt ? ` ${k.fertig} von ${k.gesamt}` : ""} …` : "Nestor denkt nach …");
  }
  $("knopf-fehler").hidden = laeuft || !k.fehler;
  $("knopf-fehler").textContent = k.fehler ?? "";
  // Funkgerät (Basis, Ticket #27): Sprechtaste am Laptop – Knopf halten oder Leertaste
  const tasteDa = basis && !nurKnopf && !!a.aktiv && a.zustand !== "pausiert";
  $("btn-taste").hidden = !tasteDa;
  if (!taste.aktiv) {
    if (tasteMeldung) $("taste-text").textContent = tasteMeldung;
    else $("taste-text").replaceChildren("Sprechtaste – halten", el("span", { class: "nur-gross" }, " (oder Leertaste)"));
  }
}

// ---------- Sprechtaste (Funkgerät, Ticket #27) ----------
// Halten, sprechen, loslassen: der Ton der Frage geht als WAV an /api/frage/audio; drücken unterbricht Nestor.
const taste = { aktiv: false };
let tasteMeldung = null;
async function tasteAn(e) {
  e?.preventDefault?.();
  if (taste.aktiv || $("btn-taste").hidden) return;
  taste.aktiv = true;
  stimme.bereit(); stimme.stopp(); nestorStopp();
  $("btn-taste").classList.add("haelt"); $("taste-text").textContent = "Ich höre … loslassen zum Senden";
  try {
    await halten.start();
    await fetch("/api/frage/halten", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ an: true }) });
  } catch (err) {
    taste.aktiv = false; halten.teile = null; $("btn-taste").classList.remove("haelt");
    tasteMeldung = `Mikrofon nicht verfügbar: ${err.message ?? err}`; knopfRendern(zustand);
  }
}
async function tasteAus() {
  if (!taste.aktiv) return;
  taste.aktiv = false;
  $("btn-taste").classList.remove("haelt");
  const wav = await halten.ende();
  if (wav.byteLength < 44 + RATE * 2 * 0.5) { // unter einer halben Sekunde: versehentlich getippt
    fetch("/api/frage/halten", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ an: false }) });
    tasteMeldung = "Zum Fragen halten, sprechen, dann loslassen.";
  } else {
    tasteMeldung = "Nestor hört die Frage …";
    knopfRendern(zustand);
    try {
      const r = await fetch("/api/frage/audio", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
      const d = await r.json().catch(() => ({}));
      tasteMeldung = !r.ok ? (d.detail ?? `Fehler ${r.status}`) : !d.ok ? d.grund : `„${d.frage}“`;
    } catch { tasteMeldung = "Server nicht erreichbar."; }
  }
  knopfRendern(zustand);
  setTimeout(() => { tasteMeldung = null; if (zustand) knopfRendern(zustand); }, 6000);
}
$("btn-taste").addEventListener("pointerdown", tasteAn);
for (const ev of ["pointerup", "pointercancel", "pointerleave"]) $("btn-taste").addEventListener(ev, tasteAus);
$("btn-taste").addEventListener("contextmenu", (e) => e.preventDefault());
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.target.closest?.("input, textarea, select, [contenteditable='true']")) return;
  if ($("btn-taste").hidden) return;
  e.preventDefault();
  if (!e.repeat) tasteAn();
});
document.addEventListener("keyup", (e) => { if (e.code === "Space" && taste.aktiv) { e.preventDefault(); tasteAus(); } });
window.addEventListener("blur", () => { if (taste.aktiv) tasteAus(); });

// ---------- Arbeitsring: lange Aufträge (Ticket #27) ----------
const AUFTRAG_ZUSTAND = { laeuft: "läuft", wartet: "wartet" };
$("arbeitsring").onclick = () => { $("arbeit-liste").hidden = !$("arbeit-liste").hidden; };
function arbeitRendern(z) {
  const auftraege = z.assistent?.auftraege ?? [];
  const laeuft = auftraege.filter((x) => x.zustand === "laeuft").length;
  const wartet = auftraege.length - laeuft;
  $("arbeitsring").hidden = !auftraege.length;
  if (!auftraege.length) $("arbeit-liste").hidden = true;
  $("arbeit-text").textContent = [laeuft ? `${laeuft} läuft` : "", wartet ? `${wartet} wartet` : ""].filter(Boolean).join(" · ");
  $("arbeitsring").dataset.tip = "Lange Aufträge – antippen zeigt sie, ✕ bricht ab";
  $("arbeit-liste").replaceChildren(...auftraege.map((x) => el("li", { class: x.zustand },
    el("span", { class: "nf-chip" }, AUFTRAG_ZUSTAND[x.zustand] ?? x.zustand),
    el("strong", {}, x.name), el("span", { class: "nf-auftrag-titel" }, x.titel ? `„${x.titel}“` : ""),
    el("button", { class: "icon klein", "data-tip": `${x.name} abbrechen`, "aria-label": `${x.name} abbrechen`,
      onclick: () => api("/api/assistent/abbrechen", { id: x.id }) }, icon("zu")))));
}

// ---------- Nestor-Zeile (Ticket #21/#27) ----------
// Über dem Verlauf: Nestors Zustand mit dem N – Ring dreht sich, solange er arbeitet; in Premium nach einem Bogen der
// Ring „Ich höre zu“ (Nachfrage ohne Namen, läuft in 6 s ab, nach „Ja?“ in 12 s – hoert_dauer). Darunter läuft mit, was er gerade sagt – im Takt der
// Wiedergabe: Jedes Textstück erscheint, wenn der Ton, der vor ihm ankam, abgespielt ist.
const feld = { text: "", wartend: [], seit: 0, schaetzEnde: 0 };
const jetztS = () => performance.now() / 1000;
function feldZeitpunkt(text) {
  const c = stimme.ctx;
  if (c && lautsprecher && c.state === "running") return jetztS() + Math.max(0, stimme.naechste - c.currentTime);
  const t = Math.max(jetztS(), feld.schaetzEnde);
  feld.schaetzEnde = t + (text?.length ?? 0) / 15;
  return t;
}
function nestorText(d) {
  if (d.neu) feld.schaetzEnde = 0;
  feld.wartend.push({ ...d, t: feldZeitpunkt(d.text) });
  feldTakt();
}
function feldTakt() {
  const jetzt = jetztS();
  let geaendert = false;
  while (feld.wartend.length && feld.wartend[0].t <= jetzt + 0.02) {
    const d = feld.wartend.shift();
    if (d.neu) feld.text = "";
    // ein Stück eines Realtime-Transkripts (delta) direkt anhängen, sonst – und nach einer Floskel – mit Leerzeichen
    const direkt = d.delta && feld.letztesDelta;
    feld.text += direkt || !feld.text ? d.text : ` ${d.text.trimStart()}`;
    feld.letztesDelta = !!d.delta;
    feld.seit = jetzt; geaendert = true;
  }
  if (geaendert && zustand) nestorZeileRendern(zustand);
}
setInterval(feldTakt, 80);
setInterval(() => { if (zustand) nestorZeileRendern(zustand); }, 500);
function nestorStopp() { // Hineinreden, Sprechtaste oder „Stopp“: was noch nicht zu hören war, erscheint auch nicht
  feld.wartend = [];
  if (feld.text && !feld.text.endsWith("…")) feld.text += " …";
  if (zustand) nestorZeileRendern(zustand);
}
const spricht = () => feld.wartend.length > 0 || (!!stimme.ctx && stimme.naechste > stimme.ctx.currentTime + 0.05);
function nestorZeileRendern(z) {
  const a = z.assistent ?? {};
  const aktiv = z.laeuft || z.simulation || z.hoeren;
  const name = a.name ?? "Nestor";
  const redet = spricht();
  const hoertNoch = a.hoert_bis ? a.hoert_bis - z.zeit : 0;
  const arbeitet = !!a.bogen || ["angesprochen", "denkt", "recherchiert"].includes(a.zustand);
  const zeile = $("nestor-zeile");
  zeile.className = `nestor-zeile${arbeitet ? " arbeitet" : ""}${redet ? " spricht" : ""}${hoertNoch > 0 && !redet && !arbeitet ? " hoert" : ""}`
    + `${a.taste ? " taste" : ""}${a.zustand === "pausiert" || !a.aktiv ? " aus" : ""}`;
  zeile.style.setProperty("--rest", String(Math.max(0, Math.min(1, hoertNoch / (a.hoert_dauer || 15)))));
  const basis = basisStufe(z);
  let text;
  if (!aktiv) text = name;
  else if (!a.aktiv || knopfdruck(z)) text = `${name} · auf Knopfdruck`;
  else if (a.zustand === "pausiert") text = `${name} hört nicht mit`;
  else if (a.taste) text = "Ich höre – loslassen zum Senden";
  else if (redet) text = `${name} spricht`;
  else if (a.bogen) text = `Bin dran: ${a.bogen.name}`;
  else if (arbeitet) text = `${name} ${NESTOR_TEXT[a.zustand] ?? "denkt nach …"}`;
  else if (hoertNoch > 0) text = "Ich höre zu – fragt ruhig nach";
  else if (a.zustand === "begruessung") text = `${name} begrüßt die Runde`;
  else text = basis ? `${name} hört mit · Sprechtaste halten zum Fragen` : `${name} hört mit · „${name}, …“ zum Fragen`;
  $("nz-zustand").textContent = text;
  const frisch = redet || jetztS() - feld.seit < 8;
  $("nz-gesagt").textContent = frisch ? feld.text : "";
  $("nz-gesagt").hidden = !frisch || !feld.text;
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
  // Modus (Ticket #1); im Modus „Auf Knopfdruck“ ersetzt die Knopfleiste die Nestor-Leiste (Ticket #6)
  $("modus-pill").hidden = !z.modus;
  document.querySelector(".nestor-wahl").hidden = knopfdruck(z); // Nestor spricht dort nicht
  // „eigener Schlüssel“ (Ticket #17, entschlackte Kopfleiste) steht hier statt in einer eigenen Pille
  const eigenerSchluessel = z.schluessel?.quelle === "dashboard";
  $("modus-pill").textContent = (z.stufe === "basis" ? `Basis${z.modus === "knopfdruck" ? " · Nur auf Knopfdruck" : ""}` : "Premium")
    + (eigenerSchluessel ? " · eigener Schlüssel" : "");
  $("modus-pill").dataset.tip = (z.stufe === "basis" ? "Nestor Basis: alle KI-Dienste von Mistral AI (Frankreich), Verarbeitung in der EU"
    : "Nestor Premium: OpenAI, Gespräch und Live-Bild")
    + (eigenerSchluessel ? " – die KI-Kosten dieses Meetings laufen über deinen eigenen OpenAI-Schlüssel" : "");
  $("modus-wechseln").hidden = z.hoeren; // Wechsel nur außerhalb eines laufenden Meetings
  $("btn-mikro").hidden = !z.hoeren;
  $("btn-mikro").classList.toggle("an", !!z.stumm);
  $("btn-mikro").replaceChildren(icon(z.stumm ? "mikroAus" : "mikro"));
  $("btn-mikro").dataset.tip = z.stumm ? "Mikro ist stumm – klicken, damit Nestor wieder zuhört" : "Mikro stumm schalten – nichts wird gehört oder ausgewertet";
  $("fehler").hidden = !z.fehler; $("fehler").textContent = z.fehler ?? "";
  // Mikrofon: welche Quelle hört gerade, und kommt überhaupt Ton an?
  const m = z.mikro ?? {};
  const handyVerbunden = !!z.handys;
  const handyBereit = handyVerbunden && m.quelle === "handy" && m.luecke != null && m.luecke <= 3 && z.lautsprecher === "handy";
  $("btn-start").disabled = !handyBereit;
  const startHinweis = !handyVerbunden ? "Erst Handy verbinden"
    : m.quelle !== "handy" ? "Am Handy Mikrofon aktivieren"
    : m.luecke == null || m.luecke > 3 ? "Warte auf Handy-Audio"
    : "Am Handy Ton aktivieren";
  $("btn-start").textContent = handyBereit ? "Meeting starten" : startHinweis;
  $("handy-empfehlung").classList.toggle("verbunden", handyBereit);
  $("handy-empfehlung").hidden = handyVerbunden;
  $("handy-bereitschaft").hidden = !handyVerbunden;
  $("handy-bereitschaft").textContent = handyBereit
    ? "✓ Handy bereit – Mikrofon und Ton sind verbunden. Du kannst das Meeting starten."
    : `Handy gekoppelt – ${startHinweis}. Tippe am Handy oben auf „Mikrofon und Ton aktivieren“.`;
  $("handy-empfehlung-text").textContent = handyBereit
    ? "Bereit: Das Handy übernimmt Mikrofon und Ton. Lege es in die Tischmitte, lass den Bildschirm offen und starte das Meeting hier."
    : handyVerbunden ? "Handy verbunden. Tippe dort auf „Dieses Handy übernimmt Mikro und Ton“ und erlaube das Mikrofon. Danach wird der Meetingstart freigeschaltet."
    : "1. QR-Code scannen. 2. Am Handy Mikrofon und Ton einschalten. 3. Meeting hier starten. Keine Anmeldung oder App nötig. Lege das Handy in die Tischmitte.";
  $("btn-handy-vorbereitung").textContent = handyVerbunden ? "Verbindung anzeigen" : "Handy verbinden";
  // Handy verbunden (gekoppelt, Seite offen) – auch bevor es Mikro und Ton übernimmt
  $("btn-mikro-quelle").hidden = z.simulation || (!m.quelle && !z.handys) || (!z.hoeren && m.quelle !== "handy" && !z.handys);
  $("mq-text").textContent = m.quelle === "handy" ? "Mikro: Handy"
    : m.quelle === "laptop" && z.hoeren ? "Mikro: Laptop" : `Handy verbunden${z.handys > 1 ? ` (${z.handys})` : ""}`;
  $("btn-mikro-quelle").dataset.tip = m.quelle === "handy" ? "Das Handy hört zu – klicken zum Zurückholen" : "Der Laptop hört zu – klicken, um ein Handy zu koppeln";
  $("hf-laptop").hidden = !(z.hoeren && !z.simulation && m.quelle !== "laptop");
  $("mq-text").textContent += z.lautsprecher ? ` · Ton: ${z.lautsprecher === "handy" ? "Handy" : "Laptop"}` : "";
  // Nestor ohne Lautsprecher (Tab zu, Handy neu geladen): sichtbar machen und hier übernehmen lassen
  $("ton-fehlt").hidden = !(z.hoeren && z.assistent?.aktiv && !z.lautsprecher) || knopfdruck(z);
  $("mikro-weg").hidden = !m.weg;
  $("mikro-weg").textContent = !m.weg ? "" : m.quelle === null
    ? "Kein Mikrofon verbunden – Nestor hört nichts. Am Handy „Dieses Handy übernimmt Mikro und Ton“ tippen oder hier zurückholen (Handy-Symbol)."
    : `Seit ${Math.round(m.luecke)} s kein Ton vom ${m.quelle === "handy" ? "Handy – ist es gesperrt oder die App im Hintergrund?" : "Laptop-Mikrofon."}`;

  // Nestor
  const a = z.assistent;
  const nestorDa = a?.aktiv && z.hoeren && !knopfdruck(z);
  knopfRendern(z);
  $("nestor").hidden = !nestorDa;
  $("btn-fragen").hidden = !nestorDa || a.zustand === "pausiert" || basisStufe(z); // Basis: Sprechtaste
  $("btn-still").hidden = !nestorDa || !["spricht", "denkt", "recherchiert", "gespraech", "begruessung"].includes(a.zustand);
  $("btn-fortsetzen").hidden = !nestorDa || a.zustand !== "pausiert";
  if (nestorDa) {
    $("nestor").className = `nestor ${a.zustand}`;
    $("nestor-zustand").textContent = `${a.name} ${NESTOR_TEXT[a.zustand] ?? a.zustand}`;
  }
  // Band (Ticket #27): Regel-Hinweise und stille Angebote, je mit höchstens einem Knopf
  bandRendern(z, $("band"));
  arbeitRendern(z);

  if (!vorbereitung) liveRendern(z);
  leisteRendern(z);
  kostenRendern(z);
  schluesselRendern(z);
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

  // Regeln als Ampeln (Zeit steht nur links); kommen schon verlässlich-vorn sortiert aus regel_status
  // (Backend, einzige Quelle: coach/regeln.py). Räumlich getrennt wie die Kacheln in der Einrichtung
  // (Ticket #10): Beta-Ampeln stehen unter einer eigenen kleinen Überschrift.
  const ampel = (r) => el("div", { class: `ampel ${r.farbe}`,
    "data-tip": (r.detail || r.titel) + (r.stufe === "experimentell" ? ` – ${r.kurzsatz}` : "") },
    el("span", { class: "a-icon" }, icon(r.id)),
    el("strong", {}, r.titel, ...(r.stufe === "experimentell" ? [konfSchild()] : [])),
    el("span", { class: "detail" }, r.detail));
  const regelStatus = z.regel_status ?? [];
  const beta = regelStatus.filter((r) => r.stufe === "experimentell");
  $("regel-ampeln").replaceChildren(
    ...regelStatus.filter((r) => r.stufe !== "experimentell").map(ampel),
    ...(beta.length ? [el("p", { class: "etikett ampel-beta-titel" }, "Beta"), ...beta.map(ampel)] : []));
  $("erinnerungen").replaceChildren(...(z.regeln ?? []).map((t) => el("span", { "data-tip": "Erinnerung – wird nicht geprüft" }, t)));
  // Ticket #27: nicht gewählte Regeln sind unsichtbar – ohne Regeln keine Karte
  $("regeln-karte").hidden = !regelStatus.length && !(z.regeln ?? []).length;

  // Redeanteile, ohne Bewertung
  const anteile = Object.entries(z.redeanteile).sort((x, y) => y[1] - x[1]);
  const summe = anteile.reduce((s, [, x]) => s + x, 0) || 1;
  $("redeanteile").replaceChildren(...(anteile.length ? anteile.map(([wer, sek]) => el("div", { class: wer === "Person ?" ? "balken unsicher" : "balken",
    "data-tip": wer === "Person ?" ? `${mmss(sek)} min nicht sicher zuzuordnen – zu kurz oder mehrere gleichzeitig` : `${mmss(sek)} min gesprochen` },
    el("span", {}, wer.replace("Person ", "P ")),
    el("span", { class: "spur" }, Object.assign(el("span"), { style: `width:${(sek / summe) * 100}%` })),
    el("span", { class: "wert" }, `${Math.round((sek / summe) * 100)} %`))) : [el("span", { class: "leise-text" }, "Noch niemand erkannt.")]));

  nestorZeileRendern(z);
  verlaufRendern(z);
}

function leisteRendern(z) {
  $("leiste").hidden = !leisteOffen;
  $("btn-transkript").classList.toggle("an", leisteOffen);
  if (!leisteOffen) return;
  $("reiter-transkript").classList.toggle("aktiv", reiter === "transkript");
  $("reiter-hinweise").classList.toggle("aktiv", reiter === "hinweise");
  $("transkript").hidden = reiter !== "transkript";
  $("hinweise").hidden = reiter !== "hinweise";
  const tr = $("transkript");
  const unten = tr.scrollTop + tr.clientHeight >= tr.scrollHeight - 20;
  const zeilen = z.segmente.map((s) => el("li", {},
    el("span", { class: "wann" }, mmss(s.start)), el("span", { class: "wer" }, s.sprecher), el("span", {}, s.text)));
  if (z.teiltext) zeilen.push(el("li", { class: "teiltext" }, el("span", { class: "wann" }, "live"), el("span"), el("span", {}, z.teiltext)));
  // Knopfdruck: kein Live-Transkript – sagen, was noch kommt, statt leer zu bleiben
  if (knopfdruck(z) && z.hoeren && z.knopf?.seit_sekunden) {
    zeilen.push(el("li", { class: "teiltext" }, el("span", { class: "wann" }, "offen"), el("span"),
      el("span", {}, `auf Knopfdruck – ${knopfOffenText(z.knopf).replace("noch nicht ausgewertet", "werden beim nächsten Knopf transkribiert")}`)));
  } else if (knopfdruck(z) && !zeilen.length) {
    zeilen.push(el("li", { class: "teiltext" }, el("span", { class: "wann" }), el("span"), el("span", {}, "auf Knopfdruck")));
  }
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
  $("e-monolog").value = e.monolog_sekunden;
  $("e-bild-anbieter").value = e.bild_anbieter;
  $("e-live-art").value = e.live_art;
  $("e-aufnahme").checked = !!e.aufnahme;
  $("e-live-hinweis").hidden = e.live_art !== "sparsam";
  // Basis: nur Mistral – Gesprächsart, Stimme, Bildweg und der OpenAI-Schlüssel gehören zu Premium
  const basis = e.stufe === "basis";
  document.querySelectorAll("#einstellungen .nur-premium").forEach((x) => { x.hidden = basis; });
  $("e-premium-schluessel").hidden = basis;
  $("e-basis-hinweis").hidden = !basis;
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
    if (d.typ === "stimme_stopp") { stimme.stopp(); return nestorStopp(); }
    if (d.typ === "nestor_text") return nestorText(d);
    if (d.typ === "pegel") { pegelAnzeigen(d.wert); return; }
    if (d.typ === "knopf") { knopfMeldung(d); return; }
    zustand = d; formAusServer(d); rendern(); einstellungenRendern(d.einstellungen);
  };
  ws.onclose = () => setTimeout(verbinden, 1000);
}

// Start: Icons setzen, Formular vorbelegen, Regeln, Szenarien und Aufnahmen laden
(async () => {
  iconSetzen("btn-fragen", "frage"); iconSetzen("btn-still", "stopp"); iconSetzen("btn-fortsetzen", "weiter");
  iconSetzen("btn-transkript", "transkript"); iconSetzen("btn-mehr", "mehr");
  // btn-handy/btn-einstellungen stecken jetzt im „Mehr“-Menü mit sichtbarem Label (Ticket #17) – Icon davor, Label bleibt stehen
  $("btn-einstellungen").prepend(icon("einstellungen")); $("btn-handy").prepend(icon("handy"));
  iconSetzen("kosten-icon", "muenze"); iconSetzen("leiste-zu", "zu");
  document.querySelector("#btn-taste .i").replaceChildren(icon("mikro"));
  verlaufVerdrahten({ buehne: $("vl-buehne"), zaehler: $("vl-zaehler"), zurueck: $("vl-zurueck"), vor: $("vl-vor"), neu: $("vl-neu") });
  $("f-titel").value = "Testmeeting";
  agendaPunkte = [
    { titel: "Ziel und Ablauf klären", ziel: "Gemeinsames Verständnis, worüber heute entschieden wird", minuten: 2 },
    { titel: "Hauptthema", ziel: "Optionen sammeln und bewerten", minuten: 5 },
    { titel: "Nächste Schritte", ziel: "Wer macht was bis wann", minuten: 2 },
  ];
  agendaInit();
  const rk = await fetch("/api/regeln").then((r) => r.json());
  regelkatalog = rk.katalog; regelwahl(rk.standard);
  personZeile(); personZeile();
  const [szenarien, aufnahmen] = await Promise.all([fetch("/api/szenarien").then((r) => r.json()), fetch("/api/aufnahmen").then((r) => r.json())]);
  $("f-szenario").replaceChildren(...szenarien.map((n) => el("option", { value: n }, n)));
  $("f-aufnahme").replaceChildren(...aufnahmen.map((n) => el("option", { value: n }, n)));
  $("zeile-aufnahme").hidden = !aufnahmen.length;
  verbinden();
})();
