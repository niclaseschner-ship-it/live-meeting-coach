"use strict";

// ⓘ an jeder Kachel und jeder Regel (Rückmeldung Niclas 11.10.2026): ein Klick erklärt, was dort passiert. Die Texte
// beschreiben, was der Code tut – Schwellen aus coach/config.py, coach/analyse.py und coach/regeln.py. Ändert sich
// dort etwas, hier nachziehen. Ein Knopf <button class="info" data-info="schluessel"> öffnet die Blase; Regeln
// bekommen zusätzlich ihren aktuellen Stand (detail aus regel_status) über data-stand.

const INFO = {
  jetzt: ["Jetzt", "Der Countdown zählt die Zeit, die ihr für diesen Agendapunkt geplant habt. Der Balken zeigt, wie viel davon verbraucht ist. Ist die Zeit um, wird er gelb, ab 10 % darüber rot. Habt ihr die Regel „Zeit einhalten“ gewählt, sagt Nestor das dann im Hinweisband. Wie lange das Meeting schon läuft, steht oben in der Kopfzeile neben „Live“."],
  agenda: ["Agenda", "Eure Punkte mit verbrauchter und geplanter Zeit. Weiter geht es per Klick auf einen Punkt oder mit „Nestor, weiter zum nächsten Punkt“. Merkt Nestor, dass ihr schon beim nächsten Thema seid, fragt er im Hinweisband „Weiter zu …?“. Unter erledigten Punkten steht, was dort beschlossen wurde."],
  nestor: ["Nestor", "Hier steht als Untertitel, was Nestor gerade sagt. Er spricht nur, wenn ihr ihn ansprecht: „Nestor“ und eure Frage, direkt danach geht eine Nachfrage ohne Namen. Wird es euch zu viel, redet einfach rein oder tippt auf Stopp. Von sich aus sagt er nichts, Hinweise erscheinen still im Hinweisband."],
  basis_nestor: ["Nestor", "Hier steht als Untertitel, was Nestor gerade sagt. Nestor Basis funktioniert wie ein Funkgerät: Sprechtaste unten klicken oder halten, sprechen, loslassen. Von sich aus sagt er nichts, Hinweise erscheinen still im Hinweisband."],
  karte: ["Ergebnisse von Nestor", "Alles, was Nestor für euch erarbeitet, erscheint hier als Karte: Antworten, Recherchen, Zusammenfassungen, Überblicke und Bilder. Die neueste steht immer vorn. Mit ‹ › blättert ihr zurück, nichts geht verloren. Habt ihr gerade zurückgeblättert, bleibt die Karte stehen und › zeigt „neu“. Bei einer Recherche stehen die Quellen zum Anklicken dabei."],
  regeln: ["Gesprächsregeln", "Nestor achtet nur auf die Regeln, die ihr beim Einrichten gewählt habt. Grün heißt: alles im Rahmen. Gelb heißt: Nestor hat etwas bemerkt und zeigt einen Hinweis im Band, ohne Namen. Rot gibt es nur beim Ton. Das ⓘ an einer Regel zeigt, worauf Nestor genau achtet und wie es gerade steht. „Beta“ heißt: funktioniert noch nicht in jeder Runde zuverlässig."],
  anteile: ["Redeanteile", "Wie viel Redezeit jede erkannte Stimme hat, umschaltbar zwischen den letzten 5 Minuten und dem ganzen Meeting. Die Namen kommen aus der Vorstellungsrunde, sonst heißt es „Person 1, 2 …“. Was Nestor keiner Stimme sicher zuordnen kann („Person ?“), zählt beim Hinweis nicht mit. Die rote Linie liegt beim 1,5-Fachen des fairen Anteils, bei 3 Personen bei 50 %. Wer in den letzten 5 Minuten darüber liegt, wird orange. Die Zahlen bewerten niemanden."],
  fest: ["Festgehalten", "Entscheidungen (✓), Aufgaben (☐), offene Punkte (?) und Risiken (!) erkennt Nestor aus dem Gespräch. Fehlt etwas, etwa wer eine Aufgabe macht oder bis wann, steht es orange daneben. Mit der Regel „Ergebnisse festhalten“ fragt Nestor beim Punktwechsel gebündelt nach. Ändern, ergänzen oder löschen: „Nestor, bitte …“ → Protokoll. Am Ende wird daraus das Protokoll."],
  // Regeln (ids aus coach/regeln.py)
  thema: ["Beim Thema bleiben", "Nestor ordnet das Gespräch laufend den Agendapunkten zu. Passt es 20 Sekunden lang nicht zum aktuellen Punkt, wird die Regel gelb. Passt es zu einem anderen Punkt, bietet Nestor an, dorthin zu wechseln. Grundlage ist der Live-Text, die KI ordnet ihn zu."],
  alle: ["Alle kommen zu Wort", "Zwei Dinge: Hat nach 10 Minuten jemand aus eurer Teilnehmerliste noch nicht gesprochen, sagt Nestor, wie viele noch still sind, ohne Namen. Und er vergleicht die Redezeit der letzten 5 Minuten: Fair wäre ein gleicher Anteil für alle, bei 3 Personen je 33 %. Hat eine Person mehr als das 1,5-Fache davon, bei 3 Personen also über 50 %, wird die Regel gelb, und das Band fragt ohne Namen: „Was sagen die anderen?“ Gewertet wird erst ab anderthalb Minuten Gespräch, höchstens ein Hinweis alle 5 Minuten."],
  ton: ["Respektvoller Ton", "Nestor achtet im Live-Text auf Kraftausdrücke und auf Sätze, die als persönlicher Angriff ankommen könnten. Dann wird die Regel für 2 Minuten rot, und die Moderation sieht die Stelle. Nestor sagt dazu nichts laut und nennt keine Namen."],
  ausreden: ["Ausreden lassen (Beta)", "Nestor zählt, wenn jemand das Wort übernimmt, während noch gesprochen wird: ohne Pause, und die neue Person spricht mindestens 3 Sekunden weiter. Ab 3 solchen Stellen in 5 Minuten kommt ein Hinweis. Gelb wird die Regel schon bei der ersten Stelle oder wenn oft mehrere gleichzeitig sprechen. Beta, weil es in Runden mit vielen Zwischenrufen Fehlalarme gibt."],
  ergebnisse: ["Ergebnisse festhalten", "Nestor erkennt Entscheidungen, Aufgaben, offene Punkte und Risiken. Fehlt bei einem davon, wer es macht, bis wann oder ob es beschlossen ist, fragt er beim Punktwechsel gebündelt nach. Gelb bleibt die Regel, solange eine nachgefragte Lücke offen ist."],
};

