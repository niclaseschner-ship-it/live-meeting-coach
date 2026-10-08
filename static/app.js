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
let hinweisWeg = 0; // id des zuletzt weggeklickten Hinweises

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
$("btn-still").onclick = () => { stimme.stopp(); nestorStopp(); api("/api/assistent/stopp"); };
$("btn-fortsetzen").onclick = () => api("/api/assistent/fortsetzen");
$("btn-transkript").onclick = () => { leisteOffen = !leisteOffen; rendern(); };
$("leiste-zu").onclick = () => { leisteOffen = false; rendern(); };
$("reiter-transkript").onclick = () => { reiter = "transkript"; rendern(); };
$("reiter-hinweise").onclick = () => { reiter = "hinweise"; rendern(); };
$("reiter-nestor").onclick = () => { reiter = "nestor"; rendern(); };
$("karte-zu").onclick = () => { feld.zu = true; feldRendern(); };
// Kopfleiste entschlackt (Ticket #17 Punkt 4): Handy koppeln und Einstellungen stecken im „Mehr“-Menü – beides
// seltene, vorbereitende Aktionen statt Aktionen je Minute. Ein Klick darauf wählt aus und schließt das Menü.
$("btn-mehr").onclick = () => { $("mehr-menu").hidden = !$("mehr-menu").hidden; $("kosten").hidden = $("einstellungen").hidden = $("handy-fenster").hidden = true; };
$("btn-einstellungen").onclick = () => { $("mehr-menu").hidden = true; $("einstellungen").hidden = !$("einstellungen").hidden; $("kosten").hidden = $("handy-fenster").hidden = true; };
$("btn-kosten").onclick = () => { $("kosten").hidden = !$("kosten").hidden; $("einstellungen").hidden = $("mehr-menu").hidden = true; if (zustand) kostenRendern(zustand); };
$("btn-schluessel").onclick = (e) => { e.stopPropagation(); $("einstellungen").hidden = false; $("s-eingabe").focus(); };
$("hinweis-zu").onclick = () => { hinweisWeg = zustand?.hinweise.at(-1)?.id ?? 0; rendern(); };
// Basis: kein Bildmodell – der Knopf schreibt den Überblick neu; Premium: Live-Bild (Knopfdruck gibt es nur in Basis)
$("btn-bild").onclick = () => (basisStufe(zustand) ? knopfDruecken("ueberblick")
  : zustand?.modus === "knopfdruck" ? knopfDruecken("bild") : api("/api/onepager"));
$("btn-folie").onclick = () => api("/api/folie");
$("tab-bild").onclick = () => { ansicht = "bild"; if (zustand) bildRendern(zustand); };
$("tab-folie").onclick = () => { ansicht = "folie"; if (zustand) bildRendern(zustand); };
$("tab-ueberblick").onclick = () => { ansicht = "ueberblick"; if (zustand) bildRendern(zustand); };
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
$("btn-handy").onclick = () => { $("mehr-menu").hidden = true; handyFensterZeigen(); };
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
  if (!$("mehr-menu").hidden && !$("mehr-menu").contains(e.target) && !$("btn-mehr").contains(e.target)) $("mehr-menu").hidden = true;
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

// ---------- Live-Bild ----------
let bildVersion = 0;
let ansicht = "bild"; // Live-Bild, Überblick (Text) oder Recherche-Folie
let folieVersion = 0;
let ueberblickVersion = 0;
const basisStufe = (z) => z?.stufe === "basis";

