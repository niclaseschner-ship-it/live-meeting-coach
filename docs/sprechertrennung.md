# Sprechertrennung: Stand und Messungen (05./06.10.2026)

„Wer spricht“ ist die Basis für Redeanteile, Monolog, Ins-Wort-Fallen, Überlappung und Gesprächsklima.
Bis zum 05.10. war sie nur an Saal-, Studio- und Zoom-Aufnahmen gemessen (94–96 % richtig). Mit dem AMI-Korpus
(vier echte Besprechungen, vier Personen, ein Tischmikrofon – unser Einsatzfall) zeigte sich: Im Raum ist es
deutlich schwerer. Dieses Dokument hält fest, was wir gemessen und warum wir so entschieden haben.

## Werkzeuge

- `scripts/bench_sprecher.py` – genau der Live-Code gegen die Sprecher-Referenz; richtig / falsch / „?“.
- `scripts/sprecher_labor.py` – Fingerabdrücke einmal je Modell berechnen, dann Strategien in Sekunden messen.
- `scripts/sprecher_labor_zuege.py` – Genauigkeit nach Länge der Beiträge, Abweichung der Redeanteile.
- `scripts/sprecher_labor_segment.py` – Segmentierung (pyannote 3.0) mit „Person ?“ und Überlappung.
- `scripts/ami_laden.py` – AMI-Sitzungen als Proben mit Sprechern, Themen und Beschlüssen.

## Was wir gelernt haben

1. **Nicht das Stimmmodell ist der Engpass.** Von vier Modellen bleibt CAM++ das beste. Selbst mit bekannten
   Stimmen aller Personen (simulierte Vorstellungsrunde) kamen feste Fenster nur auf ~67 %. Die Obergrenze bei
   perfekter Zuordnung jedes Fensters lag bei 64–75 %.
2. **Verloren geht es an der Zerlegung:** 15–17 % der Sprechzeit in AMI sind Überlappung, rund die Hälfte der
   Beiträge ist kürzer als 1 s („yeah“, „mm-hmm“), und 1,5-s-Fenster überdecken Sprecherwechsel.
3. **Nach Beitragslänge** (AMI, feste Fenster): ab 30 s 74–94 % richtig, 10–30 s 76–89 %, 3–10 s 63–73 %,
   unter 3 s 16–43 %. Redeanteile weichen je Person um höchstens 4–8 Prozentpunkte ab. Für Redeanteile und
   Monolog reicht das, für Ins-Wort-Fallen und Überlappung nicht.
4. **Segmentierung** (pyannote segmentation 3.0, MIT, 6 MB, lokal): erkennt Überlappung direkt im Signal
   (Schwelle 0,3 auf „zwei gleichzeitig“: gut die Hälfte der Überlappungszeit gefunden, 70 % der Meldungen echt).
   Für die Frage „wer“ war sie auf sauberen Aufnahmen schlechter als feste Fenster (Zoom 87 % statt 95 %, zwei
   Personen verschmolzen).
5. **Mischform** (jetzt Standard, `LMC_SEGMENTIERUNG_ART=misch`): Personen aus den bewährten Fenstern,
   Überlappung aus der Segmentierung, Überlappungsstellen als „Person ?“. Ergebnis:

| Probe | heute falsch | Mischform falsch | Mischform „?“ |
|---|---|---|---|
| Stadtrat | 0,4 % | 0,4 % | 6,4 % |
| Talkshow „Unter Vier“ | 3,5 % | 1,8 % | 6,2 % |
| Zoom-Meeting | 1,7 % | 1,5 % | 4,4 % |
| AMI a–d (Tischmikrofon) | 17–28 % | 8–15 % | 26–34 % |

   Falsche Zuordnungen halbieren sich im Raum; dafür steht ehrlich „Person ?“, wo zwei gleichzeitig sprechen oder
   es unklar ist – so mit Niclas vereinbart.

6. **„Person ?“ statt raten** (`LMC_STIMM_UNSICHER`, jetzt 0,4): Fenster, die zu keiner bekannten Person mindestens
   so ähnlich sind, werden nicht mehr der nächstbesten zugeschlagen. AMI a: falsch 13,1 → 9,2 %, d: 14,7 → 13,8 %;
   Stadtrat, Talkshow und Zoom unverändert (0,2–1,6 % falsch).
7. **Personenzahl begrenzen schadet:** Mit bekannter Teilnehmerzahl als Obergrenze wurde AMI d deutlich schlechter
   (37 % statt 53 % richtig) – frühe Fehlzuordnungen belegen die Plätze. Die Obergrenze bleibt deshalb aus; die
   Vorstellungsrunde dient Namen und Personenzahl in der Anzeige, nicht als harte Grenze.

## Gesprächsdynamik und Klima

