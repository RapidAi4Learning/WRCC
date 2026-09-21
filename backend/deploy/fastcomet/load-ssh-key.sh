#!/usr/bin/env bash
# GitHub runner only. Load an encrypted or unencrypted key into an ephemeral agent.
set -Eeuo pipefail
set +x
: "${SSH_PRIVATE_KEY:?Missing FASTCOMET_SSH_PRIVATE_KEY}"
: "${RUNNER_TEMP:?Missing RUNNER_TEMP}"
: "${GITHUB_ENV:?Missing GITHUB_ENV}"
umask 077
key_dir=$(mktemp -d "$RUNNER_TEMP/fastcomet-ssh.XXXXXXXX")
agent_started=false
cleanup() {
  status=$?
  if [[ $status != 0 && $agent_started == true ]]; then
    ssh-agent -k >/dev/null 2>&1 || true
  fi
  rm -f -- "$key_dir/key" "$key_dir/askpass" "$key_dir/askpass.used"
  rmdir -- "$key_dir"
}
trap cleanup EXIT
printf '%s\n' "$SSH_PRIVATE_KEY" | tr -d '\r' > "$key_dir/key"
unset SSH_PRIVATE_KEY
cat > "$key_dir/askpass" <<'SH'
#!/usr/bin/env bash
# One attempt only; an incorrect secret must fail rather than prompt forever.
[[ ! -e "$SSH_ASKPASS.used" ]] || exit 1
: > "$SSH_ASKPASS.used"
printf '%s\n' "${SSH_KEY_PASSPHRASE:-}"
SH
chmod 700 "$key_dir/askpass"
# The long-lived agent must not inherit the passphrase in its environment.
agent_environment=$(env -u SSH_KEY_PASSPHRASE ssh-agent -s)
eval "$agent_environment" >/dev/null
agent_started=true
export SSH_ASKPASS="$key_dir/askpass"
export SSH_ASKPASS_REQUIRE=force
export SSH_KEY_PASSPHRASE=${SSH_KEY_PASSPHRASE:-}
if ! ssh-add -q -t 30m "$key_dir/key" </dev/null; then
  echo 'Could not unlock SSH key. Check FASTCOMET_SSH_PRIVATE_KEY and FASTCOMET_SSH_PASSPHRASE.' >&2
  exit 1
fi
unset SSH_KEY_PASSPHRASE
# Only agent coordinates persist into subsequent steps, never the passphrase.
printf 'SSH_AUTH_SOCK=%s\nSSH_AGENT_PID=%s\n' "$SSH_AUTH_SOCK" "$SSH_AGENT_PID" >> "$GITHUB_ENV"