// Überblick als Text (Ticket #13): Kopf, Agenda, Entschieden / Offen / Aufgaben / Außerhalb, Neu seit dem letzten Stand
function ueberblickBauen(u) {
  const liste = (eintraege, leer, zeile) => eintraege.length ? el("ul", {}, ...eintraege.map((e) => el("li", {}, ...zeile(e))))
    : el("p", { class: "ub-leer" }, leer);
  const block = (klasse, zeichen, titel, inhalt) => el("section", { class: `ub-block ${klasse}` },
    el("h4", {}, el("span", { class: "ub-zeichen", "aria-hidden": "true" }, zeichen), titel), inhalt);
  $("ueberblick").replaceChildren(
    el("div", { class: "ub-kopf" },
      el("div", {}, el("h3", {}, u.titel), ...(u.kernaussage ? [el("p", { class: "ub-kern" }, u.kernaussage)] : []),
        ...(u.fokus ? [el("p", { class: "ub-fokus" }, `Fokus: ${u.fokus}`)] : [])),
      el("div", { class: "ub-stand" }, el("strong", {}, `Stand ${u.laufzeit}`), ...(u.punkt ? [el("span", {}, `jetzt ${u.punkt}`)] : []))),
    ...(u.agenda?.length ? [el("ol", { class: "ub-agenda" }, ...u.agenda.map((p) =>
      el("li", { class: p.status }, el("b", {}, String(p.nr)), p.titel)))] : []),
    el("div", { class: "ub-raster" },
      block("gruen", "✅", "Entschieden", liste(u.entschieden, "Noch nichts ausdrücklich beschlossen.", (e) => [e.was])),
      block("bernstein", "🟡", "Offen", liste(u.offen, "Keine offenen Fragen genannt.", (e) => [e.was])),
      block("blau", "📌", "Aufgaben", liste(u.aufgaben, "Noch keine Aufgaben verteilt.", (a) => [a.was,
        el("small", {}, ` – ${a.wer ?? "wer: offen"}${a.bis ? ` · bis ${a.bis}` : ""}`)])),
      block("grau", "↪", "Außerhalb der Agenda", liste(u.ausserhalb, "Keine Abschweifung.", (a) => [
        ...(a.zeit ? [el("small", {}, `${a.zeit} `)] : []), a.was]))),
    el("p", { class: "ub-neu" }, el("strong", {}, "Neu seit dem letzten Stand: "), u.neu.join(" · ")),
  );
}
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
  if (!z.onepager_version && bildVersion) { // Bild verworfen (Knopfdruck „verwerfen“): wieder der Platzhalter
    bildVersion = 0;
    $("live-bild").hidden = true; $("bild-leer").hidden = false; $("btn-bild-png").disabled = true;
    $("btn-bild-analyse").hidden = true;
  }
  if (z.onepager_version && z.onepager_version !== bildVersion) {
    bildVersion = z.onepager_version; ansicht = "bild"; // neues Live-Bild wird gezeigt
    const img = $("live-bild");
    img.onload = () => { img.hidden = false; $("bild-leer").hidden = true; $("btn-bild-png").disabled = false; };
    img.src = `${z.onepager_format === "png" ? "/api/onepager.png" : "/api/onepager.svg"}?v=${bildVersion}`;
    $("btn-bild-analyse").hidden = false;
  }
  // Recherche-Folie und Überblick: neue werden sofort gezeigt; Umschalter, sobald es mehr als eine Ansicht gibt
  if (z.folie && z.folie_version !== folieVersion) { folieVersion = z.folie_version; folieBauen(z.folie); ansicht = "folie"; }
  if ((z.ueberblick_version ?? 0) !== ueberblickVersion) {
    ueberblickVersion = z.ueberblick_version ?? 0;
    if (z.ueberblick) { ueberblickBauen(z.ueberblick); ansicht = "ueberblick"; } else $("ueberblick").replaceChildren();
  }
  const basis = basisStufe(z);
  if (basis && ansicht === "bild") ansicht = "ueberblick"; // Basis: kein Live-Bild, der Überblick steht an seiner Stelle
  if (ansicht === "folie" && !z.folie) ansicht = basis ? "ueberblick" : "bild";
  if (ansicht === "ueberblick" && !z.ueberblick && !basis) ansicht = "bild";
  const tabs = { bild: !basis, ueberblick: basis || !!z.ueberblick, folie: !!z.folie };
  const mehrere = Object.values(tabs).filter(Boolean).length > 1;
  $("ansicht-wahl").hidden = !mehrere;
  $("bild-titel").hidden = mehrere;
  $("bild-titel").firstChild.textContent = basis ? "Überblick " : "Live-Bild ";
  for (const [art, da] of Object.entries(tabs)) {
    $(`tab-${art}`).hidden = !da; $(`tab-${art}`).classList.toggle("aktiv", ansicht === art);
  }
  $("folie").hidden = ansicht !== "folie";
  $("ueberblick").hidden = !(ansicht === "ueberblick" && z.ueberblick);
  $("ueberblick-arbeitet").hidden = !(z.ueberblick_laeuft && ansicht !== "folie" && (basis || ansicht === "ueberblick"));
  $("live-bild").style.visibility = ansicht === "bild" ? "" : "hidden";
  const leer = (ansicht === "bild" && !bildVersion) || (ansicht === "ueberblick" && !z.ueberblick);
  $("bild-leer").hidden = !leer;
  $("btn-folie").hidden = !z.recherche_da;
  $("btn-folie").disabled = !!z.folie_laeuft;
  $("folie-arbeitet").hidden = !z.folie_laeuft;
  $("bild-arbeitet").hidden = !z.onepager_laeuft;
  if (leer) platzhalterRendern(z);
  // Knopfdruck: das Transkript entsteht erst beim Knopf – zeichnen geht, sobald jemand gesprochen hat
  $("btn-bild").disabled = !!z.onepager_laeuft || !!z.ueberblick_laeuft
    || (knopfdruck(z) ? !z.hoeren || !!z.knopf?.laeuft : !z.segmente.length);
  $("btn-bild").dataset.tip = basis ? "Überblick jetzt neu schreiben (wenige Sekunden)" : "Bild jetzt neu zeichnen (ca. 1–2 min)";
  $("btn-bild-png").hidden = basis;
  if (basis) $("btn-bild-analyse").hidden = true;
  let status = z.onepager_stand != null ? `· Stand ${mmss(z.onepager_stand)}` : "";
  if (z.onepager_fokus) status += ` · Fokus: ${z.onepager_fokus}`;
  if (basis) status = z.ueberblick ? `· Stand ${z.ueberblick.laufzeit}` : "";
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
  const knopf = knopfdruck(z);
  document.querySelectorAll(".bl-tipp, .bl-kann").forEach((e) => { e.hidden = knopf; }); // Ansprache gibt es dort nicht
  if (basisStufe(z) || ansicht === "ueberblick") { // Überblick als Text: kein Bild, das gezeichnet wird
    $("bild-spruch").textContent = z.ueberblick_laeuft ? "Nestor schreibt euren Überblick …"
      : "Hier erscheint euer Überblick: Entschiedenes, Offenes, Aufgaben.";
    const takt = knopf ? 0 : (z.onepager_minuten ?? 0) * 60;
    $("bild-weg").style.width = `${Math.round((takt ? Math.min(1, z.zeit / takt) : 0) * 100)}%`;
    $("bild-weg").parentElement.hidden = !takt;
    $("bild-wann").textContent = knopf ? "Knopf „Überblick“ oben drücken – Nestor transkribiert dann und fasst zusammen."
      : "Knopf „Überblick“ oben oder „Nestor, zeig uns die Übersicht.“"
        + (takt ? ` Sonst alle ${Math.round(takt / 60)} Minuten von selbst.` : "");
    return;
  }
  const spruch = knopf ? "Das Bild entsteht auf Knopfdruck."
    : !z.segmente.length ? SPRUECHE[0] : SPRUECHE[Math.floor(z.zeit / 60) % SPRUECHE.length];
  $("bild-spruch").textContent = z.onepager_laeuft ? "Nestor zeichnet euer erstes Bild …" : spruch;
  const takt = knopf ? 0 : (z.onepager_minuten ?? 0) * 60; // kein Bild im Takt
  const weg = takt ? Math.min(1, z.zeit / takt) : 0;
  $("bild-weg").style.width = `${z.onepager_laeuft ? 100 : Math.round(weg * 100)}%`;
  $("bild-weg").parentElement.hidden = !takt;
  const rest = Math.ceil((takt - z.zeit) / 60);
  $("bild-wann").textContent = z.onepager_laeuft ? "gleich da – ca. 1 Minute"
    : knopf ? "Knopf „Bild“ oben drücken – Nestor transkribiert dann und zeichnet."
    : !takt ? "Das Bild entsteht, sobald ihr es euch wünscht."
    : !z.segmente.length ? `Das erste Bild kommt nach ${Math.round(takt / 60)} Minuten Gespräch.`
    : rest > 1 ? `Das erste Bild kommt in ca. ${rest} Minuten.` : "Das erste Bild kommt gleich.";
}