Aus der Forschung zu „Hot Spots“ und Konflikten in Besprechungen (Wrede & Shriberg 2003; Kim et al. 2012):
die stärksten Signale sind die Rate von Überlappungen und Unterbrechungen, dazu Lautstärke und Ton.
Der Coach zählt jetzt Vorfälle gleichzeitigen Sprechens und das Ins-Wort-Fallen (gesamt und je 10 min) und
bildet daraus ein Klima für die letzten 3 Minuten (ruhig / lebhaft / hitzig, `coach/analyse.py: klima`).
Erste Probe ohne KI-Kosten: Talkshow 22× gleichzeitig, 12× ins Wort, meist „hitzig“; Stadtrat 3× gleichzeitig,
0× ins Wort, meist „ruhig“. Gewichte und Stufen sind Startwerte und werden im Raumtest kalibriert.

### Nachjustiert nach den Testläufen vom 06.10.

- **Vorfall erst ab 1 s gleichzeitigem Sprechen.** Kürzere Überlappungen sind meist Zustimmung („ja“, „mhm“) oder
  Saalhall. Ohne Mindestdauer zählte der Stadtrat Koblenz so viele „Vorfälle“ wie die Talkshow (je 10 min 18,6 zu
  19,2), weil der Hall der Saalanlage wie eine zweite Stimme wirkt. Ab 1 s: Talkshow 8,3, Koblenz 3,5, Wahlcheck 2,1,
  Hoyerswerda 1,7, Anhörung/Podium/Bürgerversammlung 0–0,5. In Koblenz fielen damit die Überlappungs-Hinweise von
  30 auf 7 und „hitzig“ fast ganz weg.
- **Erkennung echter Vorfälle im Besprechungsraum** (AMI b–d, Referenz ≥ 1 s): 41–68 % der echten Vorfälle werden
  gefunden, 84–86 % der gemeldeten sind echt. Zählen ist damit brauchbar, wenn auch eher zu niedrig.
- **„Hitzig“ braucht Lautstärke oder rauen Ton.** Die freundlichen, aber lebhaften AMI-Designbesprechungen haben
  25–30 echte Überlappungen je 10 min – mehr als die Talkshow – und standen deshalb oft auf „hitzig“. Viel Überlappung
  heißt Engagement, nicht Konflikt (passt zur Forschung: Konflikt = Überlappung plus erhobene Stimme oder negative
  Sprache). Überlappung und Unterbrechung allein reichen jetzt höchstens für „lebhaft“.
- **Der Gruppen-Hinweis „Mehrere Personen sprechen gleichzeitig“** kommt erst bei mindestens zwei Vorfällen in einer
  Minute; einzelne erscheinen nur im Zähler (synthetische Kontrollrunde: vorher ein Hinweis bei null Vorfällen).

## Vorstellungsrunde

Nach der Begrüßung bittet Nestor, reihum kurz den Namen zu sagen (`LMC_VORSTELLUNG_SEKUNDEN`, Standard 45 s).
Aus „Ich bin Lea“ wird für die erkannte Stimme der Name, auch rückwirkend im Transkript. Im Labor bringt die
Vorstellungsrunde für die Genauigkeit nur wenige Punkte, dafür richtige Personenzahl und Namen.

## Offen

- Raumtest mit Freisprecheinrichtung statt Laptop-Mikrofon – der billigste Hebel, nicht simulierbar.
- Kurze Wechsel (< 3 s) bleiben schwach; „Ausreden lassen“ ist deshalb als experimentell markiert.

## Transkriptzeilen je Sprecher (06.10., nach dem Raumtest)

Im Raumtest mit Hörbuch gingen die Stimmen nahtlos ineinander über. Eine Äußerung, wie die Pausenerkennung sie
schneidet, enthielt dann mehrere Sprecher. Das Transkript zeigte trotzdem nur die überwiegende Person und nie
„Person ?“, obwohl die Sprecherspur „Person ?“ schon kannte (10 s im Raumtest). Jetzt wird die Zeile an den
Sprecherwechseln geteilt (`text_aufteilen` in `coach/hoeren.py`):

- Abschnitte unter 1 s bekommen keine eigene Zeile.
- Weil der Live-Text keine Wortzeiten liefert, wird der Text nach Sprechzeit aufgeteilt. Die Grenze liegt auf dem
  nächsten Satzende, wenn eines in der Nähe ist, sonst auf der nächsten Wortgrenze.
- Nestor und die Agenda-Ansagen sehen weiter den ganzen Satz.

Synthetische Meetings, richtig zugeordnete Sprechzeit im Transkript: Team-Weekly 83 → 84 % (falsch 2 → 1 %),
Vereinsrunde 72 → 72 % (falsch 14 → 13 %). Die Zeilen mit „Person ?“ sind jetzt sichtbar: 8 von 175 und 10 von 206.

Der größere Fehler in der Vereinsrunde ist ein anderer: Zwei synthetische Stimmen landen als eine Person (4 statt 5
erkannt). Das kann Teilen nicht lösen. Ein Hörbuch mit einer Sprecherin, die Figuren nur verstellt, ist für die
Stimmerkennung grundsätzlich eine einzige Person.
