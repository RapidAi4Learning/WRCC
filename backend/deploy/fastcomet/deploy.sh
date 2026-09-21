#!/usr/bin/env bash
# Run on Linux (GitHub Actions, WSL or a Linux workstation), from any directory.
set -Eeuo pipefail
for name in FASTCOMET_HOST FASTCOMET_USER FASTCOMET_APP_ROOT FASTCOMET_PYTHON FASTCOMET_HEALTH_URL; do
  [[ -n ${!name:-} ]] || { echo "Missing $name" >&2; exit 1; }
done
port=${FASTCOMET_PORT:-17177}
[[ $port =~ ^[0-9]+$ && $FASTCOMET_HOST =~ ^[a-zA-Z0-9.-]+$ && $FASTCOMET_USER =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
release=$(git -C "$repo" rev-parse HEAD)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/payload"
# Archive committed files only. No local .env, media, virtualenv or untracked files.
git -C "$repo" archive HEAD backend/app backend/migrations backend/alembic.ini backend/deploy/fastcomet/app | tar -x -C "$scratch"
cp -R "$scratch/backend/app" "$scratch/backend/migrations" "$scratch/payload/"
cp "$scratch/backend/alembic.ini" "$scratch/backend/deploy/fastcomet/app/"* "$scratch/payload/"
printf '%s\n' "$release" > "$scratch/payload/.deploy-release"
tar -czf "$scratch/backend.tar.gz" -C "$scratch/payload" .
target="$FASTCOMET_USER@$FASTCOMET_HOST"
ssh_opts=(-p "$port" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=20)
remote=$(ssh "${ssh_opts[@]}" "$target" 'umask 077; mktemp -d /tmp/wrcc-deploy.XXXXXXXX')
[[ $remote =~ ^/tmp/wrcc-deploy\.[a-zA-Z0-9]+$ ]] || { echo 'Invalid remote staging path' >&2; exit 1; }
cleanup() {
  ssh "${ssh_opts[@]}" "$target" "rm -rf -- '$remote'" || true
  rm -rf -- "$scratch"
}
trap cleanup EXIT
scp -P "$port" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=20 "$scratch/backend.tar.gz" "$target:$remote/backend.tar.gz"
# %q is Bash quoting; explicitly enter Bash before interpreting these arguments.
printf -v args '%q ' "$remote" "$FASTCOMET_APP_ROOT" "$FASTCOMET_PYTHON" "$FASTCOMET_HEALTH_URL" "$release"
printf -v command 'bash -c %q' "bash -s -- $args"
ssh "${ssh_opts[@]}" "$target" "$command" < "$repo/backend/deploy/fastcomet/deploy-remote.sh"
