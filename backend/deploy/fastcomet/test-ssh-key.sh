#!/usr/bin/env bash
# Real OpenSSH, disposable local keys. No server or production secrets involved.
set -Eeuo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
scratch=$(mktemp -d /tmp/wrcc-ssh-tests.XXXXXXXX)
[[ $scratch = /tmp/wrcc-ssh-tests.* ]] || exit 1
cleanup() {
  if [[ -n ${SSH_AGENT_PID:-} ]]; then ssh-agent -k >/dev/null 2>&1 || true; fi
  rm -rf -- "$scratch"
}
trap cleanup EXIT
unset SSH_AGENT_PID SSH_AUTH_SOCK
test_phrase='temporary test phrase $ with "quotes"'
ssh-keygen -q -t ed25519 -N "$test_phrase" -f "$scratch/encrypted"
ssh-keygen -q -t ed25519 -N '' -f "$scratch/plain"
for scenario in encrypted wrong missing plain; do
  export RUNNER_TEMP="$scratch" GITHUB_ENV="$scratch/agent-env"
  : > "$GITHUB_ENV"
  key=encrypted
  [[ $scenario != plain ]] || key=plain
  export SSH_PRIVATE_KEY="$(cat "$scratch/$key")"
  export SSH_KEY_PASSPHRASE="$test_phrase"
  [[ $scenario != wrong ]] || SSH_KEY_PASSPHRASE=incorrect
  [[ $scenario != missing && $scenario != plain ]] || SSH_KEY_PASSPHRASE=''
  result=0
  bash "$script_dir/load-ssh-key.sh" > "$scratch/output" 2>&1 || result=$?
  unset SSH_PRIVATE_KEY SSH_KEY_PASSPHRASE
  if [[ $scenario == encrypted || $scenario == plain ]]; then
    [[ $result == 0 ]] || { cat "$scratch/output"; exit 1; }
    set -a
    source "$GITHUB_ENV"
    set +a
    ssh-add -T "$scratch/$key.pub"
    ssh-agent -k >/dev/null
    unset SSH_AGENT_PID SSH_AUTH_SOCK
  else
    [[ $result != 0 && ! -s $GITHUB_ENV ]]
    grep -q 'Could not unlock SSH key' "$scratch/output"
  fi
  ! grep -Fq -- "$test_phrase" "$scratch/output"
  ! grep -Fq -- "$test_phrase" "$GITHUB_ENV"
  shopt -s nullglob
  remaining=("$scratch"/fastcomet-ssh.*)
  [[ ${#remaining[@]} == 0 ]]
  echo "PASS: SSH key $scenario (temporary files removed)"
done
