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
}

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
