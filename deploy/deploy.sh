#!/usr/bin/env bash
# deploy/deploy.sh (Ticket #65) – der EINE Weg, Nestor auszurollen. Ersetzt die nicht versionierten
# /tmp/nestor_deploy.py, /tmp/nestor_rollout.py, /tmp/nestor_ui56_rollout.py (RAM-Disk, hart kodierte IDs).
#
#   deploy/deploy.sh [--dry-run] [--ohne-b] [--ohne-c] [--ohne-d] [--erzwingen] [--tag-push]
#   deploy/deploy.sh --ref <tag-oder-commit> [--erzwingen]      Rollback/Re-Deploy eines älteren Stands
#   deploy/deploy.sh --staging [--dry-run] [--erzwingen]         Staging `nestor-staging` (Ticket #62)
#
# Siehe cloudflare/README.md, Abschnitt "Ausrollen und Zurückrollen", für die ausführliche Erklärung.
#
#   --dry-run     Git-Prüfung, scripts/pipeline.sh a, GATE_B_C, coach/version.json, `wrangler deploy --dry-run`
#                 (baut das Image wirklich, lokal) – aber KEIN echter Deploy, kein Rollout, kein Smoke-Test,
#                 kein Git-Tag. Braucht kein Cloudflare-Token.
#   --ohne-b      Deployt auch ohne grünes logs/pipeline/<sha>/b.ok (lauter Warnhinweis statt Abbruch).
#   --ohne-c      Deployt auch ohne grünes Stufe C (c_<stufe>.ok) für die betroffenen Stufen (lauter Warnhinweis).
#   --ohne-d      Deployt auch ohne Stufe-D-Checkliste (d.json), obwohl Handy/Audio geändert wurden (Warnhinweis).
#   --staging     Deployt den aktuellen (sauberen, nicht zwingend gepushten) Git-Stand nach `nestor-staging`
#                 (wrangler --env staging): legt vorher den R2-Bucket an, setzt fehlende Secrets
#                 (deploy/staging_einrichten.sh), wartet auf den Rollout, Smoke-Test gegen die Staging-URL. Keine
#                 Gates (Staging ist der Ort, an dem Stufe C erst läuft), kein Git-Tag. Danach: scripts/pipeline.sh c.
#   --erzwingen   Deployt auch wenn laut Cloudflare-API Container-Instanzen laufen.
#   --tag-push    Schiebt den neuen deploy-JJJJMMTT-HHMM-Tag zusätzlich zu origin (sonst bleibt er nur lokal).
#   --ref REF     Baut und deployt EXAKT diesen Tag/Commit statt des aktuellen Git-Stands (eigener, temporärer
#                 Git-Worktree) – für einen Rollback. Überspringt Tests/GATE_B_C (der Stand war schon mal
#                 live) und legt keinen neuen Tag an.
#
# Geheimnisse ausschließlich per Umgebungsvariable an wrangler/die Cloudflare-API, nie als Datei, nie in
# einem Log: `sudo -n zugang holen cloudflare-nestor`.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"
PY="${LMC_PYTHON:-$WURZEL/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
# Hauptrepo auch aus einem Worktree heraus (Konvention wie scripts/pipeline.sh) – GATE_B_C liegt dort.
HAUPT="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
WORKER_URL="${NESTOR_WORKER_URL:-https://nestor.niclas-eschner.workers.dev}"
STAGING_URL="${NESTOR_STAGING_URL:-https://nestor-staging.niclas-eschner.workers.dev}"

DRY_RUN=0 OHNE_B=0 OHNE_C=0 OHNE_D=0 ERZWINGEN=0 TAG_PUSH=0 REF="" STAGING=0
# Name der Container-Anwendung bei Cloudflare: <worker>-<klasse, klein> – prod "nestor-nestor"
ANWENDUNG_NAME="nestor-nestor"
WRANGLER_ENV=()

