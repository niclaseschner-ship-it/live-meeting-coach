"use strict";

// Abschlussseite (Lastenheft 2 Schritt 5, 4.4–4.6): Paket, Unterstützung, Datenspende und Feedback.

let letzterStand = null;
let nachlademen = null;

async function laden() {
  const r = await fetch("/api/abschluss");
  if (!r.ok) {
    $("ab-leer").hidden = false;
    $("ab-kopf").hidden = true;
    $("ab-inhalt").hidden = true;
    return;
  }
  letzterStand = await r.json();
  $("ab-leer").hidden = true;
  $("ab-kopf").hidden = false;
  $("ab-inhalt").hidden = false;
  kopfDarstellen(letzterStand);
  darstellen(letzterStand);
  dokumentDarstellen();
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function dokumentHtml() {
  const d = letzterStand?.dokument;
  if (!d) return "<p>Das Dokument wird noch erstellt …</p>";
  const gruppe = (titel, key, felder) => {
    const xs = d[key] ?? [];
    const zeilen = xs.length ? xs.map((x) => `<li>${felder.map((f) => x[f]
      ? esc(x[f]) : `<strong class="dok-luecke">${esc(f)} fehlt</strong>`).join(" · ")}</li>`).join("") : "<li>Keine</li>";
    return `<h3>${titel}</h3><ul>${zeilen}</ul>`;
  };
  let h = `<h1>${esc(d.kopf?.titel || "Meeting")}</h1><p>${esc(d.kopf?.datum || "")} · ${Math.round((d.kopf?.dauer_sekunden || 0)/60)} Minuten</p>`;
  h += gruppe("Entscheidungen", "entscheidungen", ["was","status","wer"]);
  h += gruppe("Aufgaben", "aufgaben", ["was","wer","bis"]);
  h += gruppe("Offene Punkte", "offene_punkte", ["was","wer","bis"]);
  h += gruppe("Risiken", "risiken", ["was","wer","reaktion"]);
  h += gruppe("Parkplatz", "parkplatz", ["was"]);
  h += `<h3>Agenda</h3><ul>${(d.agenda ?? []).map((p) => `<li>${esc(p.nr)}. ${esc(p.titel)} – ${esc(p.soll_minuten)} min geplant, ${esc(p.ist_minuten)} min genutzt</li>`).join("") || "<li>Keine</li>"}</ul>`;
  if ($("dok-regeln").checked) {
    const r = letzterStand.regelanalyse ?? {};
    h += `<h3>Regelanalyse</h3><h4>Redeanteile</h4><ul>${Object.entries(r.redeanteile ?? {}).map(([n,s]) => `<li>${esc(n)}: ${Math.round(s)} s</li>`).join("") || "<li>Keine Daten</li>"}</ul>`;
    h += `<h4>Hinweise</h4><ul>${(r.hinweise ?? []).map((x) => `<li>${Math.floor(x.zeit/60)}:${String(Math.round(x.zeit%60)).padStart(2,"0")} · ${esc(x.text)}</li>`).join("") || "<li>Keine Hinweise</li>"}</ul>`;
  }
  return h;
}
function dokumentDarstellen() { $("ab-dokument").innerHTML = dokumentHtml(); }
$("dok-regeln").onchange = dokumentDarstellen;
$("btn-kopieren").onclick = async () => {
  const html = dokumentHtml(); const text = $("ab-dokument").innerText;
  try {
    await navigator.clipboard.write([new ClipboardItem({"text/html": new Blob([html], {type:"text/html"}), "text/plain": new Blob([text], {type:"text/plain"})})]);
    $("dok-meldung").textContent = "Formatiert kopiert.";
  } catch { await navigator.clipboard.writeText(text); $("dok-meldung").textContent = "Als Text kopiert."; }
  $("dok-meldung").hidden = false;
};
$("btn-drucken").onclick = () => window.print();

// Abschluss-Kopf (Ticket #17 Punkt 3): „Danke! 11 Minuten · 4 Punkte · 2 Entscheidungen“
function kopfDarstellen(z) {
  const minuten = Math.max(1, Math.round(z.dauer_sekunden / 60));
  const teile = [`${minuten} Minute${minuten === 1 ? "" : "n"}`];
  if (z.punkte) teile.push(`${z.punkte} Punkt${z.punkte === 1 ? "" : "e"}`);
  if (z.entscheidungen) teile.push(`${z.entscheidungen} Entscheidung${z.entscheidungen === 1 ? "" : "en"}`);
  $("ab-kopfzeile-text").textContent = `Danke! ${teile.join(" · ")}`;
}

function darstellen(z) {
  const eigenerSchluessel = !!z.eigener_schluessel;
  const eurText = z.kosten_eur.toLocaleString("de-DE", { minimumFractionDigits: 2 });
  $("ab-kosten-satz").textContent = eigenerSchluessel
    ? `Die KI-Kosten dieses Meetings (${eurText} €) liefen über euren eigenen Schlüssel.`
    : `Dieses Meeting hat Niclas ${eurText} € an KI-Kosten gekostet.`;

  // Eigener Schlüssel: kein Kostenausgleich mit Stufen, nur der allgemeine Link ohne Betrag (Lastenheft 4.5)
  $("ab-stufen-block").hidden = eigenerSchluessel;
  $("ab-eigener-hinweis").hidden = !eigenerSchluessel || !z.paypal_allgemein;
  if (eigenerSchluessel && z.paypal_allgemein) {
    $("ab-eigener-link").textContent = z.paypal_allgemein;
    $("ab-eigener-link").href = z.paypal_allgemein;
  }
  $("ab-unterstuetzung").hidden = eigenerSchluessel ? !z.paypal_allgemein : !z.paypal;
  if (!eigenerSchluessel && z.paypal) {
    $("ab-kacheln").replaceChildren(...z.paypal.map((s) =>
      el("button", { class: "ab-kachel", type: "button", onclick: () => betragWaehlen(s) },
        el("strong", {}, `${s.betrag} €`), el("span", {}, s.bedeutung))));
  }

  const fertig = z.ablage_fertig;
  $("ab-paket-hinweis").hidden = fertig;
  $("btn-paket").disabled = !fertig;
  $("ab-spende-hinweis").hidden = fertig;
  spendeKnopfAktualisieren();

  clearTimeout(nachlademen);
  if (!fertig) nachlademen = setTimeout(laden, 3000); // bis die Ablage fertig ist, alle 3 s erneut fragen
}

async function betragWaehlen(s) {
  $("ab-gewaehlt").hidden = false;
  $("ab-gewaehlt-betrag").textContent = `${s.betrag} €`;
  $("ab-gewaehlt-link").textContent = s.link;
  $("ab-gewaehlt-link").href = s.link;
  const r = await fetch(`/api/abschluss/qr.svg?betrag=${s.betrag}`);
  $("ab-qr").innerHTML = r.ok ? await r.text() : "";
}

$("btn-paket").onclick = () => {
  const mit = $("pk-aufnahme").checked ? 1 : 0;
  location.href = `/api/abschluss/paket.zip?aufnahme=${mit}`;
};

function spendeKnopfAktualisieren() {
  const fertig = !letzterStand || letzterStand.ablage_fertig;
  $("btn-spende").disabled = !$("sp-einverstanden").checked || !fertig;
}
$("sp-einverstanden").onchange = spendeKnopfAktualisieren;

$("btn-spende").onclick = async () => {
  await api("/api/abschluss/spende", {
    einverstanden: $("sp-einverstanden").checked,
    aufnahme: $("sp-aufnahme").checked,
    feedback: $("fb-text").value.trim(),
  });
  $("sp-danke").hidden = false;
  $("btn-spende").disabled = true;
};

$("btn-fertig").onclick = async () => {
  try {
    await api("/api/abschluss/fertig");
  } finally {
    location.href = "/";
  }
};

laden();