// ---------- Knöpfe (Ticket #6; seit #13 in beiden Stufen gleich) ----------
// Ein Knopf antwortet sofort; Fortschritt kommt als {typ: "knopf"} über die WebSocket, das Ergebnis als Karte
// (Wo stehen wir, Regeln, Protokoll, Frage) oder im Bildbereich (Überblick, Live-Bild). Mit „Nur auf Knopfdruck“
// (Basis) transkribiert der Knopf vorher den offenen Ton, und es gibt das Verwerfen.
const KNOPF_PFAD = { stand: "/api/knopf/stand", regeln: "/api/knopf/regeln", ueberblick: "/api/knopf/ueberblick",
  protokoll: "/api/knopf/protokoll", bild: "/api/knopf/bild", frage: "/api/knopf/frage" };
const KNOPF_NAME = { stand: "Wo stehen wir?", regeln: "Regeln eingehalten?", ueberblick: "Überblick", protokoll: "Protokoll",
  bild: "Bild", frage: "Nestor fragen" };
Object.assign(KARTEN_ART, { stand: "Wo stehen wir?", regeln: "Regeln", protokoll: "Protokoll", ueberblick: "Überblick" });
Object.assign(KARTEN_ICON, { stand: "zeit", regeln: "ton", protokoll: "ergebnisse", ueberblick: "bild" });
const knopfdruck = (z) => z?.modus === "knopfdruck";
function knopfDruecken(art, daten = {}) {
  if (zustand?.knopf) zustand.knopf = { ...zustand.knopf, laeuft: art, schritt: "transkribiere", anteil: 0, fehler: null };
  knopfRendern(zustand);
  return api(KNOPF_PFAD[art], daten).then(() => true, () => false); // Fehler zeigt api() schon an
}
document.querySelectorAll("#knopf-leiste .knopf-art").forEach((b) => { b.onclick = () => knopfDruecken(b.dataset.knopf); });
$("knopf-frage-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("knopf-frage").value.trim();
  if (!text) return;
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
  const an = !!z.hoeren;
  $("knopf-leiste").hidden = !an;
  if (!an) return;
  const k = z.knopf ?? {};
  const nurKnopf = knopfdruck(z);
  $("knopf-offen").hidden = !nurKnopf; $("knopf-verwerfen").hidden = !nurKnopf;
  $("knopf-offen").textContent = knopfOffenText(k);
  $("knopf-offen").dataset.tip = k.aeusserungen ? `${k.aeusserungen} Äußerungen, ${mmss(k.sprache_sekunden)} min Sprache – werden beim nächsten Knopf transkribiert` : "";
  const laeuft = !!k.laeuft;
  document.querySelectorAll("#knopf-leiste .knopf-art, #knopf-fragen").forEach((b) => {
    b.disabled = laeuft; b.classList.toggle("knopf-aktiv", b.dataset.knopf === k.laeuft);
  });
  $("knopf-fortschritt").hidden = !laeuft;
  if (laeuft) {
    const transkribiert = k.schritt === "transkribiere";
    $("knopf-balken").style.width = `${Math.round((transkribiert ? (k.anteil ?? 0) : 1) * 100)}%`;
    $("knopf-balken").parentElement.classList.toggle("denkt", !transkribiert);
    $("knopf-schritt").textContent = `${KNOPF_NAME[k.laeuft] ?? ""}: ` + (transkribiert
      ? `transkribiere${k.gesamt ? ` ${k.fertig} von ${k.gesamt}` : ""} …` : "Nestor denkt nach …");
  }
  $("knopf-fehler").hidden = laeuft || !k.fehler;
  $("knopf-fehler").textContent = k.fehler ?? "";
}

