# Live Meeting Coach

KI-gestützte, hierarchieneutrale Begleitung für Besprechungen (Hackathon, isb Open Innovation).
Der Coach macht Agenda, Zeit, Fokus und die vereinbarten Gesprächsregeln sichtbar und
unterstützt die menschliche Moderation, ohne sie zu ersetzen.

## MVP

Ein Dashboard bzw. Co-Pilot **ohne Sprachausgabe**. Priorisiert sind:

- **Monologe:** Hinweis, wenn jemand länger als etwa 4 Minuten am Stück spricht
- **Agenda und Zeit:** Ampel pro Tagesordnungspunkt
- **Fokusverlust:** Gespräch driftet vom aktuellen Punkt ab
- **Gesprächsregeln spiegeln:** z. B. Ins-Wort-Fallen

Später: Sprachausgabe, Konfliktmoderation, Kulturdiagnostik.

## Technischer Ansatz (Arbeitshypothese)

1. **Zuhören:** Transkription mit Sprechertrennung in Blöcken, einige Sekunden Verzug genügen
2. **Denken:** Analysatoren (Redezeit, Agenda, Fokus, Regeln) und ein Entscheider, der Hinweise auswählt
3. **Ausgabe:** Dashboard im Browser

Für den Prototyp zunächst eine Cloud-Variante (OpenAI), danach abspecken.
Eine Realtime-Stimme mit Funktionsaufrufen ist als Ausbaustufe vorgemerkt.

## Offene Fragen

- Wer sieht welche Hinweise?
- Wie werden Schwellen gesetzt?
- Wie wird Beteiligung interpretiert?
- Datenschutz und Freigabe für Audio in der Cloud
- Qualität der deutschen Transkription und der Sprechertrennung im Raum
- Lässt sich Ins-Wort-Fallen aus blockweiser Diarisierung erkennen?
- Mikrofon: Laptop-Array mit Rauschfilter, Handy oder Konferenzmikro

## Mitmachen

Ideen und Aufgaben bitte als [Issue](../../issues) anlegen.
