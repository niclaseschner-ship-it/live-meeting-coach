# Marktrecherche „Nestor“

_Erstellt am 08.10.2026 von Codex (Websuche) im Auftrag; Auftrag in logs/marktrecherche/auftrag.md auf dem Pi. Momentaufnahme, Angaben mit Quellen._

**Stand:** 8. Oktober 2026  
**Recherchetyp:** Beurteilung  
**Quellenbasis:** Anbieter- und Preisseiten, Datenschutzunterlagen, GitHub-Repositories und Releases sowie wissenschaftliche Primär- und Übersichtsarbeiten. Preise sind Listenpreise ohne Umsatzsteuer, soweit nicht anders angegeben.

## Kurzfazit

Der Markt für KI-Meeting-Assistenten ist groß, aber fast vollständig auf **Dokumentation von Videoanrufen** optimiert: Bot beitreten lassen, transkribieren, zusammenfassen, Aufgaben exportieren. Unterstützung für echte Präsenzgespräche wächst – vor allem durch mobile Apps, botfreie Desktop-Aufzeichnung und Teams-Rooms –, bleibt aber meist bei Transkript und Nachbereitung stehen.

Nestors engeres Feld, nämlich **sichtbare und zurückhaltende Live-Moderation eines deutschsprachigen Raumgesprächs mit Agenda, Zeit, Gesprächsregeln und ansprechbarem Sprachassistenten**, ist deutlich dünner besetzt. Read.ai, Microsoft Facilitator, SmartCues, MeetingTango und das junge TriLuna kommen einzelnen Teilen nahe. Keines der geprüften etablierten Produkte vereint jedoch Nestors gesamtes Bündel.

Die größte strategische Gefahr ist nicht ein einzelner direkter Konkurrent. Sie ist die Kombination aus:

- einem vorhandenen Ökosystem wie Teams oder Google Workspace,
- einem guten Notetaker für 8–25 € pro Nutzer und Monat,
- und einem einfachen Agenda-/Timer-Tool.

Nestor muss daher nicht primär beim „besseren Transkript“ gewinnen, sondern beim **erlebbar besseren Meeting während es stattfindet**.

---

## 1. Kommerzielle Anbieter

### 1.1 Notetaker und Meeting-Assistenten

Legende:

- **Raum:** echte Präsenzsitzung über Laptop-/Handymikrofon
- **Live-Hinweise:** Hinweise während des Gesprächs, nicht erst im Bericht
- **Ansprache:** Assistent kann während des Meetings dialogisch befragt werden; „Chat“ bedeutet keine gesprochene Wakeword-Bedienung
- **DS:** Datenstandort beziehungsweise Datenschutzposition laut Anbieter