// ---------- Nestor-Feld (Ticket #21) ----------
// Antworten stehen immer an derselben Stelle und in derselben Form: im mittleren Feld. Was Nestor sagt, läuft mit,
// sobald er spricht (Realtime: Transkript-Stücke, Text-Weg/Basis: der Satz vor seinem Ton) – im Takt der Wiedergabe:
// Jedes Textstück erscheint, wenn der Ton, der vor ihm ankam, abgespielt ist. Danach die Stichpunkte der Karte.
// Dazu das Arbeitssymbol (angesprochen / denkt / recherchiert) und die Warteschlange der Aufträge mit ✕.
const feld = { frage: "", text: "", wartend: [], karte: null, zu: true, fest: false, seit: 0, schaetzEnde: 0 };
let karteGesehen = null;    // höchste Karten-id, die schon im Feld stand
const jetztS = () => performance.now() / 1000;
// Wann ist dieses Textstück zu hören? Spielt dieser Tab den Ton, nach dessen Zeitachse; sonst geschätzt (~15 Zeichen/s)
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
    if (d.neu) Object.assign(feld, { frage: d.frage ?? "", text: "", karte: null, zu: false, fest: false });
    feld.text += d.delta || !feld.text ? d.text : ` ${d.text}`;
    feld.seit = jetzt; geaendert = true;
  }
  if (geaendert) feldRendern();
}
setInterval(feldTakt, 80);
function nestorStopp() { // Hineinreden oder „still“: was noch nicht zu hören war, erscheint auch nicht
  feld.wartend = [];
  if (feld.text && !feld.text.endsWith("…")) feld.text += " …";
  feldRendern();
}
const spricht = () => feld.wartend.length > 0 || (!!stimme.ctx && stimme.naechste > stimme.ctx.currentTime + 0.05);
function karteZeigen(k, automatisch) {
  feld.karte = k; feld.zu = false; feld.fest = !automatisch; feld.seit = jetztS();
  if (!automatisch || !feld.text) { feld.frage = k.frage && k.frage !== k.titel ? k.frage : ""; feld.text = ""; }
  feldRendern();
}
function karteFuellen(k) {
  $("karte-art").textContent = KARTEN_ART[k.art] ?? "Nestor";
  $("karte-zeit").textContent = mmss(k.zeit);
  $("karte-titel").textContent = k.titel;
  $("karte-punkte").replaceChildren(...(k.punkte ?? []).map((p) => el("li", {}, p)));
  const q = k.quellen ?? [];
  $("karte-quellen").hidden = !q.length;
  $("karte-quellen").replaceChildren(el("strong", {}, "Quellen"), ...q.map((x) => el("div", {},
    el("a", { href: x.url, target: "_blank", rel: "noopener" }, x.titel), " ", el("small", {}, x.seite))));
  $("karte-folie").hidden = k.art !== "folie";
  $("karte-protokoll").hidden = k.art !== "protokoll" || !zustand?.knopf?.protokoll;
  $("karte-folie").onclick = () => { folieBauen(k.folie); ansicht = "folie"; feld.zu = true; if (zustand) bildRendern(zustand); feldRendern(); };
}
const ARBEITET = ["angesprochen", "denkt", "recherchiert"];
const AUFTRAG_ZUSTAND = { laeuft: "läuft", wartet: "wartet" };
function feldRendern() {
  const z = zustand; if (!z) return;
  const a = z.assistent ?? {};
  const aktiv = z.laeuft || z.simulation || z.hoeren;
  const auftraege = a.auftraege ?? [];
  const arbeitet = !!a.aktiv && ARBEITET.includes(a.zustand);
  const redet = spricht();
  const frisch = feld.fest || redet || jetztS() - feld.seit < 60;  // automatisch Gezeigtes tritt nach 1 min zurück
  const inhalt = !feld.zu && frisch && !!(feld.text || feld.karte);
  const zeigen = !!aktiv && (arbeitet || auftraege.length > 0 || inhalt);
  $("nestor-feld").hidden = !zeigen;
  if (!zeigen) return;
  const laeuft = auftraege.some((x) => x.zustand === "laeuft");
  $("nestor-feld").className = `nestor-feld${arbeitet || laeuft ? " arbeitet" : ""}${redet ? " spricht" : ""}`;
  const name = a.name ?? "Nestor";
  $("nf-zustand").textContent = arbeitet ? `${name} ${NESTOR_TEXT[a.zustand]}` : redet ? `${name} spricht`
    : laeuft ? `${name} arbeitet …` : name;
  $("nf-frage").textContent = inhalt && feld.frage ? `„${feld.frage}“` : "";
  $("nf-frage").hidden = !$("nf-frage").textContent;
  $("karte-zu").hidden = !inhalt;
  // Warteschlange: läuft / wartet, jede Aufgabe per ✕ abbrechbar (oder „Nestor, lass die Recherche“)
  $("nf-auftraege").hidden = !auftraege.length;
  $("nf-auftraege").replaceChildren(...auftraege.map((x) => el("li", { class: x.zustand },
    el("span", { class: "nf-chip" }, AUFTRAG_ZUSTAND[x.zustand] ?? x.zustand),
    el("strong", {}, x.name), el("span", { class: "nf-auftrag-titel" }, x.titel ? `„${x.titel}“` : ""),
    el("button", { class: "icon klein", "data-tip": `${x.name} abbrechen`, "aria-label": `${x.name} abbrechen`,
      onclick: () => api("/api/assistent/abbrechen", { id: x.id }) }, icon("zu")))));
  // Text, solange er läuft (oder keine Karte kommt); danach die Karte mit Stichpunkten an derselben Stelle
  const karteStatt = inhalt && feld.karte && !redet;
  $("nf-text").hidden = !inhalt || !feld.text || karteStatt;
  $("nf-text").textContent = feld.text;
  $("karte").hidden = !karteStatt;
  $("karte-zeit").hidden = !karteStatt;
  if (karteStatt) karteFuellen(feld.karte);
}
function kartenRendern(z) {
  const karten = z.karten ?? [];
  const neueste = karten.at(-1);
  if (karteGesehen === null) { karteGesehen = neueste?.id ?? 0; return; } // beim Laden keine alten Karten aufpoppen
  if (neueste && neueste.id > karteGesehen) {
    karteGesehen = neueste.id;
    // Folie und Überblick erscheinen schon groß im Bildbereich
    if (!["folie", "ueberblick"].includes(neueste.art)) karteZeigen(neueste, true);
  }
  if (!karten.length && feld.karte) { feld.karte = null; feld.zu = true; } // neues Meeting
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
  $("btn-fragen").hidden = !nestorDa || a.zustand === "pausiert";
  $("btn-still").hidden = !nestorDa || !["spricht", "denkt", "recherchiert", "gespraech", "begruessung"].includes(a.zustand);
  $("btn-fortsetzen").hidden = !nestorDa || a.zustand !== "pausiert";
  if (nestorDa) {
    $("nestor").className = `nestor ${a.zustand}`;
    $("nestor-zustand").textContent = `${a.name} ${NESTOR_TEXT[a.zustand] ?? a.zustand}`;
  }
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
  feldRendern();
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
  if (v) {
    const vk = signal(z, "agenda_ohne"); // Agendawechsel ohne Ansage: automatisch erkannt, nicht angesagt
    $("vorschlag").replaceChildren(
      el("span", { "data-tip": vk?.stufe === "experimentell" ? vk.kurzsatz : "" },
        `Weiter zu „${v.titel}“?`, ...(vk?.stufe === "experimentell" ? [konfSchild("konf-klein")] : [])),
      el("div", { class: "knoepfe" },
        el("button", { class: "klein primaer", onclick: () => api("/api/punkt", { index: v.punkt }) }, "Ja, weiter"),
        el("button", { class: "klein", onclick: () => api("/api/vorschlag/verwerfen") }, "Nein")));
  }

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

  // Redeanteile, ohne Bewertung
  const anteile = Object.entries(z.redeanteile).sort((x, y) => y[1] - x[1]);
  const summe = anteile.reduce((s, [, x]) => s + x, 0) || 1;
  $("redeanteile").replaceChildren(...(anteile.length ? anteile.map(([wer, sek]) => el("div", { class: wer === "Person ?" ? "balken unsicher" : "balken",
    "data-tip": wer === "Person ?" ? `${mmss(sek)} min nicht sicher zuzuordnen – zu kurz oder mehrere gleichzeitig` : `${mmss(sek)} min gesprochen` },
    el("span", {}, wer.replace("Person ", "P ")),
    el("span", { class: "spur" }, Object.assign(el("span"), { style: `width:${(sek / summe) * 100}%` })),
    el("span", { class: "wert" }, `${Math.round((sek / summe) * 100)} %`))) : [el("span", { class: "leise-text" }, "Noch niemand erkannt.")]));

  dynamikRendern(z);
  bildRendern(z);
}