const infoBlase = { offen: null };

function infoZeigen(knopf) {
  const blase = document.getElementById("info-blase");
  const eintrag = INFO[knopf.dataset.info];
  if (!blase || !eintrag) return;
  document.querySelectorAll(".info.an").forEach((x) => x.classList.remove("an"));
  knopf.classList.add("an");
  infoBlase.offen = knopf;
  document.getElementById("info-titel").textContent = eintrag[0];
  document.getElementById("info-text").textContent = eintrag[1];
  const stand = document.getElementById("info-stand");
  stand.textContent = knopf.dataset.stand ? `Gerade: ${knopf.dataset.stand}` : "";
  stand.hidden = !knopf.dataset.stand;
  blase.hidden = false;
  const r = knopf.getBoundingClientRect(), b = blase.getBoundingClientRect();
  let x = r.left + r.width / 2 - b.width / 2, y = r.bottom + 8;
  if (y + b.height > innerHeight - 8) y = r.top - b.height - 8;
  x = Math.max(8, Math.min(x, innerWidth - b.width - 8));
  blase.style.left = `${x}px`;
  blase.style.top = `${Math.max(8, y)}px`;
}

function infoSchliessen() {
  const blase = document.getElementById("info-blase");
  if (blase) blase.hidden = true;
  document.querySelectorAll(".info.an").forEach((x) => x.classList.remove("an"));
  infoBlase.offen = null;
}

document.addEventListener("click", (e) => {
  const knopf = e.target.closest?.(".info[data-info]");
  if (knopf) {
    e.stopPropagation();
    if (infoBlase.offen === knopf) infoSchliessen(); else infoZeigen(knopf);
    return;
  }
  if (infoBlase.offen && (!e.target.closest?.("#info-blase") || e.target.closest?.("#info-zu"))) infoSchliessen();
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") infoSchliessen(); });
