#!/usr/bin/env bash
# deploy/staging_einrichten.sh (Ticket #62) – richtet die Staging-Umgebung `nestor-staging` ein oder frischt ihre
# Secrets auf. Idempotent: ein zweiter Aufruf legt nichts doppelt an und erzeugt keine neuen Zufallswerte.
#
#   deploy/staging_einrichten.sh [--nur-bucket | --nur-secrets]
#
# Was es tut:
#   1. ~/.cache/lmc-e2e/staging.env (chmod 600) anlegen, falls sie fehlt: frischer Testzugang (Mail + sechs-
#      stelliger PIN, Ticket #75 – kein Passwortweg mehr), frisches COOKIE_GEHEIMNIS, WORKER_GEHEIMNIS und
#      PIN_GEHEIMNIS – NICHT von prod kopiert und bewusst NICHT in der Hausablage (Wegwerfwerte nur für
#      Staging; geht die Datei verloren, einfach löschen und neu einrichten).
#   2. R2-Bucket `nestor-spenden-staging` (EU-Jurisdiction) anlegen, falls er fehlt.
#   3. Secrets des Workers `nestor-staging` setzen (`wrangler secret put --env staging`), Werte ausschließlich per
#      Pipe: die Wegwerfwerte aus staging.env, die API-Schlüssel aus der Hausablage (`sudo -n zugang holen
#      openai-nestor` / `mistral-api-key` – Entscheidung Niclas 10.10.2026: Staging nutzt die Produktivschlüssel,
#      Schutz über den Deckel je Lauf in Stufe C). Keine TELEGRAM_*-Secrets: Staging meldet nichts an Niclas.
#
# Den Worker selbst deployt `deploy/deploy.sh --staging`. Der ruft vor dem Deploy `--nur-bucket` auf (die Bindung
# braucht den Bucket) und danach `--nur-secrets`, falls dem Worker noch Secrets fehlen (ein Secret auf einen noch
# nie deployten Worker würde dort nur einen leeren Entwurf anlegen).
# Nichts hier gibt einen Geheimwert aus oder schreibt ihn in ein Log.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING_ENV="${LMC_STAGING_ENV:-$HOME/.cache/lmc-e2e/staging.env}"
BUCKET="nestor-spenden-staging"
BUCKET_JA=1 SECRETS_JA=1
case "${1:-}" in
  --nur-bucket) SECRETS_JA=0 ;;
  --nur-secrets) BUCKET_JA=0 ;;
  "") ;;
  *) echo "Unbekannte Option: $1" >&2; exit 64 ;;
esac

log() { printf '▸ %s\n' "$1"; }

# --- 1. Wegwerfwerte ------------------------------------------------------------------------------------------------
if [ ! -f "$STAGING_ENV" ]; then
  log "Lege $STAGING_ENV mit frischen Zufallswerten an (chmod 600)"
  mkdir -p "$(dirname "$STAGING_ENV")"
  ( umask 077
    {
      echo "# Staging-Wegwerfwerte (Ticket #62/#75) – nicht von prod, nicht in der Hausablage. Nie committen."
      echo "STAGING_URL=https://nestor-staging.niclas-eschner.workers.dev"
      echo "STAGING_TESTZUGANG_MAIL=testzugang@nestor-staging.lokal"
      echo "STAGING_TESTZUGANG_PIN=$(python3 -c 'import secrets; print(f"{secrets.randbelow(1000000):06d}")')"
      echo "STAGING_WORKER_GEHEIMNIS=$(openssl rand -hex 32)"
      echo "STAGING_COOKIE_GEHEIMNIS=$(openssl rand -hex 32)"
      echo "STAGING_PIN_GEHEIMNIS=$(openssl rand -hex 32)"
    } > "$STAGING_ENV" )
fi
# Ältere staging.env (vor #75, mit Testpasswort) um den Testzugang ergänzen statt neu anzulegen
if ! grep -q '^STAGING_TESTZUGANG_MAIL=' "$STAGING_ENV"; then
  log "Ergänze Testzugang (Ticket #75) in $STAGING_ENV"
  { echo "STAGING_TESTZUGANG_MAIL=testzugang@nestor-staging.lokal"
    echo "STAGING_TESTZUGANG_PIN=$(python3 -c 'import secrets; print(f"{secrets.randbelow(1000000):06d}")')"
  } >> "$STAGING_ENV"
fi
chmod 600 "$STAGING_ENV"
wert() { sed -n "s/^$1=//p" "$STAGING_ENV"; }

export CLOUDFLARE_API_TOKEN
CLOUDFLARE_API_TOKEN="$(sudo -n zugang holen cloudflare-nestor)"
# Das Konto-Token kann /memberships nicht lesen (wrangler whoami scheitert) – Konto-ID aus /accounts
export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-$(python3 "$WURZEL/deploy/rollout_warten.py" konto)}"
cd "$WURZEL/cloudflare"

# --- 2. R2-Bucket -----------------------------------------------------------------------------------------------------
if [ "$BUCKET_JA" = 1 ]; then
  if npx wrangler r2 bucket list --jurisdiction eu 2>/dev/null | grep -q "^name: *$BUCKET\$"; then
    log "R2-Bucket $BUCKET (eu) vorhanden"
  else
    log "Lege R2-Bucket $BUCKET (eu) an"
    npx wrangler r2 bucket create "$BUCKET" --jurisdiction eu
  fi
fi

# --- 3. Secrets --------------------------------------------------------------------------------------------------------
[ "$SECRETS_JA" = 1 ] || exit 0
setzen() {  # setzen <NAME>  – Wert kommt über stdin
  npx wrangler secret put "$1" --env staging >/dev/null && log "Secret $1 gesetzt"
}
wert STAGING_WORKER_GEHEIMNIS | tr -d '\n' | setzen WORKER_GEHEIMNIS
wert STAGING_COOKIE_GEHEIMNIS | tr -d '\n' | setzen COOKIE_GEHEIMNIS
wert STAGING_PIN_GEHEIMNIS | tr -d '\n' | setzen PIN_GEHEIMNIS
# TESTZUGANG (Ticket #75): Mail + Hash des Wegwerf-PIN (Klartext verlässt staging.env nie). Nie für prod –
# dort blockiert zusätzlich WORKER_NAME="nestor" im Code (pilotzugang.ts, testzugangErlaubt).
PIN_HASH="$(wert STAGING_TESTZUGANG_PIN | tr -d '\n' | sha256sum | cut -d' ' -f1)"
printf '{"mail": "%s", "pinHash": "%s"}' "$(wert STAGING_TESTZUGANG_MAIL)" "$PIN_HASH" | setzen TESTZUGANG
sudo -n zugang holen openai-nestor | tr -d '\n' | setzen OPENAI_API_KEY
sudo -n zugang holen mistral-api-key | tr -d '\n' | setzen MISTRAL_API_KEY
log "Staging-Secrets vollständig (Telegram bewusst aus)."
