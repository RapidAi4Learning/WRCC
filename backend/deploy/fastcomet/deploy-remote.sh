#!/usr/bin/env bash
# Invoked by deploy.sh over SSH. Never source the application's .env as shell code.
set -Eeuo pipefail
umask 077
stage=$1
app_root=$2
python=$3
health_url=$4
release=$5
[[ $stage =~ ^/tmp/wrcc-deploy\.[a-zA-Z0-9]+$ && $release =~ ^[a-f0-9]{40}$ ]] || exit 1
[[ $app_root = /* && $python = /* && $health_url = https://* ]] || { echo 'Use absolute paths and HTTPS' >&2; exit 1; }
for tool in flock tar curl; do command -v "$tool" >/dev/null; done
[[ -d $app_root && -x $python ]] || { echo 'Application directory or Python interpreter missing' >&2; exit 1; }
app_root=$(cd "$app_root" && pwd -P)
[[ $app_root != / && $app_root != "$HOME" ]] || exit 1
[[ -f $app_root/.env ]] || { echo 'A server-side .env is required; SSH does not inherit cPanel application variables.' >&2; exit 1; }
state=${FASTCOMET_STATE_DIR:-"$HOME/.local/state/wrcc-deploy"}
mkdir -p "$state"
state=$(cd "$state" && pwd -P)
[[ $state != "$app_root" && $state != "$app_root/"* ]] || { echo 'Backup directory must be outside the application root' >&2; exit 1; }
exec 9>"$state/deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
backup=$(mktemp -d "$state/$(date -u +%Y%m%dT%H%M%SZ)-${release:0:12}.XXXXXXXX")
managed=(app migrations alembic.ini passenger_wsgi.py bootstrap.py requirements.txt .deploy-release)
for name in "${managed[@]}" tmp; do
  [[ ! -L $app_root/$name ]] || { echo "Refusing symlink: $name" >&2; exit 1; }
done
phase=backup
failed() {
  echo "Deployment failed during $phase. Recovery files: $backup" >&2
  echo 'No automatic database downgrade or dependency rollback was attempted.' >&2
}
trap failed ERR
existing=()
for name in "${managed[@]}"; do
  [[ ! -e $app_root/$name ]] || existing+=("$name")
done
tar -czf "$backup/code.tar.gz" -C "$app_root" -- "${existing[@]}"
"$python" -m pip freeze > "$backup/requirements-before.txt"
printf '%s\n' "$app_root" > "$backup/app-root.txt"
mkdir "$stage/payload"
tar -xzf "$stage/backend.tar.gz" -C "$stage/payload" --no-same-owner
cd "$stage/payload"
[[ $(cat .deploy-release) = "$release" ]]
for name in "${managed[@]}"; do
  [[ -e $name && ! -L $name ]] || { echo "Missing or invalid payload path: $name" >&2; exit 1; }
done
ln -s "$app_root/.env" .env
phase=dependencies
echo '[1/4] Installing dependencies in the cPanel Python environment'
"$python" -m pip install --disable-pip-version-check -r requirements.txt
"$python" -m pip check
phase=migrations
echo '[2/4] Validating configuration and applying database migrations'
# Validate a production DSN before Alembic can fall back to local defaults.
"$python" - <<'PY'
from dotenv import dotenv_values
from app.config import get_settings
import sys
try:
    assert dotenv_values('.env').get('DATABASE_URL')
    settings = get_settings()
    assert settings.app_env == 'production'
    assert settings.database_url.startswith('postgresql+asyncpg://')
except Exception:
    # Pydantic errors can include credential values; don't expose them in CI logs.
    sys.exit('Invalid server .env: check production settings and PostgreSQL DATABASE_URL')
PY
"$python" -m alembic -c alembic.ini upgrade head
phase=activation
echo '[3/4] Activating code and requesting a Passenger restart'
# Replace only the explicitly managed paths. Persistent data and hosting files stay put.
# Moving whole packages also removes obsolete modules from previous releases.
mkdir "$backup/replaced"
for name in "${managed[@]}"; do
  if [[ -e $app_root/$name ]]; then mv -- "$app_root/$name" "$backup/replaced/$name"; fi
  cp -R -- "$stage/payload/$name" "$app_root/$name"
done
mkdir -p "$app_root/tmp"
touch "$app_root/tmp/restart.txt"
phase=health-check
echo '[4/4] Waiting for the new release and its database readiness check'
for attempt in {1..18}; do
  if curl --silent --show-error --fail --max-time 15 --proto '=https' \
    -H 'Cache-Control: no-cache' -D "$stage/headers" -o "$stage/health.json" \
    "${health_url}?deployment=${release}&attempt=${attempt}"; then
    if "$python" - "$stage/headers" "$stage/health.json" "$release" <<'PY'
import json
import sys
from pathlib import Path
headers = Path(sys.argv[1]).read_text().lower().splitlines()
body = json.loads(Path(sys.argv[2]).read_text())
ok = f'x-wrcc-release: {sys.argv[3]}' in headers
sys.exit(0 if ok and body.get('status') == 'ready' and body.get('database') == 'up' else 1)
PY
    then
      printf '%s\n' "$release" > "$backup/successful-release.txt"
      echo "Deployment verified: $release. Previous code: $backup/code.tar.gz"
      exit 0
    fi
  fi
  sleep 5
done
echo 'The new release did not become ready. Check cPanel restart and server logs.' >&2
failed
exit 1