hilfe() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --ohne-b) OHNE_B=1 ;;
    --ohne-c) OHNE_C=1 ;;
    --ohne-d) OHNE_D=1 ;;
    --staging) STAGING=1 ;;
    --erzwingen) ERZWINGEN=1 ;;
    --tag-push) TAG_PUSH=1 ;;
    --ref) REF="${2:-}"; [ -n "$REF" ] || { echo "--ref braucht einen Tag oder Commit" >&2; exit 64; }; shift ;;
    -h|--hilfe|--help) hilfe; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; hilfe >&2; exit 64 ;;
  esac
  shift
done

if [ "$STAGING" = 1 ]; then
  [ -z "$REF" ] || { echo "--staging und --ref zusammen gibt es nicht." >&2; exit 64; }
  WORKER_URL="$STAGING_URL"
  ANWENDUNG_NAME="nestor-staging-nestor-staging"
  WRANGLER_ENV=(--env staging)
fi

log() { printf '▸ %s\n' "$1"; }
warnen() { printf '\n⚠️  %s\n\n' "$1" >&2; }
abbrechen() { printf '\n✖ %s\n' "$1" >&2; exit 1; }

# --- Git-Stand: sauber und beim Upstream (nur im Normalfall, nicht beim Rollback über --ref) -----------------
git_sauber_und_gepusht() {
  if [ -n "$(git status --porcelain)" ]; then
    abbrechen "Git-Stand nicht sauber (git status --porcelain zeigt etwas). Committen oder verwerfen, dann erneut."
  fi
  local oben
  if ! oben="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
    abbrechen "Kein Upstream-Branch gesetzt (git push -u origin <branch>), kann den Gleichstand nicht prüfen."
  fi
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse '@{u}')" ]; then
    abbrechen "HEAD ist nicht auf dem Stand von $oben – erst pushen oder pullen."
  fi
}

# --- Stufe A (pytest, Worker-Tests, TypeScript) -----------------------------------------------------------
tests_gruen() {
  log "scripts/pipeline.sh a (pytest + Worker-Tests + TypeScript)"
  "$WURZEL/scripts/pipeline.sh" a
}

# --- GATE_B_C: Stufe B (Klick-E2E, Basis + Premium) muss für GENAU diesen Commit grün gewesen sein -----------
gate_b_c() {
  local sha="$1" marker
  marker="$HAUPT/logs/pipeline/$sha/b.ok"
  if [ -f "$marker" ]; then
    log "GATE_B_C: Stufe B schon grün für $sha (Lauf vom $(cat "$marker"))"
    return 0
  fi
  if [ "$OHNE_B" = 1 ]; then
    warnen "GATE_B_C: KEIN grüner Stufe-B-Lauf für $sha ($marker fehlt) – mit --ohne-b TROTZDEM deployt. Das Klick-E2E (Basis + Premium, scripts/pipeline.sh b) hat diesen Stand nicht geprüft."
    return 0
  fi
  abbrechen "GATE_B_C: $marker fehlt. Erst 'scripts/pipeline.sh b' grün bekommen (läuft beide Stufen), oder ausdrücklich mit --ohne-b übersteuern."
}

