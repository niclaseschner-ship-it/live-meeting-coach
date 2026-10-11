// Ticket #84, Stufe A: Der Markdown-lite-Renderer für Kartendetails (static/verlauf.js: mdInline, mdLeichtKnoten,
// mitbenutzt von karteBauen) baut nur DOM-Knoten über el() – nie innerHTML. Dieser Test lädt die echten
// Browser-Dateien (basis.js, verlauf.js) unverändert in einen kleinen DOM-Stub (kein jsdom nötig, Pi ist
// speicherknapp) und prüft mit bösartigem Eingabetext (<script>, <img onerror>, javascript:), dass daraus nie ein
// script- oder img-Element bzw. ein ausführbarer Link entsteht – der Text bleibt Text.
//
// Lauf: node --test tests/js/markdown_lite.test.mjs (Node ≥ 18, kein npm-Paket nötig).

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HIER = path.dirname(fileURLToPath(import.meta.url));
const WURZEL = path.resolve(HIER, "..", "..");

// --- Minimaler DOM-Stub: genug für el() (document.createElement/createTextNode, append, setAttribute, className,
// addEventListener) und die instanceof-Prüfung in el(). Baut keine HTML-Strings, nur ein Objektbäumchen.
class VNode {}
class VText extends VNode {
  constructor(text) {
    super();
    this.nodeType = 3;
    this.text = String(text);
  }
}
class VElement extends VNode {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = String(tag).toLowerCase();
    this.attrs = {};
    this.children = [];
  }
  set className(wert) { this.attrs.class = wert; }
  get className() { return this.attrs.class ?? ""; }
  setAttribute(name, wert) { this.attrs[name] = String(wert); }
  addEventListener() { /* im Test nicht gebraucht */ }
  append(...kinder) { for (const k of kinder) this.children.push(k); }
}
const vdocument = { createElement: (tag) => new VElement(tag), createTextNode: (t) => new VText(t) };

// basis.js und verlauf.js sind klassische Skripte (kein Modul) – im selben vm-Kontext hintereinander ausgeführt
// teilen sie sich dieselbe globale lexikalische Umgebung, genau wie zwei <script>-Tags auf einer Seite. Top-Level
// `function`-Deklarationen (mdInline, mdLeichtKnoten, karteBauen – anders als `const el = …`) landen dabei als
// Eigenschaften auf dem Sandkasten-Objekt und sind von hier aus aufrufbar.
function sandkasten() {
  const box = { document: vdocument, Node: VNode, console };
  vm.createContext(box);
  for (const datei of ["static/basis.js", "static/verlauf.js"]) {
    const quelle = fs.readFileSync(path.join(WURZEL, datei), "utf8");
    vm.runInContext(quelle, box, { filename: datei });
  }
  return box;
}

function alleTags(knoten, aus = new Set()) {
  if (knoten.nodeType === 1) {
    aus.add(knoten.tagName);
    for (const kind of knoten.children) alleTags(kind, aus);
  }
  return aus;
}

function allerText(knoten) {
  if (knoten.nodeType === 3) return knoten.text;
  return knoten.children.map(allerText).join("");
}

function alleAttribute(knoten, aus = []) {
  if (knoten.nodeType === 1) {
    aus.push(knoten.attrs);
    for (const kind of knoten.children) alleAttribute(kind, aus);
  }
  return aus;
}

const BOESARTIG = ["<script>alert(1)</script>", '<img src=x onerror="alert(1)">', "javascript:alert(2)"];

// --- mdInline: nur **fett**, alles andere Text -----------------------------------------------------------------
test("mdInline macht aus bösartigem Text innerhalb von ** nur ein strong mit Textinhalt", () => {
  const { mdInline } = sandkasten();
  for (const boese of BOESARTIG) {
    const knoten = mdInline(`**${boese}**`);
    const huelle = { nodeType: 1, tagName: "x", attrs: {}, children: [...knoten] };
    assert.deepEqual(alleTags(huelle), new Set(["x", "strong"]));
    assert.equal(allerText(huelle), boese); // unverändert als Text, nie als Markup
  }
});

test("mdInline ohne ** lässt bösartigen Text unverändert als reinen Text stehen", () => {
  const { mdInline } = sandkasten();
  const text = `Vorher ${BOESARTIG[0]} nachher`;
  const knoten = mdInline(text);
  assert.ok(knoten.every((k) => k.nodeType === 3)); // nur Textknoten, kein einziges Element
  assert.equal(knoten.map((k) => k.text).join(""), text);
});

