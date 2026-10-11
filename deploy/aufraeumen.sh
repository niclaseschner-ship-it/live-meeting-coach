#!/usr/bin/env bash
# deploy/aufraeumen.sh – hält die Platte des Pi schlank (Rückmeldung Niclas 11.10.2026: nach Deploys und Testläufen
# blieben Docker-Bilder, Build-Cache und Testvideos liegen). Läuft am Ende von deploy/deploy.sh und scripts/pipeline.sh,
# lässt sich auch von Hand starten. Fasst nur Nestors eigene Sachen an – Immich, Paperless und andere Dienste nie.
#
#   deploy/aufraeumen.sh            Docker-Bilder, Build-Cache und alte Testläufe
#   deploy/aufraeumen.sh --nur-logs nur alte Testläufe (für die Pipeline, ohne Docker)
#
# Behalten wird:
#   - je Nestor-Bildreihe (nestor-nestor, nestor-staging-nestor-staging) nur das neueste Tag – ein Rollback baut mit
#     deploy.sh --ref ohnehin neu
#   - Build-Cache bis 1 GB (der Rest wird beim nächsten Bau neu gefüllt, kostet nur Bauzeit)
#   - Testläufe unter logs/pipeline/<zeitstempel>/: die 15 neuesten, ältere nur, wenn jünger als 7 Tage.
#     Die Freigaben logs/pipeline/<sha>/ (b.ok, c_*.ok, d.json) sind winzig und bleiben immer.
set -uo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Testläufe liegen im Hauptrepo, auch wenn aus einem Worktree gestartet (Konvention wie scripts/pipeline.sh)
HAUPT="$(cd "$(git -C "$WURZEL" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
NUR_LOGS=0
[ "${1:-}" = "--nur-logs" ] && NUR_LOGS=1
vorher=$(df --output=avail -B1M / | tail -1)

# --- alte Testläufe -------------------------------------------------------------------------------------------------
LAEUFE="$HAUPT/logs/pipeline"
if [ -d "$LAEUFE" ]; then
  # Zeitstempel-Ordner (JJJJMMTT-HHMMSS), neueste zuerst; die ersten 15 bleiben
  ls -1d "$LAEUFE"/20[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | sort -r | tail -n +16 |
    while read -r ordner; do
      if [ -n "$(find "$ordner" -maxdepth 0 -mtime +7)" ]; then rm -rf "$ordner"; fi
    done
  # Videos sind der Großteil eines Laufs: in Läufen älter als 2 Tage nur die Videos löschen (Berichte bleiben)
  find "$LAEUFE" -mindepth 4 -maxdepth 5 -type d -name video -mtime +2 -prune -exec rm -rf {} + 2>/dev/null
fi

# pytest-Reste der Pipeline (TMPDIR liegt dort, nicht in der RAM-Disk /tmp): älter als einen Tag weg
find "${HOME}/.cache/lmc-e2e/tmp" -mindepth 1 -maxdepth 1 -mtime +1 -exec rm -rf {} + 2>/dev/null

if [ "$NUR_LOGS" = 0 ] && command -v docker >/dev/null 2>&1; then
  # --- Nestor-Bilder: je Reihe nur das neueste Tag -----------------------------------------------------------------
  for reihe in nestor-nestor nestor-staging-nestor-staging nestor-cloud; do
    docker images --format '{{.Repository}}:{{.Tag}} {{.CreatedAt}}' |
      awk -v r="$reihe" '{ split($1, t, ":"); n = t[1]; sub(/.*\//, "", n); if (n == r) print }' |
      sort -k2,3 -r | tail -n +3 |  # je Reihe gibt es das Bild doppelt (lokal + registry.cloudflare.com): 2 behalten
      awk '{print $1}' | xargs -r docker rmi >/dev/null 2>&1
  done
  # --- Build-Cache auf 1 GB begrenzen ------------------------------------------------------------------------------
  docker builder prune -f --max-used-space 1gb >/dev/null 2>&1
fi

nachher=$(df --output=avail -B1M / | tail -1)
echo "▸ Aufgeräumt: $(( (nachher - vorher) )) MB frei geworden, jetzt $(( nachher / 1024 )) GB frei auf /"