# --- GATE_C_D (Ticket #62): Stufe C (Staging, echte Anbieter) für die betroffenen Stufen, ggf. Stufe D ------------
# Welche Stufen betroffen sind und ob es D braucht, sagt scripts/betroffene_stufen.py aus dem Diff seit dem letzten
# deploy-*-Tag (im Zweifel beide und D). Die Markierungen schreibt scripts/pipeline.sh c bzw. d, an den SHA gebunden.
gate_c_d() {
  local sha="$1" auswahl stufen d stufe fehlt=()
  auswahl="$(python3 "$WURZEL/scripts/betroffene_stufen.py")"
  stufen="$(printf '%s' "$auswahl" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["stufen"]))')"
  d="$(printf '%s' "$auswahl" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["d"]))')"
  log "GATE_C_D: betroffen laut Diff: ${stufen:-keine Stufe}; Stufe D nötig: $([ "$d" = 1 ] && echo ja || echo nein)"
  for stufe in $stufen; do
    if [ -f "$HAUPT/logs/pipeline/$sha/c_$stufe.ok" ]; then
      log "GATE_C_D: Stufe C $stufe grün für $sha (Lauf vom $(cat "$HAUPT/logs/pipeline/$sha/c_$stufe.ok"))"
    else
      fehlt+=("c_$stufe.ok")
    fi
  done
  if [ "${#fehlt[@]}" -gt 0 ]; then
    if [ "$OHNE_C" = 1 ]; then
      warnen "GATE_C_D: KEIN grünes Stufe C für $sha (${fehlt[*]} fehlt) – mit --ohne-c TROTZDEM deployt. Die echten Anbieter hat dieser Stand auf Staging nicht durchlaufen."
    else
      abbrechen "GATE_C_D: ${fehlt[*]} fehlt für $sha. Erst 'deploy/deploy.sh --staging' und 'scripts/pipeline.sh c --stufe beide' grün bekommen, oder ausdrücklich mit --ohne-c übersteuern."
    fi
  fi
  if [ "$d" = 1 ]; then
    if python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok") else 1)' \
         "$HAUPT/logs/pipeline/$sha/d.json" 2>/dev/null; then
      log "GATE_C_D: Stufe-D-Checkliste für $sha abgehakt"
    elif [ "$OHNE_D" = 1 ]; then
      warnen "GATE_C_D: Handy/Audio geändert, aber keine abgehakte Stufe D (d.json) für $sha – mit --ohne-d TROTZDEM deployt."
    else
      abbrechen "GATE_C_D: Handy/Audio geändert (oder kein Vergleichsstand) – Stufe D fehlt für $sha. Checkliste docs/abnahme_manuell.md am echten Handy gegen Staging, dann 'scripts/pipeline.sh d'. Oder ausdrücklich mit --ohne-d übersteuern."
    fi
  fi
}

# --- coach/version.json: GIT_SHA + Bauzeit ins Image (gitignored, siehe Dockerfile-Kommentar) ----------------
version_datei_schreiben() {
  local sha="$1" bauzeit
  bauzeit="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"git_sha": "%s", "gebaut_am": "%s"}\n' "$sha" "$bauzeit" > "$WURZEL/coach/version.json"
  echo "$bauzeit"
}

