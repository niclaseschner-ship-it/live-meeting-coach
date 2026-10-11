// Stufe A: Die Gesten des gemeinsamen Sprechknopf-Bedienmodells (static/basis.js: sprechknopf) –
// Klick (< 300 ms) schaltet um (Aufnahme läuft weiter, zweiter Klick beendet und sendet), Halten (≥ 300 ms)
// bleibt wie bisher ein Funkgerät. Lädt basis.js unverändert in einen kleinen DOM-/Timer-Stub (kein jsdom nötig,
// Pi ist speicherknapp) – wie tests/js/markdown_lite.test.mjs vorgemacht hat.
//
// Lauf: node --test tests/js/sprechknopf.test.mjs (Node ≥ 18, kein npm-Paket nötig).

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HIER = path.dirname(fileURLToPath(import.meta.url));
const WURZEL = path.resolve(HIER, "..", "..");

// --- Minimaler DOM-Stub: ein Knopf (classList, Attribute, addEventListener) sowie document/window nur mit
// addEventListener (für die optionale Leertaste der Seite bzw. window-blur) – mehr braucht sprechknopf() nicht.
class ZielStub {
  constructor() { this._h = {}; }
  addEventListener(typ, fn) { (this._h[typ] ??= []).push(fn); }
  removeEventListener(typ, fn) { this._h[typ] = (this._h[typ] ?? []).filter((f) => f !== fn); }
  aus(typ, ev = {}) { for (const fn of [...(this._h[typ] ?? [])]) fn(ev); }
}
class KnopfStub extends ZielStub {
  constructor() {
    super();
    this.disabled = false; this.hidden = false;
    this.attrs = {};
    const klassen = new Set();
    this.classList = { toggle: (name, an) => { if (an) klassen.add(name); else klassen.delete(name); },
                        contains: (name) => klassen.has(name) };
  }
  setAttribute(name, wert) { this.attrs[name] = String(wert); }
  setPointerCapture() { /* im Test ohne echten Zeiger nicht gebraucht */ }
}

function sandkasten() {
  const fenster = new ZielStub();
  const dokument = new ZielStub();
  const box = {
    document: dokument, window: fenster, console, performance: { now: () => Date.now() },
    setTimeout, clearTimeout, setInterval, clearInterval,
  };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(WURZEL, "static", "basis.js"), "utf8"), box, { filename: "static/basis.js" });
  return box;
}

const warten = (ms = 15) => new Promise((ok) => setTimeout(ok, ms));
const WAV_LANG = new ArrayBuffer(60000); // deutlich über der Mindestlänge (44 + RATE*2*0,5 Byte)

// Baut einen Sprechknopf mit kontrollierbarer Uhr (o.jetzt) und Zählern für start/ende/senden.
function aufbauen(box, zusatz = {}) {
  const knopf = new KnopfStub();
  let klock = 0;
  const anzeigen = []; // [{text, zustand}]
  const zaehler = { start: 0, ende: 0, senden: 0, abbrechen: 0 };
  const o = {
    anzeige: (text, zustand) => anzeigen.push({ text, zustand }),
    ruhe: () => "Ruhe",
    jetzt: () => klock,
    start: async () => { zaehler.start++; },
    ende: async () => { zaehler.ende++; return WAV_LANG; },
    senden: async () => { zaehler.senden++; return { text: "Ergebnis" }; },
    abbrechen: async () => { zaehler.abbrechen++; },
    ...zusatz,
  };
  const api = box.sprechknopf(knopf, o);
  return { knopf, api, anzeigen, zaehler, vor: (ms) => { klock += ms; } };
}

test("Klick (< 300 ms) schaltet um, Aufnahme läuft weiter – der zweite Klick beendet und sendet, der folgende pointerup löst nichts mehr aus", async () => {
  const box = sandkasten();
  const { knopf, anzeigen, zaehler, vor } = aufbauen(box);

  knopf.aus("pointerdown", { pointerId: 1 });
  assert.equal(knopf.classList.contains("haelt"), true);
  assert.ok(anzeigen.at(-1).text.startsWith("Ich höre"));

  vor(120); // kurzer Klick, < 300 ms
  knopf.aus("pointerup");
  await warten();
  assert.equal(zaehler.ende, 0, "ein kurzer Klick darf die Aufnahme nicht beenden");
  assert.equal(knopf.classList.contains("haelt"), true, "Umschaltmodus: Klasse bleibt „haelt“");
  assert.ok(anzeigen.at(-1).text.startsWith("Ich höre"), "Text muss weiter mit „Ich höre“ beginnen (UI-Vertrag)");
  assert.ok(anzeigen.at(-1).text.includes("nochmal klicken"));

  // der zweite Klick (pointerdown im Umschaltmodus) beendet und sendet
  vor(50);
  knopf.aus("pointerdown", { pointerId: 1 });
  await warten();
  assert.equal(zaehler.ende, 1);
  assert.equal(zaehler.senden, 1);
  assert.equal(knopf.classList.contains("haelt"), false);

  // der pointerup, der auf den zweiten Klick folgt, löst nichts mehr aus
  const vorherAnzeigen = anzeigen.length;
  knopf.aus("pointerup");
  await warten();
  assert.equal(zaehler.ende, 1);
  assert.equal(zaehler.senden, 1);
  assert.equal(anzeigen.length, vorherAnzeigen, "pointerup nach dem zweiten Klick darf nichts mehr anzeigen");
});

