#!/usr/bin/env bash
# Integration checks with a fake host, pip, database and HTTP endpoint.
set -Eeuo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
scratch=$(mktemp -d /tmp/wrcc-tests.XXXXXXXX)
[[ $scratch = /tmp/wrcc-tests.* ]] || exit 1
trap 'rm -rf -- "$scratch"' EXIT
real_python=$(command -v python || command -v python3)
export REAL_PYTHON="$real_python"
mkdir "$scratch/bin"
cat > "$scratch/bin/python" <<'SH'
#!/usr/bin/env bash
set -eu
if [[ ${1:-} == -m ]]; then
  echo "$*" >> "$TEST_CASE/calls"
  case "$*" in
    '-m pip freeze') echo 'old-package==1.0' ;;
    '-m pip install'*) [[ ${FAIL_PHASE:-} != dependencies ]] ;;
    '-m alembic'*) [[ ${FAIL_PHASE:-} != migrations ]] ;;
  esac
elif [[ $# == 1 && $1 == - ]]; then
  cat >/dev/null # Host configuration import: isolated from developer credentials.
else
  exec "$REAL_PYTHON" "$@"
fi
SH
cat > "$scratch/bin/curl" <<'SH'
#!/usr/bin/env bash
set -eu
while [[ $# -gt 0 ]]; do
  case "$1" in
    -D) headers=$2; shift ;;
    -o) body=$2; shift ;;
  esac
  shift
done
revision=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
[[ ${FAIL_PHASE:-} != stale ]] || revision=old
printf 'HTTP/1.1 200 OK\r\nX-WRCC-Release: %s\r\n\r\n' "$revision" > "$headers"
printf '{"status":"ready","database":"up"}' > "$body"
SH
printf '#!/usr/bin/env bash\nexit 0\n' > "$scratch/bin/sleep"
printf '#!/usr/bin/env bash\n[[ ${FAIL_PHASE:-} != lock ]]\n' > "$scratch/bin/flock"
chmod +x "$scratch/bin/"*
export PATH="$scratch/bin:$PATH"
for scenario in success dependencies migrations stale lock; do
  export TEST_CASE="$scratch/$scenario" FAIL_PHASE="$scenario"
  mkdir -p "$TEST_CASE/home" "$TEST_CASE/live/app" "$TEST_CASE/live/media" "$TEST_CASE/payload/app" "$TEST_CASE/payload/migrations"
  printf 'old' > "$TEST_CASE/live/app/obsolete.py"
  printf 'private' > "$TEST_CASE/live/.env"
  printf 'hosting' > "$TEST_CASE/live/.htaccess"
  printf 'photo' > "$TEST_CASE/live/media/photo.jpg"
  printf 'new' > "$TEST_CASE/payload/app/main.py"
  for name in alembic.ini passenger_wsgi.py bootstrap.py requirements.txt; do
    printf 'new' > "$TEST_CASE/payload/$name"
  done
  printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$TEST_CASE/payload/.deploy-release"
  stage=$(mktemp -d /tmp/wrcc-deploy.XXXXXXXX)
  tar -czf "$stage/backend.tar.gz" -C "$TEST_CASE/payload" .
  result=0
  # Confine all backup writes to the fixture.
  env FASTCOMET_STATE_DIR="$TEST_CASE/home/.local/state/wrcc-deploy" bash "$script_dir/deploy-remote.sh" "$stage" "$TEST_CASE/live" \
    "$scratch/bin/python" https://example.invalid/api/health/ready \
    aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa > "$TEST_CASE/output" 2>&1 || result=$?
  [[ $stage = /tmp/wrcc-deploy.* ]] && rm -rf -- "$stage"
  [[ $(cat "$TEST_CASE/live/.env") == private ]]
  [[ $(cat "$TEST_CASE/live/.htaccess") == hosting ]]
  [[ $(cat "$TEST_CASE/live/media/photo.jpg") == photo ]]
  if [[ $scenario == success ]]; then
    [[ $result == 0 ]] || { cat "$TEST_CASE/output"; exit 1; }
    [[ -f $TEST_CASE/live/tmp/restart.txt && ! -e $TEST_CASE/live/app/obsolete.py ]]
    [[ $(cat "$TEST_CASE/live/app/main.py") == new ]]
    backup=("$TEST_CASE/home/.local/state/wrcc-deploy/"*/code.tar.gz)
    [[ $(tar -xOf "${backup[0]}" app/obsolete.py) == old ]]
    grep -q 'Deployment verified:' "$TEST_CASE/output"
  else
    [[ $result != 0 ]] || { echo "Unexpected success: $scenario"; exit 1; }
    if [[ $scenario != stale ]]; then
      [[ ! -e $TEST_CASE/live/tmp/restart.txt ]]
      [[ $(cat "$TEST_CASE/live/app/obsolete.py") == old ]]
    fi
    if [[ $scenario == dependencies ]]; then
      ! grep -q alembic "$TEST_CASE/calls"
    fi
  fi
  echo "PASS: $scenario (persistent files preserved)"
done
