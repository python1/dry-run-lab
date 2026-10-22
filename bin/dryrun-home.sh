#!/usr/bin/env bash
# Data directory for one install.
# DRYRUN_HOME overrides. Otherwise use the path recorded in this checkout,
# then the path recorded for this user, then the default.

dryrun_resolve_home() {
  local root="$1"
  local recorded config
  if [[ -n "${DRYRUN_HOME:-}" ]]; then
    printf '%s\n' "$DRYRUN_HOME"
    return 0
  fi
  if [[ -f "$root/.dryrun-home" ]]; then
    recorded="$(head -n 1 "$root/.dryrun-home" | tr -d '\r')"
    if [[ -n "$recorded" ]]; then
      printf '%s\n' "$recorded"
      return 0
    fi
  fi
  config="${XDG_CONFIG_HOME:-$HOME/.config}/dryrun-lab/install-path"
  if [[ -f "$config" ]]; then
    recorded="$(head -n 1 "$config" | tr -d '\r')"
    if [[ -n "$recorded" ]]; then
      printf '%s\n' "$recorded"
      return 0
    fi
  fi
  printf '%s\n' "$HOME/.local/share/dryrun-lab"
}

dryrun_record_home() {
  local root="$1"
  local path="$2"
  local dir
  printf '%s\n' "$path" >"$root/.dryrun-home"
  dir="${XDG_CONFIG_HOME:-$HOME/.config}/dryrun-lab"
  mkdir -p "$dir"
  printf '%s\n' "$path" >"$dir/install-path"
}