const KLIMA_HOEHE = { ruhig: 30, lebhaft: 65, hitzig: 100 };
function dynamikRendern(z) {
  const d = z.dynamik;
  if (!d) return;
  const k = d.klima ?? { stufe: "ruhig", gruende: [] };
  const box = $("klima");
  box.className = `klima ${k.stufe}`;
  const thermo = el("span", { class: "thermo" }, el("span"));
  thermo.firstChild.style.height = `${KLIMA_HOEHE[k.stufe] ?? 30}%`;
  // Klima, gleichzeitiges Sprechen und Ausreden lassen je einzeln einstufen statt mit einem Schild fürs
  // ganze Kärtchen (das verwischte, dass es unterschiedliche Zahlen sind, siehe Lastenheft 4.3).
  const kKlima = signal(z, "klima");
  const kGleich = signal(z, "gleichzeitig");
  const kAusreden = signal(z, "ausreden");
  box.dataset.tip = "Letzte 3 Minuten: gleichzeitiges Sprechen, Ins-Wort-Fallen, Lautstärke und Ton"
    + (kKlima?.stufe === "experimentell" ? ` – ${kKlima.kurzsatz}` : "");
  box.replaceChildren(thermo, el("div", {},
    el("div", { class: "stufe" }, k.stufe[0].toUpperCase() + k.stufe.slice(1),
      ...(kKlima?.stufe === "experimentell" ? [konfSchild("konf-klein")] : [])),
    el("div", { class: "gruende" }, k.gruende.length ? k.gruende.join(" · ") : "keine Auffälligkeiten")));
  $("dynamik").replaceChildren(
    el("div", { "data-tip": "Vorfälle, in denen zwei gleichzeitig sprachen (seit Beginn / letzte 10 min)"
        + (kGleich?.stufe === "experimentell" ? ` – ${kGleich.kurzsatz}` : "") },
      el("strong", {}, d.ueberlappungen, ...(kGleich?.stufe === "experimentell" ? [konfSchild("konf-klein")] : [])),
      el("span", {}, `gleichzeitig gesprochen · ${d.ueberlappungen_10min} in 10 min`)),
    el("div", { "data-tip": "Wechsel ohne Pause, nach denen die neue Person das Wort behält (seit Beginn / letzte 10 min)"
        + (kAusreden?.stufe === "experimentell" ? ` – ${kAusreden.kurzsatz}` : "") },
      el("strong", {}, d.unterbrechungen, ...(kAusreden?.stufe === "experimentell" ? [konfSchild("konf-klein")] : [])),
      el("span", {}, `ins Wort gefallen · ${d.unterbrechungen_10min} in 10 min`)));
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
  $("e-bild").value = e.bild_minuten;
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
  iconSetzen("btn-bild", "neu"); iconSetzen("btn-bild-png", "speichern"); iconSetzen("btn-bild-analyse", "datei");
  iconSetzen("kosten-icon", "muenze"); iconSetzen("btn-folie", "folie");
  document.querySelectorAll(".bl-kann li").forEach((li) => li.prepend(icon(li.dataset.icon)));
  iconSetzen("hinweis-zu", "zu"); iconSetzen("leiste-zu", "zu"); iconSetzen("karte-zu", "zu");
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
