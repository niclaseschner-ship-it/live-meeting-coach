#!/usr/bin/env bash
# Test-Pipeline (Ticket #61). Ein Einstieg für alle Stufen, Ergebnisse unter <Hauptrepo>/logs/pipeline/<zeitstempel>/.
#
#   scripts/pipeline.sh a                                   Stufe A: pytest + Worker-Tests + TypeScript (~1,5 min)
#   scripts/pipeline.sh b [--stufe basis|premium|beide] [--rauch]
#                                                           Stufe B: lokale Klick-E2E gegen Fake-Anbieter, 0 €
#   scripts/pipeline.sh c [--stufe premium|basis|beide]     Stufe C: dieselbe Klick-E2E gegen Staging mit ECHTEN
#                                                           Anbietern (Deckel je Lauf: Premium 1 €, Basis 0,30 €)
#   scripts/pipeline.sh d                                   Stufe D: Handy-Checkliste (docs/abnahme_manuell.md) abhaken
#
# A und B rufen keinen echten KI-Anbieter. C kostet echtes Geld und braucht vorher `deploy/deploy.sh --staging`
# (Staging muss den aktuellen Git-Stand tragen). Nichts hier deployt oder pusht. Temporäres liegt unter
# ~/.cache/lmc-e2e (auf dem Pi ist /tmp eine RAM-Disk). Stufe B prüft vorher, ob ≥ 2 GB Arbeitsspeicher frei sind.
# Freigaben fürs Deploy-Gate (an den Commit gebunden): logs/pipeline/<sha>/b.ok, c_<stufe>.ok, d.json.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${LMC_PYTHON:-$WURZEL/.venv/bin/python}"
[ -x "$PY" ] || PY="$(cd "$WURZEL" && git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/python"
TS="$(date +%Y%m%d-%H%M%S)"
# Berichte ins Hauptrepo (auch aus einem Worktree heraus), damit sie den Worktree überleben; logs/ ist gitignored
HAUPT="$(cd "$(git -C "$WURZEL" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
AUSGABE="${LMC_PIPELINE_AUSGABE:-$HAUPT/logs/pipeline}/$TS"
export TMPDIR="${HOME}/.cache/lmc-e2e/tmp"
mkdir -p "$TMPDIR"

stufe_a() {
  mkdir -p "$AUSGABE/a"
  local rc=0
  echo "▸ pytest"
  (cd "$WURZEL" && "$PY" -m pytest -q -p no:cacheprovider) 2>&1 | tee "$AUSGABE/a/pytest.log" || rc=1
  echo "▸ Worker: vitest"
  (cd "$WURZEL/cloudflare" && npx vitest run) 2>&1 | tee "$AUSGABE/a/vitest.log" || rc=1
  echo "▸ Worker: tsc --noEmit"
  (cd "$WURZEL/cloudflare" && npx tsc --noEmit) 2>&1 | tee "$AUSGABE/a/tsc.log" || rc=1
  if [ "$rc" = 0 ]; then echo "Stufe A grün · $AUSGABE/a"; else echo "Stufe A ROT · $AUSGABE/a" >&2; fi
  return "$rc"
}

stufe_b() {
  local rc=0
  (cd "$WURZEL" && "$PY" -m tests.e2e.lauf --ordner "$AUSGABE/b" "$@") || rc=$?
  # GATE_B_C (Ticket #65): deploy/deploy.sh will nicht erneut die ganze Klick-E2E fahren, sondern nur prüfen,
  # ob der Git-Stand, der deployt werden soll, hier schon grün war. Die Markierung gilt deshalb nur für einen
  # Lauf über BEIDE Stufen (Standard, ohne --stufe oder mit --stufe beide) – ein Lauf mit nur einer Stufe
  # prüft nicht genug für eine Freigabe und schreibt darum nichts.
  local stufenwahl="beide" vorheriges=""
  for arg in "$@"; do
    if [ "$vorheriges" = "--stufe" ]; then stufenwahl="$arg"; fi
    vorheriges="$arg"
  done
  if [ "$rc" = 0 ] && [ "$stufenwahl" = "beide" ]; then
    local sha
    sha="$(git -C "$WURZEL" rev-parse HEAD)"
    mkdir -p "$HAUPT/logs/pipeline/$sha"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$HAUPT/logs/pipeline/$sha/b.ok"
    echo "GATE_B_C: Freigabe für $sha geschrieben · $HAUPT/logs/pipeline/$sha/b.ok"
  fi
  return "$rc"
}

case "${1:-}" in
  a) shift; stufe_a "$@" ;;
  # Stufe C (Ticket #62): Staging hat genau einen Container – ein C-Lauf zur Zeit. Freigabe c_<stufe>.ok schreibt
  # tests/e2e/lauf_c.py selbst, je grüner Stufe, und nur wenn Staging genau HEAD trägt.
  c) shift; exec 8>"${HOME}/.cache/lmc-e2e/pipeline-c.lock"
     if ! flock -n 8; then echo "▸ Ein anderer Stufe-C-Lauf läuft – warte …"; flock 8; fi
     (cd "$WURZEL" && "$PY" -m tests.e2e.lauf_c --ordner "$AUSGABE/c" "$@") ;;
  d) shift; (cd "$WURZEL" && "$PY" scripts/abnahme_d.py "$@") ;;
  # Ein B-Lauf zur Zeit auf der Maschine: feste Ports (18000/18787, Fakes) und ~1,5 GB RAM – parallele Läufe aus
  # mehreren Worktrees würden sich gegenseitig rot färben. Wartet, statt abzubrechen.
  b) shift; exec 9>"${HOME}/.cache/lmc-e2e/pipeline-b.lock"
     # Unter einem äußeren `flock <dieselbe Datei> scripts/pipeline.sh …` hält der Elternprozess die Sperre schon –
     # dann nicht noch einmal warten (das wäre eine Selbstblockade).
     if ! flock -n 9; then
       if ps -o args= -p "$PPID" | grep -q 'pipeline-b.lock'; then :
       else echo "▸ Ein anderer Stufe-B-Lauf läuft – warte …"; flock 9; fi
     fi
     stufe_b "$@" ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 64 ;;
esac
