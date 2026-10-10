"use strict";

// Phasen-Automat (Ticket #66). Der Server liefert die Phase explizit im Schnappschuss (coach/pipeline.py: phase()):
// vorbereitung | live | abschluss. Hier steht an EINER Stelle, welcher Bereich in welcher Phase auf welchem Gerät
// überhaupt vorkommt – Desktop (index.html) und Handy (handy.html) schalten nur noch darüber, statt die Phase aus
// Nebenmerkmalen (laeuft, segmente, zeit …) zu raten. Maßstab ist szenarien/ui_vertrag.json („bereiche“).
//
// Bereiche, die zusätzlich vom Zustand abhängen (Regeln gewählt? Band hat Inhalt? Wiedergabe?), bekommen ihre
// Bedingung als zweites Argument; sichtbar ist ein Bereich nur, wenn Phase UND Bedingung passen.

const PHASEN = ["vorbereitung", "live", "abschluss"];

const PHASEN_BEREICHE = {
  desktop: {
    "einrichtung": ["vorbereitung"],
    "btn-start": ["vorbereitung"],
    "live": ["live", "abschluss"],          // nach dem Ende bleibt das Bild stehen, bis „Neues Meeting“
    "btn-neu": ["abschluss"],
    "knopf-leiste": ["live"],
    "regeln-zone": ["live"],
    "band": ["live"],
    "btn-stopp": ["live"],
    "btn-kosten": ["live"],
    "btn-transkript": ["live"],
    "leiste": ["live", "abschluss"],
  },
  handy: {
    "mikro-karte": ["vorbereitung", "live"],
    "mikro-vorbereitung": ["vorbereitung"],
    "mikro-erklaerung": ["vorbereitung", "live"],
    "btn-mikro": ["vorbereitung", "live"],
    "btn-stumm": ["live"],
    "ton-fehlt": ["live"],
    "band": ["live"],
    "h-nestor-karte": ["live"],
    "h-verlauf-karte": ["live"],
    "h-transkript-karte": ["live"],
    "h-meeting": ["vorbereitung", "live", "abschluss"],  // im Abschluss nur der Satz „Zusammenfassung am Laptop“
    "btn-start": ["vorbereitung"],
    "btn-stopp": ["live"],
  },
};

// Phase aus dem Serverzustand; ohne Angabe (alter Server, noch kein Zustand) gilt Vorbereitung.
const phaseVon = (z) => (PHASEN.includes(z?.phase) ? z.phase : "vorbereitung");

// Blendet alle Bereiche des Geräts für die Phase ein oder aus. bedingungen: { id: bool } – zusätzliche Bedingung
// je Bereich. Setzt data-phase an <body> (für CSS) und gibt die Phase zurück.
function phaseAnzeigen(phase, geraet, bedingungen = {}) {
  const tabelle = PHASEN_BEREICHE[geraet];
  for (const [id, phasen] of Object.entries(tabelle)) {
    const e = document.getElementById(id);
    if (e) e.hidden = !phasen.includes(phase) || bedingungen[id] === false;
  }
  document.body.dataset.phase = phase;
  return phase;
}
