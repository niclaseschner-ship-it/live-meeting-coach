"use strict";

// Feedback-Knopf (Ticket #18, Nachtrag Niclas): auf jeder Seite erreichbar – Startseite, Dashboard, Abschluss –
// unabhängig vom Meetingzustand, auch während eines laufenden Meetings. Baut sich selbst in die Seite ein, damit
// er nicht in jeder HTML-Datei einzeln gepflegt werden muss. Nutzt dieselben Klassen wie style.css (klappfenster,
// primaer, icon), das auf jeder Seite schon eingebunden ist.

(function () {
  function bauen() {
    const knopf = document.createElement("button");
    knopf.id = "fb-schwebend";
    knopf.className = "icon fb-schwebend";
    knopf.setAttribute("data-tip", "Feedback, Funktionswunsch oder Fehler melden");
    knopf.setAttribute("aria-label", "Feedback geben");
    knopf.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M21 11.5a8.4 8.4 0 0 1-1.1 4.2L21 20l-4.4-1.1a8.4 8.4 0 1 1 4.4-7.4Z"/></svg>'
      + '<span>Feedback</span>';  // mit Wort, nicht nur Symbol – soll auf Anhieb verständlich sein (Niclas, 08.10.)

    const fenster = document.createElement("div");
    fenster.id = "fb-fenster";
    fenster.className = "klappfenster fb-fenster";
    fenster.hidden = true;
    fenster.innerHTML =
      '<h3>Feedback</h3>' +
      '<label>Worum geht es? <select id="fb-art">' +
      '<option value="feedback">Feedback</option>' +
      '<option value="funktionswunsch">Funktionswunsch</option>' +
      '<option value="fehler">Fehler</option>' +
      '</select></label>' +
      '<label>Nachricht <textarea id="fb-nachricht" rows="3" placeholder="Was willst du uns sagen?"></textarea></label>' +
      '<button id="fb-senden" class="primaer">Senden</button>' +
      '<p id="fb-dank" class="leise-text" hidden>Danke! Wir lesen das.</p>';

    document.body.append(knopf, fenster);

    knopf.onclick = () => { fenster.hidden = !fenster.hidden; };
    document.addEventListener("click", (e) => {
      if (!fenster.hidden && !fenster.contains(e.target) && !knopf.contains(e.target)) fenster.hidden = true;
    });

    const nachricht = fenster.querySelector("#fb-nachricht");
    const dank = fenster.querySelector("#fb-dank");
    fenster.querySelector("#fb-senden").onclick = async () => {
      const text = nachricht.value.trim();
      if (!text) return;
      const art = fenster.querySelector("#fb-art").value;
      try {
        await fetch("/api/feedback", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ art, text, seite: location.pathname }),
        });
      } catch {
        // Keine Verbindung: dem Feedback keinen Aufwand mehr widmen, einfach schließen
      }
      nachricht.value = "";
      dank.hidden = false;
      setTimeout(() => { fenster.hidden = true; dank.hidden = true; }, 1800);
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bauen);
  else bauen();
})();