| Anbieter | Funktionen | Raum/Hybrid | Live-Hinweise bzw. Ampeln | Sprachlich ansprechbar | DS / DSGVO | Listenpreis |
|---|---|---|---|---|---|---|
| **Otter.ai** | Live-Transkript, Sprecher, Zusammenfassung, Aufgaben, Folienerkennung, AI Chat, Kalender- und Call-Integrationen | **Ja**, Live-Aufnahme über Web-/Mobil-App; Hybrid über Zoom/Teams/Meet | Redezeit als Auswertung, aber keine Nestor-artigen Regelampeln | AI Chat textlich; keine belegte Wakeword-/Sprachantwort | US-Anbieter/AWS; DPA, SCC und internationale Transfers, kein belegter EU-Datenstandort | Free; Pro **$8,33**, Business **$19,99/Nutzer/Monat** jährlich ([Preis/Funktionen](https://otter.ai/pricing), [DPA](https://otter.ai/terms-of-service)) |
| **Fireflies.ai** | Bot, Transkript, Zusammenfassung, Aufgaben, Suche, Integrationen, Analyse | Vor allem Online-Calls; Raum nur indirekt über Aufzeichnung/Upload | Conversation Intelligence, aber keine sichtbare Gruppenmoderation | Chat über Inhalte, nicht als Raum-Sprachassistent belegt | US-Transfer unter DPF/SCC; Anbieter sagt, Meetingdaten würden nicht zum Modelltraining benutzt | Free; Pro **$10**, Business **$19**, Enterprise **$39/Nutzer/Monat** jährlich ([Preise](https://guide.fireflies.ai/articles/9606045468-fireflies-billing-terms), [DPA](https://fireflies.ai/data-processing-agreement)) |
| **tl;dv** | Botbasierte Aufzeichnung, Transkript, Clips, Zusammenfassungen, Multi-Meeting-Auswertung, CRM | Schwerpunkt Meet/Teams/Zoom; keine überzeugend belegte native Raumfunktion | Nein | Textbasierte KI-Auswertung | EU-Unternehmen mit DSGVO-Positionierung; exakter Verarbeitungsort je Funktion muss im DPA geprüft werden | Free plus kostenpflichtige Pläne; belastbarer aktueller öffentlicher Listenpreis war nicht eindeutig auslesbar ([Billing-Dokumentation](https://intercom.help/tldv/en/collections/3423236-billing)) |
| **Fathom** | Online-Aufzeichnung, Zusammenfassungen, Aufgaben, Clips, globale Suche, CRM-Sync, Scorecards | Schwerpunkt Videoanruf; botfreie Mac-Aufnahme in Beta, kein ausgeprägtes Raumprodukt | Coaching-Scorecards nach dem Gespräch, nicht allgemeine Regelampeln | „Conversational meeting assistant“ textlich | Daten laut Anbieter vollständig in den **USA**; DPA und behauptete DSGVO-Konformität | Free; Individual Premium **$16**, Team **$15**, Business **$25/Nutzer/Monat** jährlich ([Preise](https://www.fathom.ai/pricing), [Sicherheit](https://help.fathom.video/en/articles/296512)) |
| **Read.ai** | Live-Transkript und -Zusammenfassung, Meeting-Timer, Talk Time, Engagement, Sentiment, Aufgaben, persönlicher Coach | **Ja**, mobile und Desktop-Apps erfassen Präsenztermine; Kernprodukt bleibt plattformnah | **Ja:** Live-Talk-Time, Tempo, Füllwörter, Engagement und Meeting-Timer; am nächsten an Nestors Feedbackidee | Kein belegter gesprochener Wakeword-Dialog; Ask Read textlich | US standardmäßig; **EU- und Kanada-Residency für geeignete Workspace-Kunden**, DPA/SCC; affektive Kennzahlen abschaltbar | Free 5 Meetings; bezahlte Pläne grob **$15–29,75/Nutzer/Monat** jährlich, je Stufe ([Live-Werkzeuge](https://www.read.ai/meeting-tools), [Preise](https://support.read.ai/hc/en-us/articles/22307341312275-What-are-the-different-paid-plans-that-Read-offers), [Residency](https://www.read.ai/for-your-teams)) |
| **Krisp** | Botfreie Aufnahme, Live-Transkript, Zusammenfassung, Aufgaben, Rauschunterdrückung, Sprecherzeit, AI Chat | **Ja**, expliziter Modus für Präsenz- und Hybridmeetings auf Desktop und Mobilgerät | Talk-Time, aber keine thematischen oder Gesprächsregel-Ampeln | AI Chat textlich | Behauptet DSGVO/SOC 2; Wahl des Rechenzentrums und On-Device-Modus erst Enterprise | Core **$8**, Advanced **$15/Nutzer/Monat** jährlich; Enterprise individuell ([Preise und Funktionen](https://krisp.ai/pricing/), [Präsenzmodus](https://whatsnew.krisp.ai/announcements/krisp-3-2-6-ai-meeting-assistant-improvements)) |
| **Granola** | Botfreie Mitschrift, KI ergänzt eigene Notizen, Vorlagen, Meeting-Chat, Suche und Integrationen | Laptopmikrofon ermöglicht Präsenzaufzeichnung; keine explizite Raum-Moderation | Nein | Chat über Meetings, nicht gesprochen | Cloudverarbeitung; Training kann individuell beziehungsweise unternehmensweit deaktiviert werden | Free; Business **$14**, Enterprise **$35/Nutzer/Monat** ([Preise](https://www.granola.ai/pricing)) |
| **Jamie** | Botfreie Aufnahme, Transkript nach Meeting, Zusammenfassung, Aufgaben, Ask Jamie | **Ja**, ausdrücklich Präsenzmeetings; derzeit schwach bei Live-Transkription | Nein, Verarbeitung wesentlich nach dem Gespräch | Textchat nach dem Meeting | **EU-gehostet**, laut Anbieter DSGVO-konform | Free 10 Notizen; bezahlte Pläne ab ungefähr **24 €/Nutzer/Monat** ([offizielle Preis-/Funktionsseite](https://www.meetjamie.ai/pricing)) |
| **Notta** | Live-Aufnahme, Transkript, Sprechererkennung, Zusammenfassung, Bot für Calls, Übersetzung, Hardware „Memo“ | **Ja**, native Sofortaufnahme für Präsenzgespräche; Hardware verfügbar | Nein | „Notta Brain“ als Chat, nicht als moderierender Sprachassistent | AWS; SOC 2/ISO 27001. Neuer Offline-„Privacy Mode“ hält Audio und Transkript lokal, schaltet aber nicht sämtliche Netzwerkaktivität ab | Pro **$8,17**, Business **$16,67/Nutzer/Monat** jährlich; Memo-Hardware zusätzlich ([Preise](https://www.notta.ai/en/pricing), [Privacy Mode](https://support.notta.ai/hc/en-us/articles/52683417314587-What-is-Privacy-Mode-Recording)) |
| **PLAUD Note / NotePin** | Kleine Aufnahmehardware, Transkript, Zusammenfassungen, Vorlagen; 300 Minuten monatlich enthalten | **Ja**, klar auf Präsenzgespräche und Interviews ausgerichtet | Nein; Ergebnisse überwiegend nach der Aufnahme | Kein echter Raumdialog | Anbieter wirbt mit DSGVO, ISO 27001/27701, SOC 2 und HIPAA; konkrete Residency muss vertraglich geprüft werden | Hardware plus Abo; **300 Min./Monat inklusive**, laufende Pläne zusätzlich ([Produktseite](https://eu.plaud.ai/products/plaud-note-ai-voice-recorder), [Planvergleich](https://support.plaud.ai/hc/en-us/articles/50742099278617-Comparison)) |
| **Sally AI** | Bot, Transkript, Zusammenfassung, Aufgaben, Analysen, CRM; Smartphone-App | **Ja:** Vor-Ort- und Hybridtermine über App beziehungsweise Konferenztelefon | Analyse, aber keine belegten allgemeinen Live-Regelampeln | Kein gesprochener Raumdialog belegt | **Entwickelt und gehostet in Deutschland**; Löschregeln, AVV, ISO-Zertifizierungen laut Anbieter | Tarife ab **8 €/Monat**, Enterprise individuell ([Preise/Funktionen](https://www.sally.io/de/preise), [Datenschutz](https://www.sally.io/de/dsgvo-und-sicherheit)) |
| **Leexi** | Transkript, Zusammenfassung, Aufgaben-Kanban, Briefing, Websuche, Multi-Meeting-Trends, CRM/ATS/VoIP | **Ja**, Mobile App für Feld- und Präsenzmeetings | Optionaler Coach und Scorecards; primär nachträglich | Ask Leexi textlich | Verarbeitung laut Vertragsunterlagen nur EU/EWR; Datenhaltung und Transport in Frankreich, optional Scaleway | Starter **$12**, AI Meeting **$23**, Business **$39/Nutzer/Monat** jährlich; französische Cloud +$5 ([Preise](https://www.leexi.ai/en/pricing/), [Funktionsvergleich](https://docs.leexi.ai/en/references/plans-and-modules/comparison), [Vertragsunterlagen](https://www.leexi.ai/terms_of_service_en.pdf)) |
| **Amberscript** | Automatische oder menschlich geprüfte Transkription, Sprechertrennung, Editor, API und Exporte | Dateien und Transkriptionsworkflow; kein umfassender Live-Meeting-Assistent | Nein | Nein | **Dateispeicherung auf EU-Servern**, ISO 27001/9001 laut Anbieter | 19 €/5 h, 29 €/10 h, 49 €/25 h monatlich; Credits ab 10 €/h ([Preise](https://www.amberscript.com/en/pricing/)) |

### 1.2 Plattformanbieter mit Raumbezug

| Anbieter | Raumkompetenz | Live-Unterstützung | Datenschutz / Preis | Einordnung gegenüber Nestor |
|---|---|---|---|---|
| **Microsoft Teams Rooms + Copilot/Facilitator** | Sehr stark: zertifizierte Raumgeräte, „Intelligent Speaker“, Stimmen-/Gesichtsprofile und Sprecherzuordnung. Facilitator unterstützt seit 2026 in einer Vorschau auch spontane reine Präsenzgespräche per QR-Code | Live-Notizen, Aufgaben und Chat; keine vergleichbaren frei konfigurierbaren Gesprächsregel-Ampeln. In der Präsenzvorschau wird bisher nur die startende Person namentlich zugeordnet, andere als „Speaker 1/2“ | Teams Rooms Pro **34,70 €/Raum/Monat** plus berechtigte Microsoft- und Copilot-Lizenzen; Copilot Business derzeit ab **15,60 €/Nutzer/Monat** jährlich ([Facilitator](https://learn.microsoft.com/en-us/microsoftteams/rooms/facilitator-teams-rooms), [Sprechererkennung](https://learn.microsoft.com/MicrosoftTeams/rooms/voice-recognition), [Raumpreis](https://www.microsoft.com/de-de/microsoft-teams/microsoft-teams-rooms/compare-rooms-plans), [Copilot-Preis](https://www.microsoft.com/de-de/microsoft-365/copilot/pricing)) | **Stärkste Enterprise-Gegenhypothese:** In Microsoft-Organisationen kann die integrierte Lösung trotz weniger Moderationsfunktionen gewinnen |
| **Zoom Rooms + AI Companion** | Sehr starke Hybridraum-Infrastruktur, Smart Name Tags und Sprachbefehle, aber Hardware-/Zoom-zentriert | Zusammenfassungen, Fragen und Raumsteuerung; keine unabhängige Gesprächsregelmoderation | AI Companion ist bei geeigneten bezahlten Zoom-Workplace-Plänen ohne separaten KI-Aufpreis enthalten; Rooms und Hardware separat ([Raumfunktionen](https://www.zoom.com/en/products/meeting-rooms/hardware/guide/meeting-spaces/), [Zoom-Kostenargument](https://media.zoom.com/download/assets/zoom-tco-vs-ms-teams.pdf)) | Überlegen bei Kamera, Remote-Einbindung und globalem Betrieb; für einfache Präsenzrunden überdimensioniert |
| **Google Meet + Gemini** | „Take notes for me“ kann inzwischen auch für Präsenzmeetings beziehungsweise unterwegs verwendet werden, bleibt aber an ein Meet-/Workspace-Setup gebunden | Während des Meetings „Summary so far“, danach strukturierte Notizen in Docs; keine Live-Moderationsampeln | In berechtigten Workspace-/Google-AI-Plänen enthalten; Daten folgen Workspace-Richtlinien ([Google-Hilfe](https://support.google.com/meet/answer/14754931)) | Sehr niedrige Einführungshürde bei Google-Kunden, aber keine eigenständige Raumfacilitation |

### 1.3 Moderation, Coaching und Facilitation

| Produkt | Was es live leistet | Raum | Preis | Bedeutung für Nestor |
|---|---|---:|---:|---|
| **Read.ai Coach** | Meeting-Timer, Redezeit, Sprechtempo, Füllwörter, Unterbrechungen, Engagement und privates Coaching | Teilweise über Apps | in Read-Plänen enthalten | Der wichtigste etablierte Beleg, dass Nutzer Live-Metriken akzeptieren; problematisch sind Sentiment- und „Charisma“-Bewertungen, von denen Nestor sich bewusst absetzen kann ([Coach](https://www.read.ai/assistant), [Methodik](https://support.read.ai/hc/en-us/articles/4406653674003-About-Sentiment-Engagement-and-the-Read-Score)) |
| **Ovida** | Analyse realer Gespräche, rollenbezogenes Üben und privates Feedback zu Empathie, Zuhören und Fragen | Eher eigene Videoräume oder hochgeladene Aufnahmen | Enterprise/individuell | Kommunikationsentwicklung statt laufender Gruppenmoderation; potenzieller Methoden-/Evaluationspartner ([Produkt](https://ovida.ai/), [FAQ](https://ovida.ai/faqs)) |
| **Mentimeter** | Live-Umfragen, Wortwolken, Abstimmung, Quiz und Publikumsbeteiligung | **Ja**, stark bei Veranstaltungen, Lehre und Workshops | Free; kostenpflichtige Presenter-Pläne | Ergänzung statt Ersatz: Nestor könnte Abstimmungen/Check-ins integrieren, sollte aber kein vollständiges Audience-Response-System nachbauen ([Preise/Funktionen](https://www.mentimeter.com/plans)) |
| **SessionLab** | Agendaentwurf, Methodenbibliothek, automatische Zeitberechnung und Time Tracker | **Ja**, von menschlichen Facilitators geführt | Individual **$9**, Pro **$15**, Business **$23/Nutzer/Monat** jährlich | Stark bei Vorbereitung und Methoden, schwach bei Zuhören und automatischen Live-Hinweisen; gute Integrations-/Kooperationskategorie ([Preise](https://www.sessionlab.com/pricing/)) |
| **Butter** | Virtuelle Workshopräume, Agenda, Timer, Aktivitäten und Moderationssteuerung | Schwerpunkt Online-Workshop | Freemium/Teamtarife; aktueller belastbarer Listenpreis in der Recherche nicht eindeutig | Ersetzt eher Zoom plus Workshopregie, nicht den unauffälligen Präsenzbegleiter |
| **einfache Timer-Tools** | Sichtbare Tagesordnung und Countdown, teilweise grün–gelb–rot | **Ja** | oft kostenlos | Beweisen, dass Nestors Agenda-Ampel allein keine belastbare Differenzierung ist; Beispiele: [AgendaClock](https://agendaclock.com/meeting-agenda-timer), [OpenSpeak](https://openspeak.website/), [SessionRun](https://sessionrun.com/) |

### 1.4 Junge, besonders direkte Wettbewerber

Diese Anbieter sind funktional relevant, aber ihre Marktreife, Kundenbasis und Datenschutzdokumentation sind wesentlich schwächer belegt als bei den etablierten Plattformen.

| Produkt | Nähe zu Nestor | Wichtige Abweichung |
|---|---|---|
| **SmartCues.ai** | Erkennt live Sprechtempo, Talk/Listen-Ratio und Monologe; zeigt kontextbezogene Hinweise. Präsenzgespräche können über das Handymikrofon erfasst werden | Vertriebscoaching auf Ebene des einzelnen Reps, keine neutrale Gruppenmoderation; Datenschutz/Residency und belastbare Preise blieben offen ([Produktseite](https://smartcues.ai/)) |
| **MeetingTango** | KI-Agenda, Timer, Live-Nudges bei Zeitüberschreitung und nicht festgehaltenen Entscheidungen, Aufgaben mit Eigentümer und Nachverfolgung | Kein belegtes tiefes Audioverständnis oder allgemeines Gesprächsregel-Monitoring; junges Produkt ([Produktseite](https://meetingtango.com/)) |
| **TriLuna AI Facilitator** | Lädt Agenda und Regeln, steuert aktiv Reihenfolge, Redezeit und Stummschaltung, greift bei Stillstand ein und erstellt danach Protokolle | Vor allem Telefon-/Video-Calls; aktives „Durchmoderieren“ ist deutlich invasiver als Nestors Ampeln. Reife und Compliance noch unklar ([Produktseite](https://triluna.ai/facilitator/)) |
| **MonsterOps** | Agenda, Abschnittstimer, „Tangent Alerts“, Transkriptnotizen, Entscheidungen und To-dos | Eng auf Leadership-/EOS-artige Routinen zugeschnitten; unabhängige Validierung fehlt ([Produktseite](https://monsterops.io/en/product/leadership-meetings)) |

### Fakt, Annahme, Schluss zu den Anbietern

**Fakten**

- Präsenzaufzeichnung ist 2026 keine Seltenheit mehr: Otter, Read, Krisp, Notta, Jamie, Sally, Leexi und Hardwareanbieter bieten sie in unterschiedlicher Qualität.
- Live-Redezeit und Coaching existieren insbesondere bei Read und SmartCues.
- Microsoft bietet mit Facilitator erstmals eine ernsthafte KI-Notizfunktion für spontane Präsenzgespräche in Teams Rooms.
- Deutsche beziehungsweise EU-Datenhaltung ist bei Sally, Leexi, Amberscript und Jamie klarer positioniert als bei den großen US-Notetakern.

**Annahme**

- „Funktioniert im Raum“ auf einer Produktseite garantiert noch keine gute Sprechertrennung bei 3–8 Menschen um ein einziges Laptopmikrofon. Fast alle Anbieter veröffentlichen dazu keine belastbaren deutschen Raum-Benchmarks.
- Anbieterangaben zu „DSGVO-konform“ sind Selbstauskünfte. Sie ersetzen keine Prüfung von AVV, Subprozessoren, Drittlandtransfers, Löschvorgängen und Einwilligungsprozess.

**Eigener Schluss**

- Nestor ist nicht mehr einzigartig, weil er Präsenzgespräche transkribiert.
- Nestor bleibt ungewöhnlich durch die Verbindung aus **Raumfokus + sichtbarer gemeinsamer Moderation + nicht personenbezogener Gesprächsregeln + Agenda + gesprochenem Dialog**.
- Das stärkste Differenzierungsmerkmal ist dabei nicht „KI“, sondern die **soziale Produktgestaltung**: Das Dashboard bewertet nicht einzelne Menschen, sondern macht gemeinsam vereinbarte Regeln und den Gesprächszustand sichtbar.

---

## 2. Open-Source- und GitHub-Projekte

Sterne und Aktivität sind Momentaufnahmen vom 8. Oktober 2026. Sterne messen Aufmerksamkeit, nicht Codequalität oder Produktionsreife.

| Projekt | Sterne / Aktivität | Lizenz | Fähigkeiten | Ersatz oder Ergänzung für Nestor | Übernahme-/Kooperationspotenzial |
|---|---:|---|---|---|---|
| **[Meetily](https://github.com/Zackriya-Solutions/meetily)** | ca. **31,1k**; letzter Push **15.09.2026**, Commits bis September 2026 | MIT | Lokale Desktop-App, Mikrofon und Systemaudio, Whisper/Parakeet, Zusammenfassung über Ollama oder kompatible APIs; Community-/Pro-Abgrenzung beachten | Könnte Nestors lokale Aufnahme, Transkription und Desktop-Packaging teilweise ersetzen, aber nicht Live-Moderation, Dashboard und Sprachagent | **Sehr hoch:** Audio-Capture, lokale ASR-Pipeline, Installer und Hardwarebeschleunigung prüfen; bei Pro-Funktionen genau auf Codegrenze achten ([Organisation/Metadaten](https://github.com/Zackriya-Solutions), [Releases](https://github.com/Zackriya-Solutions/meetily/releases)) |
| **[Vexa](https://github.com/Vexa-ai/vexa)** | ca. **2,9k**, 2.600+ Commits; v0.12-Releases bis Aug./Sep. 2026 | Apache-2.0 / Open-Core-Komponenten beachten | Bots für Meet, Teams, Zoom, Echtzeit-WebSocket-Transkripte, Sprecherzuordnung, API/MCP, Self-Hosting und Knowledge-Agents | Kein Ersatz für Raum-Moderation; sehr starker Ersatz für eine künftig geplante Online-/Hybrid-Bot-Infrastruktur | **Hoch:** nicht selbst Meeting-Bots bauen. Kooperation oder Adapter für Teams/Zoom/Meet; gehostet ca. **$0,30/h** laut Projekt ([Repo](https://github.com/Vexa-ai/vexa), [Releases](https://github.com/Vexa-ai/vexa/releases)) |
| **[anarlog, vormals Hyprnote](https://github.com/fastrepl/anarlog)** | ca. **9,5k**, knapp 9.800 Commits; gepflegt, Hauptfokus des Teams liegt aber beim separaten Produkt Char | Community-App MIT; Enterprise-Komponenten kommerziell | Local-first Notepad, lokale Transkription, Markdown-Dateien, BYO-LLM, keine Kontopflicht | Ersetzt Notiz-/Archivteil, nicht Live-Ampeln oder Rauminteraktion | **Mittel bis hoch:** lokale Datenmodelle, BYO-Provider und Markdown-Export; Lizenzgrenze in `enterprise/` prüfen ([Repo/Status](https://github.com/fastrepl/anarlog)) |
| **[Scriberr](https://github.com/rishikanthc/Scriberr)** | ca. **3,1k**; aktives Self-Hosting-Projekt | MIT | Offline-Transkription, Sprecherdiarisierung, Suche, Chat, Zusammenfassungen, REST-API | Nachbearbeitung statt harter Echtzeit; kein Moderationsersatz | **Mittel:** Self-hosted Archiv-/Nachverarbeitung, Diarisierungsprofile und API-Entwurf ([Repo](https://github.com/rishikanthc/Scriberr)) |
| **[pyannote.audio](https://github.com/pyannote/pyannote-audio)** | ca. **10,6k**, 2.500+ Commits; Releases und Wartung aktiv | MIT für Bibliothek; einzelne Modelle haben eigene Bedingungen | VAD, Sprecherwechsel, Überlappung, Embeddings und Diarisierung | Baustein, kein Produkt; für Nestors Redeanteile und „Ausreden lassen“ zentral | **Sehr hoch:** Benchmark gegen aktuellen Stack. Besonders Überlappungserkennung; Modelllizenzen und Echtzeitlatenz getrennt prüfen ([Repo](https://github.com/pyannote/pyannote-audio), [Releases](https://github.com/pyannote/pyannote-audio/releases)) |
| **[Conversationaly](https://github.com/bykof/conversationaly)** | jüngerer Meetily-Fork; Aktivität 2026, geringe bis mittlere Reichweite | MIT | Mikrofon und Systemaudio, lokale Live-Transkription und lokales LLM in Tauri/Rust, kein Konto/Cloud/Telemetry | Technisch näher an einer lokalen Nestor-Basis als reine Batch-Projekte, aber ohne Facilitation | **Hoch als Architekturvergleich:** gebündelte `transcribe.cpp`-/`llama.cpp`-Pipeline und Datenschutzstandard |
| **[Meet2Notes](https://github.com/estebanstifli/Meet2Notes)** | jung/aktiv; Sterne noch kein starkes Reifesignal | Repositoryangabe vor Übernahme einzeln verifizieren | Plattformübergreifende Aufnahme, Live- und finale Transkription, Diarisierung, Voice Matching, lokale strukturierte Notizen | Teilersatz der Audio-/Protokollkette | **Mittel:** modulare Trennung von ASR, Diarisierung, Stimmerkennung und Analyse ist architektonisch interessant |
| **[Meeting Transcriber](https://github.com/pasrom/meeting-transcriber)** | jung und aktiv | MIT | macOS, automatische Erkennung von Teams/Zoom/Webex, getrennte Spuren, Whisper/Parakeet, FluidAudio, lokales Markdown-Protokoll | Nur macOS und eher Call-Recorder; kein Präsenzcoach | **Mittel:** Parakeet/WhisperKit, Dual-Track-Aufnahme und automatische Meeting-Erkennung |
| **[OpenAI Agents SDK / Realtime](https://github.com/openai/openai-agents-python)** | stark gepflegtes offizielles SDK; 2026 Realtime-Updates | MIT | Realtime-Sprachagenten, WebSocket-Transport, Tools/MCP und Unterbrechungsbehandlung | Baustein für Premium-Sprachdialog, nicht Meetingprodukt | **Hoch:** offizielle Grundlage für „Nestor, …“, Toolaufrufe und gesprochene Antworten; Providerbindung und laufende Kosten bleiben ([Release Notes](https://github.com/openai/openai-agents-python/blob/main/docs/release.md)) |
| **[Microsoft NOTSOFAR-1](https://github.com/microsoft/NOTSOFAR1-Challenge)** | Forschungsrepo, nicht Endnutzerprodukt | Repo-/Modelllizenzen komponentenweise prüfen | Datensatz und Referenzpipeline für Fernfeld-ASR, Sprachseparation und Diarisierung realer Meetings | Kein Ersatz; Benchmark- und Trainingsressource | **Sehr hoch für Evaluation:** Nestors Kernproblem ist gerade „distant meeting transcription“ mit einem Raummikrofon |
| **[OpenSpeak](https://openspeak.website/)** | kleines Open-Source-Projekt | Open Source; konkrete Lizenz im Repo vor Codeübernahme prüfen | Agenda mit Min-/Soll-/Max-Zeiten, Projektorampel, Smartphone-Steuerung, Ist-vs.-Plan-Report, Self-Hosting | Ersetzt Nestors einfachen Agenda-Timer, nicht die KI-Funktionen | **Mittel:** UX-Ideen und interoperables Agendaformat; beweist zugleich, dass Timer allein Commodity ist |
| **[CoCo Collaboration Coach](https://github.com/ROC-HCI/CollaborationCoach_PostFeedback)** | Forschungsprototyp, nicht laufendes Produkt | im Repo prüfen | Feedback zu Teilnahme, Unterbrechung, Lautstärke und Emotion; Studienprototyp | Konzeptionell sehr nah an Nestors Regelmonitoring | **Hoch als Forschungspartner/Referenz**, weniger als direkt übernehmbarer Produktionscode ([Projektbeschreibung](https://roc-hci.com/past-projects/coco-collaboration-coach/)) |

### Technische Bewertung

**Am ehesten übernehmen**

1. **Fernfeld-/Diarisierungs-Benchmarking:** NOTSOFAR-1 und pyannote.
2. **Lokale Audio- und Desktop-Pipeline:** Meetily beziehungsweise Conversationaly.
3. **Online-Meeting-Bots:** Vexa integrieren statt selbst bauen.
4. **Premium-Sprachagent:** offizielles OpenAI-Realtime-/Agents-SDK.
5. **Portable Exporte:** Markdown-/Dateimodell von anarlog als Vorbild.

**Nicht ungeprüft übernehmen**

- Sprechererkennung über dauerhafte Voiceprints: technisch nützlich, datenschutzrechtlich und sozial deutlich sensibler als anonyme Sprechertrennung.
- Emotion-, Sentiment- oder „Charisma“-Klassifikation: Die Aussagekraft ist begrenzt und widerspricht Nestors nicht personenbezogener Positionierung.
- Code aus Open-Core-Projekten, ohne die Community-/Enterprise-Grenze und Modelllizenzen zu prüfen.

**Kooperationskandidaten**

- **Vexa:** Online-/Hybrid-Anbindung und Botbetrieb.
- **Meetily:** lokaler Audio-Stack und gemeinsame Datenschutzpositionierung.
- **Ovida beziehungsweise CoCo-Forschung:** valide Definition und Evaluation kommunikativer Verhaltenssignale.
- **SessionLab:** Agenda-/Workshop-Import statt Nachbau einer riesigen Methodenbibliothek.

---

## 3. Wissenschaft und Praxis

### 3.1 Was durch Forschung gestützt wird

| Befund | Evidenz | Konsequenz für Nestor |
|---|---|---|
| Sichtbares Echtzeit-Feedback kann das Gesprächsverhalten verändern | Der MIT-**Meeting Mediator** veränderte in Versuchen Überlappungszeit und Interaktivität signifikant, ohne die Teilnehmenden stark abzulenken ([MIT](https://www.media.mit.edu/publications/meeting-mediator-enhancing-group-collaboration-with-sociometric-feedback-2/)) | Ampeln für Monolog, Redeanteil und Ausredenlassen sind grundsätzlich plausibel |
| Redezeit- und Blickfeedback beeinflusst die soziale Dynamik in Präsenzmeetings | Ein multimodales Co-Located-System zeigte in einer Evaluation Verhaltensänderungen durch Echtzeitfeedback ([Springer](https://link.springer.com/article/10.1007/s00779-010-0284-x)) | Präsenzfokus ist wissenschaftlich kein exotischer Sonderfall |
| Ausgewogenere Beteiligung lässt sich technisch anstoßen | **ScoringTalk** steigerte die Beteiligungsbalance, ohne die gesamte Sprechmenge zu verringern ([Studie](https://www.jstage.jst.go.jp/article/iscie/30/11/30_427/_article)); CoCo meldete in einem Experiment mit 39 Personen ausgeglichenere Redeanteile ([Projekt](https://roc-hci.com/past-projects/coco-collaboration-coach/)) | Redeanteil sollte als Gruppenmuster visualisiert werden, nicht als individuelle Schulnote |
| Dashboards fördern Bewusstsein, beweisen aber nicht automatisch bessere Entscheidungen | Microsofts **MeetingCoach** verbesserte in seinen Evaluationen Bewusstsein und Erinnerung; die Autoren formulieren nur „Potenzial“ für mehr Effektivität und Inklusion ([Paper](https://www.microsoft.com/en-us/research/uploads/prod/2021/01/MeetingCoach_CHI2021_cameraready.pdf)) | Produktmetriken nicht als bewiesene Produktivitätssteigerung vermarkten |
| Passive Hinweise sind weniger störend als aktive Eingriffe | Eine CHI-2025-Studie mit 15 Wissensarbeitern fand passive Zielreflexion hilfreich; aktive Fragen lösten eher unmittelbare Reflexion aus, konnten aber den Gesprächsfluss stören ([CHI-Paper](https://doi.org/10.1145/3706598.3714052)) | Nestors Ampeln sollten Standard sein, gesprochene Eingriffe nur auf Anfrage oder nach expliziter Regel |
| Agenda und Vorbereitung korrelieren mit besseren Meetings | Forschung und Reviews nennen schriftliche Agenda, Vorabinformationen, klare Ziele und vollständige Behandlung der Punkte als wichtige Merkmale ([Praxis-/Literaturüberblick](https://pmc.ncbi.nlm.nih.gov/articles/PMC6743516/), [CIPD Evidence Review](https://www.cipd.org/en/knowledge/evidence-reviews/productive-meetings/)) | Der Einladungsmail-zu-Agenda-Workflow ist ein substanzieller Teil des Produkts, kein Beiwerk |
| Inklusion und wahrgenommene Wirksamkeit hängen zusammen | Eine große Unternehmensbefragung mit 3.290 ausgewerteten Antworten verband Agenda, Vorab-/Nachabkommunikation, Beteiligung und angenehmes Beitragen mit Wirksamkeit und Inklusion ([Studie](https://arxiv.org/abs/2102.09803)) | Nestor sollte Gruppenprozess und Ergebnisartefakte gemeinsam messen |
| Mehr Feedback ist nicht immer besser | CoCo fand auch, dass Echtzeitfeedback Gespräche weniger spontan machen kann; Effekte wirkten teilweise in spätere Sitzungen fort ([Projekt](https://roc-hci.com/past-projects/coco-collaboration-coach/)) | Ein ruhiger, abschaltbarer Modus und nutzerdefinierte Schwellen sind wichtig |
| KI-Moderation ist weiterhin ein junges Forschungsfeld | Neuere Arbeiten zu inklusiven Co-Hosts und Feedbackmediatoren berichten formative beziehungsweise kleine Laborstudien, etwa 68 Personen in 12 Gruppen oder 28 Personen ([Inclusive Meetings](https://arxiv.org/abs/2501.10553), [Feedback Mediator](https://arxiv.org/abs/2601.11750)) | Keine starken Wirksamkeitsversprechen ohne eigene Feldstudie |

### 3.2 Was nicht als belegt gelten sollte

**Nicht ausreichend belegt sind:**

- dass gleichmäßige Redezeit in jedem Meeting besser ist;
- dass KI zuverlässig Respekt, Stimmung oder „Charisma“ objektiv erkennt;
- dass weniger Unterbrechungen immer bessere Ergebnisse erzeugen;
- dass automatische Moderation menschliche Facilitators ersetzen kann;
- dass gute Transkription automatisch zu besseren Entscheidungen führt.

Redeanteile hängen von Rolle und Meetingtyp ab: Eine Sachverständige darf in einer Anhörung mehr sprechen, ein Moderator weniger Inhalt beitragen, und ein kurzes Lagebriefing ist bewusst asymmetrisch. Nestor sollte daher **gegen vorher vereinbarte Regeln und Meetingtypen**, nicht gegen eine universelle Gleichverteilungsnorm prüfen.

### Praxis-Schluss

Der wissenschaftlich defensible Claim lautet:

> Nestor macht ausgewählte Gesprächsmuster und Zielabweichungen zeitnah sichtbar, damit die Gruppe selbst reagieren kann.

Nicht defensible wäre:

> Nestor erkennt objektiv schlechte Kommunikation und macht jedes Meeting produktiver.

---

## 4. Lücke und Positionierung

### 4.1 Wo Nestor tatsächlich besonders ist

| Merkmal | Marktstatus | Nestors Position |
|---|---|---|
| Präsenzmeeting mit einem normalen Laptop-/Handymikrofon | Inzwischen bei mehreren Notetakern vorhanden | Nur noch begrenzt differenzierend |
| Gemeinsamer Beamer-/Dashboardmodus | Bei Notetakern selten; bei Timern üblich | Stark in Verbindung mit Transkript und Meetingzustand |
| Live-Regeln: Monolog, Abschweifung, Ausredenlassen, respektvoller Ton | Einzelteile bei Read, SmartCues und Forschungsprototypen; kaum als neutrales Gruppenprodukt | **Kernlücke**, besonders ohne Personenbewertung |
| Agenda mit Countdown je Punkt | Commodity bei Facilitation-Tools | Nützlich, aber allein kein Burggraben |
| Sprachliche Ansprechbarkeit „Nestor, …“ mit gesprochener Antwort | Bei allgemeinen Voice Agents technisch verfügbar, bei Notetakern im Raum selten | **Starkes Differenzierungsmerkmal**, sofern Latenz und Fehlaktivierungen stimmen |
| Live-Übersicht „Entschieden, Offen, Aufgaben“ | Viele Anbieter erstellen dies erst nachträglich | Stark, wenn während des Meetings korrigierbar |
| EU-Basisstufe und flüchtige Sitzungsdaten | Einige EU-Anbieter haben Residency; „nur bis Meetingende“ ist seltener | Stark für Verwaltung, Bildung, Beratung und Betriebsrat |
| Open Source, AGPL | Kommerzielle Marktführer geschlossen; einige lokale OSS-Notetaker existieren | Stark für Vertrauen und Self-Hosting, aber kein Ersatz für Betriebssicherheit |
| Webrecherche und Folien aus dem Gespräch | Meeting-Tools bieten zunehmend Chats, Suche und Integrationen | Differenzierung nur, wenn live, zuverlässig und quellennah |

### 4.2 Wo Nestor klar unterlegen ist

**Faktenbasierter Vergleich**

- **Akustik und Sprecherzuordnung:** Teams Rooms und Zoom Rooms können zertifizierte Mehrmikrofonhardware und Benutzerprofile nutzen.
- **Kalender und automatische Teilnahme:** etablierte Notetaker verbinden Google/Microsoft-Kalender in wenigen Schritten.
- **Videoanruf-Anbindung:** Fireflies, Otter, Fathom, Read, Sally und Leexi treten automatisch Calls bei.
- **Integrationen:** CRM, Slack, Notion, Jira, Asana, Zapier, Webhooks, öffentliche APIs und MCP sind verbreitet.
- **Enterprise-Verwaltung:** SSO, SCIM, Audit Logs, Rollen, Retention, Domain Capture und zentrale Richtlinien fehlen typischerweise jungen Projekten.
- **Mobile Reife:** etablierte Anbieter haben native Apps, Benachrichtigungen und zuverlässige Hintergrundaufnahme.
- **Suchbares Langzeitgedächtnis:** Nestors Löschung am Meetingende ist datenschutzfreundlich, aber für Nutzer, die ein Wissensarchiv erwarten, zugleich ein Funktionsnachteil.
- **Vertrieb und Vertrauen:** Microsoft, Google und etablierte Anbieter haben Beschaffungskanäle, Zertifikate, SLAs und Support.

### 4.3 Was Nutzer wahrscheinlich zusätzlich erwarten

Priorität aus Markthäufigkeit und Wechselhürde:

1. **Kalenderintegration** und Agendaübernahme aus Einladung/Termin.
2. **Export mit einem Klick:** Markdown, PDF, DOCX, E-Mail sowie Aufgaben nach Planner, Jira, Asana oder Trello.
3. **Teams-/Zoom-/Meet-Anbindung**, zumindest als Hybridquelle.
4. **Korrigierbares Ergebnis:** Entscheidungen, offene Punkte, Aufgaben und Sprecherlabels während und nach dem Meeting bearbeiten.
5. **Einwilligungs- und Transparenzworkflow:** sichtbarer Aufnahmestatus, mündliche oder digitale Zustimmung, Pause-/Privatmodus.
6. **Meetingvorlagen:** Teamrunde, Retrospektive, Gemeinderat, Workshop, Unterricht, Beratung.
7. **Glossar und Eigennamen**, besonders für Verwaltung, Technik und Hochschulen.
8. **Mehrmikrofon-/Raumhardware-Unterstützung**, ohne Hardwarezwang.
9. **Optionales Archiv statt Zwangsarchiv:** standardmäßig flüchtig, aber expliziter Export oder kundeneigener Speicher.
10. **Administration:** Kundenpasswort reicht für Pilotkunden, später werden Rollen, SSO, Audit und Löschrichtlinien erwartet.
11. **Barrierefreiheit:** gut lesbare Live-Untertitel, Tastaturbedienung, Kontrast und Export für Hörgeschädigte.
12. **Qualitätsanzeige:** kenntlich machen, wenn Diarisierung, Themenerkennung oder Regelbewertung unsicher ist.

### Positionierungsvorschlag

> **Nestor ist kein Meeting-Recorder, sondern der gemeinsame, datensparsame Co-Moderator für Gespräche im Raum. Er hält Agenda, Zeit, Gesprächsregeln und Ergebnisse sichtbar zusammen – ohne Menschen zu benoten.**

Die Abgrenzung „ohne Bewertung von Personen“ sollte deutlich offensiver werden. Read und andere Produkte sprechen von Sentiment, Engagement, Bias oder Charisma. Das schafft zwar beeindruckende Dashboards, öffnet aber methodische, arbeitsrechtliche und soziale Angriffsflächen.

---

## 5. Zielgruppen und Preisrahmen

### 5.1 Marktübliche Vergleichspreise

Aus den geprüften Listenpreisen ergeben sich drei Preiscluster:

| Kategorie | Typischer heutiger Preis |
|---|---:|
| Individueller Notetaker | etwa **8–20 € pro Nutzer/Monat** |
| Team-/Business-Notetaker mit Integrationen | etwa **15–40 € pro Nutzer/Monat** |
| Facilitation-Planer | etwa **9–23 € pro Facilitator/Monat** |
| Konferenzraum-Plattform | etwa **35 € pro Raum/Monat** allein für die Raumsoftware, zuzüglich Benutzerlizenzen und Hardware |
| Transkription nach Verbrauch | ungefähr **1,60–10 € pro Audiostunde**, ohne umfassende Live-Moderation |
| Professionelle menschliche Moderation | wesentlich höher und meist tage- beziehungsweise projektbezogen; nicht derselbe Produktmarkt |

Nestors Rechenkosten von ungefähr **0,70 €/h Basis** beziehungsweise **$2–3,50/h Premium** liegen unter vielen denkbaren Nutzenwerten, aber Premium kann bei intensiver Nutzung teuer werden. Eine reine unbegrenzte Pauschale ohne Fair-Use wäre riskant.

### 5.2 Zielgruppenbewertung

| Zielgruppe | Nutzen | Haupthürde | Zahlungsrahmen als begründete Annahme |
|---|---|---|---:|
| **KMU-Teams mit vielen Präsenzrunden** | Weniger Moderationslast, sichtbare Entscheidungen und Aufgaben; keine Teams-Rooms-Hardware nötig | Kalender/Export und Zuverlässigkeit werden erwartet | **19–49 €/Team/Monat** Basis; **59–99 €** mit Premiumstunden und Integrationen |
| **Verwaltung, Gemeinderäte, Gremien** | Agenda, Zeitdisziplin, nachvollziehbare Entscheidungen, deutsche Sprache, EU-Verarbeitung | Datenschutzprüfung, Zustimmung, Vergabe, Anforderungen an Protokollrichtigkeit | **49–149 €/Raum/Monat** oder **10–30 € je Sitzung**; Self-Hosting/Support separat |
| **Vereine und Ehrenamt** | Entlastet Protokollführung, hält lange Diskussionen auf Kurs | Sehr preissensibel, geringe technische Betreuung | kostenlos/freiwillige Unterstützung; optional **5–15 €/Monat** |
| **Schulen und Hochschulen** | Seminare, Projektgruppen, Gremien, Barrierefreiheit und Moderationslernen | Einwilligung, Minderjährige, institutionelle IT und Zugänglichkeit | **10–30 €/Lehrkraft/Monat** oder Campus-/Fachbereichspaket; Bildungsrabatt nötig |
| **Beratung und professionelle Moderation** | Co-Facilitator, Live-Ergebnisbild, Recherche, Folien, nachvollziehbares Follow-up | Muss konfigurierbar sein und darf Moderator nicht öffentlich korrigieren | **29–79 €/Facilitator/Monat**, ggf. **5–15 € je Premiumsitzung** |
| **Betriebsräte, Verbände, Nonprofits** | Datenschutz, zugängliche Protokolle, ausgewogene Beteiligung | Hohe Vertraulichkeit; US-Cloud oft problematisch | **19–59 €/Organisation/Monat**, On-Prem/EU-Support höher |
| **Vertriebsteams** | Live-Coaching und Zusammenfassungen | Stark besetzter Markt; CRM-Sync zwingend | **20–50 €/Nutzer/Monat**, aber Nestor hätte hier keinen natürlichen Vorteil |
| **Großunternehmen** | Standardisierte Moderation in Räumen | SSO, SCIM, Audit, SLA, Geräteverwaltung und Beschaffung fehlen | Potenziell **50–150 €/Raum/Monat**, aber erst nach Enterprise-Reife |

Die Preisrahmen der rechten Spalte sind **eigene Schlussfolgerungen**, keine gemessene Zahlungsbereitschaft. Sie sind aus den Marktpreisen von Notetakern, Facilitation-Software und Teams Rooms abgeleitet. Eine belastbare Preisentscheidung benötigt Interviews oder bezahlte Pilotversuche.

### 5.3 Sinnvolle Angebotslogik

Nestors freiwillige Finanzierung passt zu Vereinen und Open Source, ist aber als alleinige SaaS-Finanzierung wahrscheinlich nicht stabil. Eine passende Struktur wäre:

- **Community:** selbst hosten, AGPL, kostenlos.
- **Unterstützer:** gehostete Basis, etwa 10–20 Stunden/Monat, **9–15 €**.
- **Team:** mehrere Moderatoren, Exporte und Kalender, **29–49 €/Monat je Team oder Raum**.
- **Organisation:** EU-Betrieb, Verwaltung, Löschregeln, Support, **79–149 €/Monat**.
- **Premium-Sprache:** enthaltenes Kontingent plus transparente Stunden- oder Creditpreise.

Dabei sollte nicht jeder Sitzplatz lizenziert werden. Für ein Produkt, das sichtbar im Raum läuft, ist **Preis je aktivem Raum, Team oder Facilitator** verständlicher als eine Lizenz für jede anwesende Person.

---

## Gegenhypothesen

### „Microsoft, Google und Zoom werden Nestor überflüssig machen“

**Teilweise plausibel.** Sie besitzen Kalender, Identitäten, Konferenzhardware und Beschaffungskanäle. Microsoft Facilitator ist ein ernstes Signal.

**Warum die Hypothese noch nicht vollständig trägt:** Diese Plattformen optimieren auf ihr jeweiliges Ökosystem und Meetingdokumentation. Konfigurierbare, gemeinsam sichtbare Gesprächsregeln ohne individuelle Bewertung und eine günstige EU-/Open-Source-Stufe sind weiterhin nicht ihr Schwerpunkt.

### „Ein Notetaker plus kostenloser Timer genügt“

**Für viele Teams wahrscheinlich ja.** Wer nur Protokoll und Zeitplan will, braucht Nestor nicht.

**Konsequenz:** Nestor muss zeigen, dass die Live-Rückkopplung Verhalten oder Ergebnisqualität verbessert. Ohne diesen Nachweis bleibt es ein hübsch kombiniertes Dashboard.

### „Menschen wollen keinen KI-Moderator“

**Für aktive, ungefragte Eingriffe oft richtig.** Forschung weist auf Unterbrechung und geringere Spontaneität hin.

**Konsequenz:** Default sollten passive Ampeln, ein klarer Knopfmodus und explizite Sprachansprache sein. Automatisches Reinsprechen gehört, wenn überhaupt, in einen optionalen experimentellen Modus.

---

## Unsicherheiten und Grenzen

- Viele Funktions-, Sicherheits- und Genauigkeitsangaben stammen von den Anbietern selbst.
- „DSGVO-konform“ wurde nicht juristisch geprüft.
- Mehrere Anbieter ändern Preise und Funktionspakete häufig.
- Es gibt kaum veröffentlichte Vergleichstests für **deutsche Mehrpersonengespräche im Raum mit nur einem Laptopmikrofon**.
- Junge Wettbewerber wie TriLuna, MeetingTango, MonsterOps und SmartCues können funktional interessant sein, haben aber noch keine mit Microsoft, Read oder etablierten Notetakern vergleichbare Beleglage.
- Die Forschung zeigt überwiegend Verhaltensänderungen, Wahrnehmung oder kleine Laborbefunde – nicht robuste langfristige Produktivitäts- oder Entscheidungsgewinne.

## Suchprotokoll

Gesucht wurde auf Deutsch und Englisch nach Kombinationen aus:

- AI meeting assistant / notetaker / in-person / hybrid / room;
- meeting coach / speaking time / interruption / real-time feedback;
- meeting facilitator / agenda timer / tangent alert;
- GDPR / EU data residency / pricing;
- open source meeting transcription / diarization / realtime;
- AI-assisted meeting moderation / sociometric feedback / meeting effectiveness.

Geprüfte Quellenarten:

1. offizielle Produkt-, Preis-, Hilfe- und Datenschutzseiten;
2. GitHub-Repositories, Releases und Lizenzangaben;
3. wissenschaftliche Publikationen und Evidence Reviews;
4. ergänzend einzelne Sekundärquellen, wenn eine Primärseite einen aktuellen Preis nicht vollständig ausgab.

Ausgeschlossen wurden reine Sales-Intelligence-Produkte wie Gong, Avoma und Chorus, allgemeine Videokonferenzsysteme ohne relevante KI- oder Facilitation-Funktion sowie zahlreiche kleine Transkriptions-Wrapper ohne erkennbare Aktivität. Nach zusätzlichen Suchen kamen keine grundlegend neuen Produktkategorien mehr hinzu; die Stoppregel war damit erreicht.

# Die fünf wichtigsten Erkenntnisse für Nestor

1. **Die eigentliche Marktlücke ist nicht Präsenztranskription.** Die können inzwischen viele. Die Lücke ist neutrale, sichtbare Live-Moderation des gemeinsamen Gesprächs.

2. **Read.ai ist der wichtigste etablierte Funktionsvergleich, Microsoft Facilitator die wichtigste strategische Bedrohung.** Read validiert Live-Metriken; Microsoft kann Raumtechnik, Kalender und Enterprise-Vertrieb bündeln.

3. **„Ohne Personenbewertung“ ist ein starkes Produktversprechen.** Nestor sollte Redezeit und Gesprächsregeln als gemeinsam vereinbarten Prozess darstellen und Sentiment-, Emotion- oder Charisma-Scores bewusst ablehnen.

4. **Die Forschung stützt passive Echtzeit-Rückmeldung, aber keine großen Wirkungsversprechen.** Sichtbare Hinweise können Verhalten verändern; aktive KI-Eingriffe können zugleich stören. Knopfmodus und Nutzerkontrolle sind daher Kernfunktionen, keine Datenschutzbeigabe.

5. **Der größte funktionale Rückstand liegt rund um das Meeting.** Kalender, Call-Anbindung, Aufgabenexport, korrigierbare Ergebnisse, Glossar, Administration und optionale kundeneigene Speicherung werden schneller kaufentscheidend als noch eine weitere KI-Analyse.

# Drei Empfehlungen, was als Nächstes

1. **Nestors Wirksamkeit mit einem kleinen Feldversuch belegen.**  
   12–20 reale Teams, jeweils Meetings mit und ohne Nestor; messen: Agendaeinhaltung, Überlappungszeit, Monologphasen, Zahl klar formulierter Entscheidungen/Aufgaben, wahrgenommene Fairness, Ablenkung und Bereitschaft zur erneuten Nutzung. Keine universelle „Meeting-Qualitätszahl“.

2. **Den Produktkern schärfen und die Integrationslücke gezielt schließen.**  
   Zuerst Kalender/Einladungsimport, korrigierbarer Live-Überblick und Exporte zu E-Mail, Markdown sowie mindestens einem Aufgabenwerkzeug. Für Online-/Hybridbots Vexa prüfen; für lokale Audio- und ASR-Technik Meetily/Conversationaly und pyannote benchmarken.

3. **Drei bezahlte Piloten mit unterschiedlicher Zahlungslogik starten.**  
   Je ein KMU-Team, eine Verwaltung/Hochschule und ein professioneller Facilitator. Testen: **29–49 €/Team/Monat**, **49–149 €/Raum/Monat** und **5–15 € je Premiumsitzung**. Entscheidend ist nicht die abgefragte Zahlungsbereitschaft, sondern ob die Organisation nach vier bis acht Wochen tatsächlich verlängert.