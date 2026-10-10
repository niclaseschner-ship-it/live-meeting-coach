// Füllt Name/Anschrift/Mail auf impressum.html und datenschutz.html. Ticket #63: aus dem Inline-<script>
// hierher verschoben, damit die CSP ohne 'unsafe-inline' für script-src auskommt (cloudflare/src/sicherheit.ts).
(async () => {
  try {
    const r = await fetch("/api/start");
    if (!r.ok) return;
    const d = await r.json();
    if (d.impressum_name) document.getElementById("imp-name").textContent = d.impressum_name;
    if (d.impressum_anschrift) {  // ohne Anschrift entfällt die Zeile (privates Projekt, Zugang nur nach Anmeldung)
      document.getElementById("imp-anschrift").textContent = d.impressum_anschrift;
      document.getElementById("imp-anschrift-zeile").hidden = false;
    }
    if (d.impressum_mail) document.getElementById("imp-mail").textContent = d.impressum_mail;
  } catch { /* Vorgabe „[wird ergänzt]“ bleibt stehen */ }
})();