test("Halten (≥ 300 ms) sendet wie bisher beim Loslassen", async () => {
  const box = sandkasten();
  const { knopf, zaehler, vor } = aufbauen(box);

  knopf.aus("pointerdown", { pointerId: 1 });
  vor(500); // echtes Halten
  knopf.aus("pointerup");
  await warten();
  assert.equal(zaehler.ende, 1);
  assert.equal(zaehler.senden, 1);
});

test("pointerleave beendet nur im Halte-Modus – nicht mehr, wenn schon umgeschaltet ist", async () => {
  const box = sandkasten();
  const { knopf, zaehler, vor } = aufbauen(box);

  // Fall 1: pointerleave während eines echten Haltens (Maus verlässt den Knopf, Taste noch unten) beendet
  knopf.aus("pointerdown", { pointerId: 1 });
  vor(50);
  knopf.aus("pointerleave");
  await warten();
  assert.equal(zaehler.ende, 1, "pointerleave muss ein laufendes Halten beenden");

  // Fall 2: nach einem kurzen Klick (Umschaltmodus) darf pointerleave nichts mehr tun
  knopf.aus("pointerdown", { pointerId: 1 });
  vor(100);
  knopf.aus("pointerup"); // < 300 ms → Umschaltmodus
  await warten();
  assert.equal(zaehler.ende, 1, "noch keine zweite Beendigung durch den Klick selbst");
  knopf.aus("pointerleave");
  await warten();
  assert.equal(zaehler.ende, 1, "pointerleave darf den Umschaltmodus nicht beenden");
  assert.equal(knopf.classList.contains("haelt"), true, "die Aufnahme läuft im Umschaltmodus unverändert weiter");
});

test("window-blur beendet nur im Halte-Modus – im Umschaltmodus bleibt die Aufnahme unberührt", async () => {
  const box = sandkasten();
  const { zaehler, vor, knopf } = aufbauen(box);

  knopf.aus("pointerdown", { pointerId: 1 });
  vor(100);
  knopf.aus("pointerup"); // < 300 ms → Umschaltmodus
  await warten();
  assert.equal(zaehler.ende, 0);

  box.window.aus("blur");
  await warten();
  assert.equal(zaehler.ende, 0, "blur im Umschaltmodus darf die Aufnahme nicht beenden");
  assert.equal(knopf.classList.contains("haelt"), true);
});

test("pointercancel beendet immer – im Halte-Modus wie im Umschaltmodus", async () => {
  const box = sandkasten();
  const { knopf, zaehler, vor } = aufbauen(box);

  knopf.aus("pointerdown", { pointerId: 1 });
  vor(100);
  knopf.aus("pointerup"); // Umschaltmodus
  await warten();
  assert.equal(zaehler.ende, 0);

  knopf.aus("pointercancel");
  await warten();
  assert.equal(zaehler.ende, 1, "pointercancel muss auch im Umschaltmodus beenden");
});

test("Obergrenze (o.hoechstens_ms) beendet automatisch und sendet", async () => {
  const box = sandkasten();
  const { knopf, zaehler } = aufbauen(box, { hoechstens_ms: 30 });

  knopf.aus("pointerdown", { pointerId: 1 });
  await warten(90); // über die Obergrenze hinaus warten (reale Timer)
  assert.equal(zaehler.ende, 1);
  assert.equal(zaehler.senden, 1);
  assert.equal(knopf.classList.contains("haelt"), false);
});

test("zu kurze Aufnahme (unter einer halben Sekunde WAV) wird abgebrochen, nicht gesendet", async () => {
  const box = sandkasten();
  const { knopf, zaehler, vor, anzeigen } = aufbauen(box, { ende: async () => { zaehler.ende++; return new ArrayBuffer(100); } });

  knopf.aus("pointerdown", { pointerId: 1 });
  vor(400); // ein echtes Halten, aber am Ende eine winzige WAV (z. B. abgerissenes Mikrofon)
  knopf.aus("pointerup");
  await warten();
  assert.equal(zaehler.senden, 0);
  assert.ok(anzeigen.at(-1).text.toLowerCase().includes("zu kurz"));
});