# --- Cloudflare-IDs: nie hart kodiert – aus Env-Überschreibung oder aus wrangler selbst ermittelt ------------
# WICHTIG für den ersten echten Deploy: diese beiden Abfragen gegen die tatsächliche wrangler-/API-Antwort
# prüfen (ungetestet in diesem Ticket – kein echter Deploy erlaubt). Schlägt eine fehl, einfach
# CLOUDFLARE_ACCOUNT_ID bzw. NESTOR_APPLICATION_ID von Hand exportieren (z. B. aus `wrangler whoami` bzw.
# `wrangler containers list` von Auge abgelesen) und erneut aufrufen.
cloudflare_konto_id() {
  if [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then echo "$CLOUDFLARE_ACCOUNT_ID"; return; fi
  (cd "$1/cloudflare" && npx wrangler whoami --json 2>/dev/null) | python3 -c '
import json, sys
d = json.load(sys.stdin)
konten = d.get("accounts") or []
if not konten:
    sys.exit(1)
print(konten[0]["id"])
' || "$PY" "$WURZEL/deploy/rollout_warten.py" konto \
    || abbrechen "Konnte CLOUDFLARE_ACCOUNT_ID weder aus 'wrangler whoami --json' noch aus /accounts lesen – bitte von Hand exportieren."
}

cloudflare_anwendung_id() {
  if [ -n "${NESTOR_APPLICATION_ID:-}" ]; then echo "$NESTOR_APPLICATION_ID"; return; fi
  (cd "$1/cloudflare" && npx wrangler containers list --json 2>/dev/null) | python3 -c '
import json, sys
for eintrag in json.load(sys.stdin):
    if eintrag.get("name") == sys.argv[1]:
        print(eintrag["id"])
        break
else:
    sys.exit(1)
' "$ANWENDUNG_NAME" || abbrechen "Konnte NESTOR_APPLICATION_ID nicht aus 'wrangler containers list --json' lesen (Name '$ANWENDUNG_NAME' erwartet) – bitte von Hand exportieren."
}

# --- Deploy-Gate: keine laufenden Meetings während des Rollouts -----------------------------------------------
keine_laufenden_instanzen() {
  if [ "$ERZWINGEN" = 1 ]; then
    warnen "Erzwungener Deploy (--erzwingen): laufende Container-Instanzen werden NICHT geprüft."
    return 0
  fi
  log "Prüfe laufende Container-Instanzen …"
  if ! "$PY" "$WURZEL/deploy/rollout_warten.py" instanzen; then
    abbrechen "Es laufen Container-Instanzen – kein Deploy während eines Meetings (R2 Abschnitt 3, U5). Mit --erzwingen übersteuern."
  fi
}

# --- Der eigentliche, echte Deploy (braucht das Cloudflare-Token, nur per Env) --------------------------------
echter_deploy() {
  local arbeitsordner="$1" sha="$2" bauzeit="$3"
  (
    cd "$arbeitsordner"
    set -euo pipefail
    export CLOUDFLARE_API_TOKEN
    CLOUDFLARE_API_TOKEN="$(sudo -n zugang holen cloudflare-nestor)"
    export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-$(cloudflare_konto_id "$arbeitsordner")}"
    # Beim allerersten Deploy einer Umgebung (Staging) gibt es noch keine Container-Anwendung – dann kann auch
    # nichts laufen; die ID wird nach dem Deploy ermittelt.
    if [ -n "${NESTOR_APPLICATION_ID:-}" ] || NESTOR_APPLICATION_ID="$(cloudflare_anwendung_id "$arbeitsordner" 2>/dev/null)"; then
      export NESTOR_APPLICATION_ID
      keine_laufenden_instanzen
    else
      unset NESTOR_APPLICATION_ID
      log "Noch keine Container-Anwendung $ANWENDUNG_NAME – erster Deploy dieser Umgebung, nichts kann laufen."
    fi

    if [ "$STAGING" = 1 ]; then
      "$WURZEL/deploy/staging_einrichten.sh" --nur-bucket
    fi
    log "wrangler deploy ${WRANGLER_ENV[*]} (GIT_SHA=$sha)"
    (cd "$arbeitsordner/cloudflare" && npx wrangler deploy "${WRANGLER_ENV[@]}" \
      --var "GIT_SHA:$sha" --var "BUILD_ZEIT:$bauzeit" --keep-vars)
    if [ "$STAGING" = 1 ] && ! (cd "$arbeitsordner/cloudflare" && npx wrangler secret list --env staging 2>/dev/null) \
         | grep -q '"WORKER_GEHEIMNIS"'; then
      log "Staging hat noch keine Secrets – setze sie (deploy/staging_einrichten.sh --nur-secrets)"
      "$WURZEL/deploy/staging_einrichten.sh" --nur-secrets
    fi
    export NESTOR_APPLICATION_ID="${NESTOR_APPLICATION_ID:-$(cloudflare_anwendung_id "$arbeitsordner")}"

    log "Ermittle das gerade ausgerollte Bild-Tag …"
    local bildtag
    bildtag="$("$PY" "$WURZEL/deploy/rollout_warten.py" neuester-tag)"

    log "Warte auf den Container-Rollout ($bildtag) …"
    "$PY" "$WURZEL/deploy/rollout_warten.py" warten --tag "$bildtag"

    log "Smoke-Test (Worker /version Pflicht, Container /api/version falls erreichbar)"
    "$PY" "$WURZEL/deploy/smoke.py" --worker-url "$WORKER_URL" --erwarteter-sha "$sha" \
      --kunden-cookie "${NESTOR_SMOKE_COOKIE:-}"
  )
}

git_tag_setzen() {
  local sha="$1" tag
  tag="deploy-$(date +%Y%m%d-%H%M)"
  git tag -a "$tag" "$sha" -m "Deploy $tag"
  log "Git-Tag $tag gesetzt (auf $sha)"
  if [ "$TAG_PUSH" = 1 ]; then
    git push origin "$tag"
    log "Tag $tag nach origin geschoben"
  else
    log "Tag $tag bleibt lokal (mit --tag-push zusätzlich schieben)"
  fi
}

