# Kurzrecherche: Meeting-Artefakte für Nestor

## Kurzfazit

Ich empfehle **vier** eigenständige Artefakte:

1. **Aufgabe**
2. **Entscheidung**
3. **Offener Punkt / offene Frage**
4. **Risiko**

Nur **Risiko** fehlt in Nestors bisheriger Liste und lohnt sich als eigene Klasse. Es unterscheidet sich fachlich klar vom offenen Punkt: Ein Risiko ist ein mögliches zukünftiges Ereignis mit Eintrittswahrscheinlichkeit und Auswirkung; ein Problem ist bereits eingetreten. PMBOK-/PMI-Praxis führt deshalb Risk Register und Issue Log getrennt. [PMI](https://www.pmi.org/learning/library/project-risk-management-success-tool-6078)

Nicht als eigene Artefakte würde ich führen:

- **Parkplatz:** Darstellungsstatus eines offenen Punkts (`quelle = außerhalb Agenda`), kein eigener Inhaltstyp.
- **Vereinbarung:** entweder Entscheidung („Wir arbeiten künftig …“) oder Aufgabe („Wir liefern …“).
- **Information/Ankündigung:** Bestandteil der Zusammenfassung; ohne Zuständigkeit oder Lebenszyklus nichts zu „managen“.
- **Folgetermin:** Aufgabe, solange er vereinbart werden muss; danach Kalendertermin. Optional mit offenen Punkten verknüpfen.
- **Problem/Issue:** zunächst offener Punkt; daraus entstehen Aufgaben oder Entscheidungen. Eine fünfte Klasse lohnt erst, wenn Nestor später ein echtes Issue-Tracking mit Status und Eskalation anbietet.
- **Erkenntnis/Lesson Learned:** in Retrospektiven nützlich, aber zu speziell für den allgemeinen Kern.

## Was Praxis und KI-Werkzeuge erfassen

Protokoll- und Moderationspraxis konzentriert sich auf **Beschlüsse, Aufgaben, Verantwortliche und Termine**. ISO empfiehlt für Resolutionen eine eindeutige Formulierung, Zieltermin und verantwortliche Person; PMI verlangt für Action Items genau einen Owner und ein Fälligkeitsdatum. [ISO Committee Manager Toolkit](https://www.iso.org/files/live/sites/isoorg/files/store/en/PUB100415.pdf), [PMI](https://www.pmi.org/learning/library/four-techniques-facilitate-project-meetings-7249)

Scrum erzeugt nicht automatisch ein allgemeines „Meetingprotokoll“. Relevant sind vielmehr Backlog-Änderungen, Commitments, Impediments und Anpassungen. Das spricht dafür, Ergebnisse semantisch zu erfassen, statt sie an Agenda- oder Scrum-Ereignisse zu koppeln. [Scrum Guide](https://scrumguides.org/scrum-guide.html)

Die Anbieter decken überwiegend dieselbe Basis ab:

- **Teams Facilitator/Copilot:** Aufgaben, Entscheidungen, offene Fragen und Zusammenfassungen; Aufgaben können nach Bestätigung in Planner übernommen werden. [Microsoft](https://support.microsoft.com/en-us/teams/copilot/facilitator-in-microsoft-teams-meetings)
- **Zoom AI Companion:** Zusammenfassung, nächste Schritte und Aufgaben; neuere Workflows können auch Entscheidungen und Risiken strukturieren. [Zoom](https://support.zoom.com/hc/en/article?ampDeviceId=f6ced667-a0aa-4a39-b5c2-c35a08a9ccf7&id=zm_kb&lang=null&onlycontent=1&optimizely_user_id=a916f6f81cd61f75eb1d87620d9ab0df&sysparm_article=KB0057748)
- **Otter:** standardmäßig Themen, Highlights und Action Items; Enterprise-Templates zusätzlich Entscheidungen, Risiken und nächste Schritte. [Otter Standard](https://help.otter.ai/hc/en-us/articles/9156381229079-Meeting-Summary-Overview), [Otter Enterprise](https://help.otter.ai/hc/en-us/articles/17332984641047-Otter-Insights-for-Enterprise)
- **Fireflies:** Takeaways, Next Steps und Action Items; weitere Kategorien über Vorlagen. [Fireflies](https://guide.fireflies.ai/articles/9547055509-fireflies-ai-meeting-summaries)
- **Read:** Action Items, Schlüsselfragen und Entscheidungen; offene Aufgaben werden über Meetings hinweg wieder aufgegriffen. [Read](https://support.read.ai/hc/en-us/articles/49437229480595-Ada-Meeting-Intelligence-Preparation)
- **tl;dv:** Themen und frei konfigurierbare Vorlagen; der Anbieter empfiehlt selbst Entscheidungen sowie Action Items mit Owner und Deadline. [tl;dv](https://intercom.help/tldv/en/articles/5946410-set-up-the-slack-integration)
- **Fathom:** automatische Action Items und frei wählbare Zusammenfassungsvorlagen. [Fathom](https://help.fathom.video/en/articles/3239617)

**Schluss:** Der Markt ist bei Aufgaben stark, aber bei dauerhaft strukturierten Entscheidungen, offenen Fragen und Risiken uneinheitlich. Genau dort kann Nestor mehr bieten als eine bloße Zusammenfassung.

## Empfohlenes Datenmodell

| Artefakt | Erkennungsmerkmale im Gespräch | Pflichtfelder für „vollständig“ | Optionale Felder | Wann gilt es als Lücke? |
|---|---|---|---|---|
| **Aufgabe** | „Ich kümmere mich …“, „Kannst du …?“, „Wir müssen noch …“, „bis Freitag“, „nächster Schritt ist …“ | **Was** – konkrete, verbbasierte Handlung; **wer** – genau eine verantwortliche Person; **bis wann** – Datum oder eindeutig bestimmbarer Zeitpunkt | Ergebnis/Definition of Done, Priorität, Mitwirkende, Abhängigkeiten, Quelle/Transkriptstelle, Status | Handlung erkannt, aber Was, Owner oder Termin fehlt; mehrere Personen sind nur kollektiv verantwortlich; „prüfen/klären/anschauen“ hat kein erkennbares Ergebnis |
| **Entscheidung** | „Wir entscheiden …“, „Dann machen wir …“, „Das ist beschlossen“, „Wir nehmen Variante B“, „Damit ist X vom Tisch“ | **Was gilt**; **Status** – endgültig oder vorläufig; **wer/Gremium hat entschieden** | Begründung, verworfene Alternativen, Geltungsbereich, gültig ab/bis, Review-Datum, Auswirkungen, Quelle | Nur Präferenz oder Vorschlag statt Beschluss; widersprüchliche Aussagen; Entscheidungsträger unklar; „vorläufig“ ohne Review-Zeitpunkt |
| **Offener Punkt / offene Frage** | „Das müssen wir noch klären“, „Weiß jemand …?“, „Da fehlt uns …“, „Nehmen wir mit“, „Parken wir“, „Darauf kommen wir zurück“ | **präzise Frage bzw. ungeklärter Sachverhalt**; **wer klärt oder entscheidet**; **bis wann bzw. bei welchem Termin wird wieder vorgelegt** | Parkplatz-Kennzeichen, benötigte Information, zuständiges Gremium, Abhängigkeiten, Priorität, Quelle | Frage bleibt unbeantwortet und hat weder Owner noch Wiedervorlage; „später“ oder „nächstes Mal“ ohne bestimmbaren Bezug; Parkplatz-Eintrag ohne Disposition |
| **Risiko** | „Wenn X passiert, dann …“, „Es besteht die Gefahr …“, „Das könnte uns verzögern“, „Wir sind abhängig von …“, „Worst Case …“ | **Ursache–Ereignis–Auswirkung**; **Eintrittswahrscheinlichkeit**; **Auswirkungsstärke**; **Risk Owner**; **Reaktion** – vermeiden, reduzieren, übertragen oder bewusst akzeptieren | Frühwarnsignal/Trigger, Eintrittszeitraum, Maßnahme mit eigenem Owner und Termin, Restrisiko, Kategorie, Status | Nur diffuse Sorge; mögliche Auswirkung fehlt; niemand beobachtet das Risiko; hohes Risiko ohne Maßnahme oder ausdrücklich dokumentierte Akzeptanz |

Für Aufgaben entspricht das dem Kern von SMART: spezifisch, zuordenbar, prüfbar und terminiert. Praktische Action-Item-Leitfäden nennen Owner, klare Handlung, Umfang, gewünschtes Ergebnis und Deadline. [Atlassian Action Items](https://www.atlassian.com/work-management/project-collaboration/team-meetings/action-items)

Für Entscheidungen sollte Nestor den **Entscheider** vom Bearbeiter trennen. DACI unterscheidet Driver, Approver, Contributors und Informed und ergänzt Status, Auswirkung, Termin und Ergebnis. Für normale Meetings reicht davon meist „wer durfte entscheiden?“; die vollständige DACI-Matrix wäre zu schwergewichtig. [Atlassian DACI](https://www.atlassian.com/software/confluence/templates/decision/)

Für Risiken empfiehlt PRINCE2 unter anderem Ursache/Ereignis/Auswirkung, Wahrscheinlichkeit, Auswirkung, Owner und Reaktionsplan. [PRINCE2-Risikoregister](https://www.prince2.com/uk/blog/the-risk-register-what-to-include-and-what-to-avoid)

## Was in echten Meetings typischerweise fehlt

Belastbare Zahlen speziell zu „fehlender Owner“ sind überraschend selten. Dafür gibt es klare Befunde zur übergeordneten Follow-up-Lücke:

- In Microsofts Work Trend Index 2023 sagten **55 %**, dass die nächsten Schritte am Meetingende unklar seien; **56 %** fanden es schwierig, das Geschehen zusammenzufassen. Grundlage war eine internationale Befragung von 31.000 Beschäftigten; als Anbieter von Teams hat Microsoft allerdings ein Eigeninteresse an Meeting-KI. [Microsoft Work Trend Index 2023](https://info.microsoft.com/rs/157-GQE-382/images/SREVM16705-CNTNT.pdf)
- In der iBabs Global Meeting Survey 2024 bestätigte **weniger als die Hälfte**, dass Action Items angemessen verfolgt würden. Auch dies ist eine Anbieterbefragung und daher eher ein Größenordnungs- als ein neutraler Wirksamkeitsbeleg. [iBabs](https://www.ibabs.com/en/board-management/global-meeting-survey/)
- In einer von Otter veröffentlichten Befragung hielten **77 %** eine Verteilung der Notizen spätestens am folgenden Tag für nötig; als wichtigste Inhalte nannten die Befragten Entscheidungen, Termine sowie Aufgaben mit Owner. Auch diese Studie ist anbietergesponsert. [Otter-Report](https://public.otter.ai/reports/The_Cost_of_Unnecessary_Meeting_Attendance.pdf)

Die wiederkehrenden praktischen Lücken sind damit:

1. **kein eindeutiger Owner,**
2. **kein Termin oder nur „bald“,**
3. **Aufgabe ohne prüfbares Ergebnis,**
4. **Vorschlag wird fälschlich als Entscheidung protokolliert,**
5. **offene Frage wird notiert, aber nicht wiedervorgelegt,**
6. **Risiko wird als Sorge erwähnt, ohne Owner oder Reaktion.**

## Wie Nestor nachfragen sollte

Die Moderationspraxis empfiehlt Zusammenfassungen **nach jedem Themenblock** und eine Abschlussprüfung von Entscheidungen, Aufgaben und Terminen. Ein Parkplatz soll Nebenthemen sichtbar sichern, ohne die laufende Diskussion zu entgleisen. [Princeton](https://insidefacilities.princeton.edu/focus), [Government of Canada – Facilitation Essentials](https://www.csps-efpc.gc.ca/tools/jobaids/summarizing-synthesizing-eng.aspx)

Daraus würde ich für Nestor ableiten:

- **Nicht mitten im Gedanken unterbrechen.** Zunächst still als unvollständige Karte anzeigen.
- **Am natürlichen Übergang fragen:** Agendawechsel, erkennbare Gesprächspause oder Abschluss eines Beschlusses.
- **Mit einem konkreten Vorschlag statt einer offenen Meta-Frage:**  
  „Ich habe als Aufgabe notiert: *Anna schickt den Entwurf*. Wer übernimmt sie verbindlich und bis wann?“
- **Fehlende Angaben bündeln:** eine Nachfrage pro Artefakt, nicht je Feld.
- **Nur Pflichtfelder aktiv erfragen.** Begründung, Priorität oder Definition of Done nur bei erkennbarer Mehrdeutigkeit.
- **Eine abgelehnte Nachfrage nicht wiederholen.** Die Karte bleibt sichtbar als „unvollständig“.
- **Am Meetingende höchstens drei relevante Lücken vorlesen:** zuerst Aufgaben ohne Owner, dann Aufgaben ohne Termin, danach unklare Entscheidungen bzw. hohe Risiken.
- **Unsicherheit offen benennen:**  
  „Das klang für mich nach einer Entscheidung. Soll ich es so festhalten?“
- **Die Gruppe bestätigen lassen.** Nestor schlägt vor; die Runde entscheidet – passend zum Lastenheft.

Eine sinnvolle Obergrenze wäre daher: **eine Intervention pro Themenabschluss plus ein gebündelter Abschlusscheck**, nicht ein starres Zeitintervall.

---

*Recherche am 08.10.2026; berücksichtigt wurden Framework-/Moderationsquellen, Anbieter-Dokumentationen aller sieben genannten Werkzeuge und Befragungen. Sättigung war erreicht, als zusätzliche Quellen nur weitere Varianten von Zusammenfassung, Aufgabe, Entscheidung, offener Frage, Risiko und Parkplatz lieferten. Anbieterquellen belegen Funktionen, nicht deren Erkennungsqualität.*