// --- mdLeichtKnoten: Zwischenüberschrift, Listen, Absätze – mit bösartigem Inhalt --------------------------------
test("mdLeichtKnoten baut aus bösartigem Markdown-Text nie ein script- oder img-Element", () => {
  const { mdLeichtKnoten } = sandkasten();
  const text = [
    `Kernsatz mit ${BOESARTIG[0]} drin.`,
    "",
    `### Zwischenüberschrift ${BOESARTIG[1]}`,
    `- **Wichtig**: ${BOESARTIG[1]}`,
    `- Link: [klick](${BOESARTIG[2]})`,
    "1. Erster Punkt",
    "2. Zweiter Punkt",
    "",
    `Absatz mit ${BOESARTIG[2]} als reiner Text.`,
  ].join("\n");
  const bloecke = [...mdLeichtKnoten(text)];
  const huelle = { nodeType: 1, tagName: "x", attrs: {}, children: bloecke };
  const tags = alleTags(huelle);
  for (const verboten of ["script", "img", "a", "iframe", "svg"]) {
    assert.ok(!tags.has(verboten), `unerwartetes <${verboten}> aus bösartigem Markdown`);
  }
  assert.deepEqual(tags, new Set(["x", "p", "h4", "ul", "li", "strong", "ol"]));
  // kein Attribut (href, src, onerror, …) trägt je einen der bösartigen Werte – es gibt im Baum schlicht keine
  // Attribute außer der eigenen "class" der Listen, die der Renderer selbst setzt
  for (const attrs of alleAttribute(huelle)) {
    for (const wert of Object.values(attrs)) {
      assert.ok(!BOESARTIG.some((b) => wert.includes(b)), `bösartiger Wert im Attribut: ${wert}`);
    }
  }
  const text_gesamt = allerText(huelle);
  for (const boese of BOESARTIG) assert.ok(text_gesamt.includes(boese)); // als Text da, nicht stillschweigend entfernt
});

test("mdLeichtKnoten: Reihenfolge und Form (Zwischenüberschrift, Liste, Absatz) stimmen für harmlosen Text", () => {
  const { mdLeichtKnoten } = sandkasten();
  const bloecke = [...mdLeichtKnoten("Kernsatz zuerst.\n\n### Einzelheiten\n- **Median**: 11 Euro\n- **Trend**: steigend")];
  assert.deepEqual([...bloecke].map((b) => b.tagName), ["p", "h4", "ul"]);
  assert.equal(allerText(bloecke[0]), "Kernsatz zuerst.");
  assert.equal(allerText(bloecke[1]), "Einzelheiten");
  assert.equal([...bloecke[2].children].length, 2);
  assert.equal(bloecke[2].children[0].tagName, "li");
});

// --- Karte als Ganzes: dieselbe Behandlung für alle Kartenarten, nicht nur Recherche ------------------------------
test("karteBauen: eine bösartige Recherche-Karte (Titel, Frage, Stichpunkte, Quelle, Details) bleibt überall Text", () => {
  const { karteBauen } = sandkasten();
  const karte = {
    id: 1, art: "recherche", zeit: 0,
    titel: `${BOESARTIG[0]} Titel`,
    frage: `${BOESARTIG[1]} Frage`,
    punkte: [`**Preis**: ${BOESARTIG[0]}`],
    details: `Kernsatz.\n- **Wichtig**: ${BOESARTIG[1]}`,
    quellen: [{ titel: `${BOESARTIG[0]} Quelle`, url: BOESARTIG[2], seite: "x" }],
  };
  const artikel = karteBauen(karte, {});
  const tags = alleTags(artikel);
  for (const verboten of ["script", "iframe", "svg"]) assert.ok(!tags.has(verboten));
  assert.ok(!tags.has("img")); // kein <img> aus dem bösartigen Text (die Quelle erzeugt nur <a>, keine Bilder)
  // Die einzige echte Quelle für ein href ist die Quellen-Zeile – ihr Wert ist genau die (harmlose) API-URL und
  // steht nie als ausführbares Markup, sondern nur als Attributwert
  const hrefs = alleAttribute(artikel).map((a) => a.href).filter(Boolean);
  assert.deepEqual(hrefs, [BOESARTIG[2]]); // als String-Attribut, nicht navigiert, nicht interpretiert
  const text = allerText(artikel);
  assert.ok(text.includes(BOESARTIG[0]) && text.includes(BOESARTIG[1])); // als Text sichtbar, nicht verschluckt
});