# ============================================================================================================
if [ -n "$REF" ]; then
  # --- Rollback/Re-Deploy eines bestehenden Stands --------------------------------------------------------
  SHA="$(git rev-parse --verify "$REF^{commit}" 2>/dev/null)" || abbrechen "Unbekannte Referenz: $REF"
  log "Rollback/Re-Deploy von $REF ($SHA) – Tests und GATE_B_C übersprungen (dieser Stand war schon live)."
  ARBEITSORDNER="$(mktemp -d "${TMPDIR:-/tmp}/nestor-deploy-ref.XXXXXX")"
  # /tmp ist auf dem Pi eine RAM-Disk (siehe ~/.claude/CLAUDE.md) – ein Worktree-Checkout ist klein (Code,
  # kein .git), aber danach trotzdem aufräumen.
  trap 'git worktree remove --force "$ARBEITSORDNER" 2>/dev/null || rm -rf "$ARBEITSORDNER"' EXIT
  git worktree add --detach "$ARBEITSORDNER" "$SHA" >/dev/null
  ln -s "$WURZEL/modelle" "$ARBEITSORDNER/modelle" 2>/dev/null || true
  ln -s "$WURZEL/cloudflare/node_modules" "$ARBEITSORDNER/cloudflare/node_modules" 2>/dev/null || true
  BAUZEIT="$(version_datei_schreiben "$SHA")"
  cp "$WURZEL/coach/version.json" "$ARBEITSORDNER/coach/version.json"

  if [ "$DRY_RUN" = 1 ]; then
    log "Dry-Lauf: wrangler deploy --dry-run auf $ARBEITSORDNER"
    (cd "$ARBEITSORDNER/cloudflare" && npx wrangler deploy --dry-run)
    log "Dry-Lauf fertig – kein echter Deploy, kein Tag."
    exit 0
  fi

  echter_deploy "$ARBEITSORDNER" "$SHA" "$BAUZEIT"
  log "Rollback auf $REF ($SHA) fertig. Kein neuer Git-Tag (der Stand hat schon einen)."
  exit 0
fi

# --- Staging (Ticket #62): aktueller, sauberer Stand, ohne Gates und ohne Tag ----------------------------------
if [ "$STAGING" = 1 ]; then
  log "Staging: prüfe Git-Stand (sauber – gepusht muss er nicht sein) …"
  [ -z "$(git status --porcelain)" ] || abbrechen "Git-Stand nicht sauber – Staging trägt immer einen Commit (SHA-Bindung von Stufe C)."
  SHA="$(git rev-parse HEAD)"
  BAUZEIT="$(version_datei_schreiben "$SHA")"
  if [ "$DRY_RUN" = 1 ]; then
    (cd "$WURZEL/cloudflare" && npx wrangler deploy --env staging --dry-run)
    log "Dry-Lauf Staging fertig – kein echter Deploy."
    exit 0
  fi
  echter_deploy "$WURZEL" "$SHA" "$BAUZEIT"
  log "Staging-Deploy fertig: $SHA auf $WORKER_URL – weiter mit: scripts/pipeline.sh c --stufe beide"
  exit 0
fi

# --- Normaler Deploy des aktuellen Git-Stands ---------------------------------------------------------------
log "Prüfe Git-Stand (sauber, gepusht) …"
git_sauber_und_gepusht
SHA="$(git rev-parse HEAD)"

tests_gruen
gate_b_c "$SHA"
gate_c_d "$SHA"
BAUZEIT="$(version_datei_schreiben "$SHA")"
log "coach/version.json geschrieben (GIT_SHA=$SHA, gebaut_am=$BAUZEIT)"

if [ "$DRY_RUN" = 1 ]; then
  log "Dry-Lauf: wrangler deploy --dry-run (baut das Image wirklich, lokal – kein echter Deploy)"
  (cd "$WURZEL/cloudflare" && npx wrangler deploy --dry-run)
  log "Dry-Lauf fertig – kein echter Deploy, kein Git-Tag."
  exit 0
fi

echter_deploy "$WURZEL" "$SHA" "$BAUZEIT"
git_tag_setzen "$SHA"
log "Deploy fertig: $SHA"
