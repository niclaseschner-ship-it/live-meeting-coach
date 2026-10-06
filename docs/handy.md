# Handy als Mikrofon und Fernbedienung

Das Laptop-Mikrofon taugt nicht für den Raum. Ein Handy in der Tischmitte hört besser und bedient Nestor, ohne dass
jemand zum Laptop muss. Die Handy-Seite `/handy` bietet keine neuen Funktionen, sondern die des Dashboards für den
Daumen:

- Mikrofon übernehmen, mit Pegelanzeige;
- Nestor fragen, stoppen und wieder zuhören lassen; stumm schalten;
- laufender Hinweis groß, Nestors letzte Antwort;
- Verlauf: Hinweise, Nestor-Karten (antippen öffnet sie) und Transkript;
- Meeting starten und beenden.

Eingerichtet wird das Meeting weiter am Laptop, der als Anzeige für alle dient.

## Einrichten

1. Einmalig auf dem Laptop: `tailscale serve --bg 8000`. Der Coach ist dann unter
   `https://<laptop>.<tailnet>.ts.net` erreichbar, mit echtem Zertifikat und nur im eigenen Tailnet.
   Abschalten mit `tailscale serve --https=443 off`.
2. Im Dashboard auf das Handy-Symbol tippen und den QR-Code scannen. Alternativ `/handy` öffnen und den
   Kopplungscode eintippen.
3. Am Handy „Mit diesem Handy zuhören“ tippen. Das Handy übernimmt das Mikrofon, der Laptop gibt es ab
   (Kopfleiste „Mikro: Handy“). Zurückholen geht über das Handy-Symbol.

Als App installieren: Android über „Als App installieren“, iPhone über „Teilen → Zum Home-Bildschirm“. Die
installierte App hat am iPhone eigene Cookies, dort den Code einmal eintippen.

## Latenz (geschätzt und gemessen)

| Strecke | Laptop-Mikrofon | Handy über WLAN/Tailnet |
|---|---|---|
| Mikrofon im Browser | ~10–20 ms | ~20–40 ms |
| Audiopakete à 100 ms | 100 ms | 100 ms |
| Netz bis zum Laptop | 0 | direkt 2–10 ms, über Relay 50–150 ms |
| HTTPS-Weiterleitung `tailscale serve` | – | gemessen ~25 ms je neue Verbindung, der Audiostrom bleibt offen |

Typisch kommen 30–100 ms hinzu. Zum Vergleich: Der Live-Text braucht 1–2 s, Nestors Antwort ~6 s. Kosten
entstehen keine, der Audiostrom ist ~48 KB/s. Die Handy-Seite zeigt die gemessene Laufzeit zum Laptop
(grün < 80 ms, gelb < 250 ms). Gelb oder rot heißt meist: Das Netz trennt die Geräte voneinander (Gäste-WLAN),
und Tailscale vermittelt über einen Relay-Server.

## Was wir aus Teachbuddy und xbuddy übernommen haben

- **HTTPS ist Pflicht.** Ohne HTTPS gibt der Browser das Mikrofon nicht frei, und es gibt keinen Service Worker.
  Wir verwenden ein Tailscale-Zertifikat, denn ein selbstsigniertes Zertifikat muss man auf dem iPhone mühsam als
  vertrauenswürdig einrichten.
- **Wake Lock** nach jedem Verdecken neu anfordern; der Zustand ist als Chip sichtbar („Display bleibt an“).
  Fehlt die Unterstützung, steht dort „Display-Timeout hochsetzen“.
- **Stille ist kein abgeschaltetes Mikrofon.** Der Server merkt sich, wann zuletzt ein Audiopaket kam. Pakete
  kommen alle 100 ms, auch bei Stille. Bleiben sie > 3 s aus, zeigen Dashboard und Handy „kein Ton vom Handy“.
  Wird das Handy wieder sichtbar, verbindet es das Mikrofon still neu.
- **AudioContext immer wieder aufwecken.** Android startet ihn gern angehalten.
- **Ein Mikrofon zur Zeit.** Eine neue Quelle löst die alte ab (Code 4001), sonst entstünde ein zerhackter Strom.
- **Nestors Stimme über das Handy, das zuhört.** Echo-Unterdrückung kann nur herausrechnen, was das Gerät selbst
  abspielt. Ein zweites Handy als reine Fernbedienung nimmt die Stimme nicht weg.
- **Keine alten Fassungen.** Der Service Worker holt immer zuerst aus dem Netz und dient nur offline aus dem
  Zwischenspeicher.
- **iOS:** Apple-Meta-Tags und `apple-touch-icon`, sonst startet die App im Safari-Rahmen. Am iPhone den
  Stummschalter aus, sonst bleibt Nestor still (Web-Audio folgt dem Schalter).

## Sicherheit

Der Coach lauscht weiter nur auf `127.0.0.1`. Anfragen über `tailscale serve` erkennt er an den
Weiterleitungs-Kopfzeilen. Sie brauchen den Kopplungscode, ein Cookie hält ihn 400 Tage. Der Code liegt in
`~/.live-meeting-coach/kopplung`; wer die Datei löscht, entkoppelt alle Handys. Den OpenAI-Schlüssel eintragen und
den QR-Code anzeigen geht nur am Laptop selbst.

## Offen für den Raumtest

- Mit Pixel 9a und iPhone 12 im Raum messen: Laufzeit, Echo mit Nestor über Handy-Lautsprecher, Display-Sperre.
- iPhone: Ob Safari bei aktivem Mikrofon über den Lautsprecher oder leise über die Hörmuschel spielt, ist
  ungeprüft. Im Zweifel einen Bluetooth-Lautsprecher am Handy verwenden.
