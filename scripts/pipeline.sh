#!/usr/bin/env bash
# Test-Pipeline (Ticket #61). Ein Einstieg für alle Stufen, Ergebnisse unter logs/pipeline/<zeitstempel>/.
#
#   scripts/pipeline.sh a                                   Stufe A: pytest + Worker-Tests + TypeScript (~1,5 min)
#   scripts/pipeline.sh b [--stufe basis|premium|beide] [--rauch]
#                                                           Stufe B: lokale Klick-E2E gegen Fake-Anbieter, 0 €
#
# Nichts hier ruft einen echten KI-Anbieter, deployt oder pusht. Temporäres liegt unter ~/.cache/lmc-e2e
# (auf dem Pi ist /tmp eine RAM-Disk). Stufe B prüft vorher, ob ≥ 2 GB Arbeitsspeicher frei sind.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${LMC_PYTHON:-$WURZEL/.venv/bin/python}"
[ -x "$PY" ] || PY="$(cd "$WURZEL" && git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/python"
TS="$(date +%Y%m%d-%H%M%S)"
AUSGABE="$WURZEL/logs/pipeline/$TS"
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
  (cd "$WURZEL" && "$PY" -m tests.e2e.lauf --ordner "$AUSGABE/b" "$@")
}

case "${1:-}" in
  a) shift; stufe_a "$@" ;;
  b) shift; stufe_b "$@" ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 64 ;;
esac
