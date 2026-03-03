#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: lima_mymill_sim.sh [up|bootstrap|gui|shell]

Commands:
  up         Create/start the Lima VM and install LinuxCNC packages in the guest.
  bootstrap  Re-run the guest package bootstrap only.
  gui        Bring up the guest GUI stack and launch linuxcnc with sim/mymill-sim.ini.
  shell      Open an interactive shell in the guest at the repo root.

Environment:
  LIMA_INSTANCE  Lima instance name (default: mymill-sim)
  LIMA_VM_TYPE   Optional limactl --vm-type value, e.g. vz or qemu
  LIMA_VIDEO     Override video mode: 1 forces --video, 0 disables it
EOF
}

root_dir="${MYMILL_REPO_ROOT:-}"
if [[ -z "${root_dir}" ]]; then
  root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
root_dir="$(cd "${root_dir}" && pwd)"
instance="${LIMA_INSTANCE:-mymill-sim}"
command="${1:-up}"

if ! command -v limactl >/dev/null 2>&1; then
  echo "limactl is required on the host. Use 'nix run \"path:${root_dir}\"#mymill-lima-sim -- ${command}' or install Lima first." >&2
  exit 1
fi

instance_status() {
  limactl list --format '{{.Name}} {{.Status}}' | awk -v target="${instance}" '$1 == target { print $2 }'
}

start_vm() {
  local want_video="${1:-0}"
  local instance_dir="${LIMA_HOME:-${HOME}/.lima}/${instance}"
  local status=""
  local args=()
  if [[ -n "${LIMA_VM_TYPE:-}" ]]; then
    args+=(--vm-type "${LIMA_VM_TYPE}")
  fi
  if [[ -n "${LIMA_VIDEO:-}" ]]; then
    want_video="${LIMA_VIDEO}"
  fi
  if [[ "${want_video}" == "1" ]]; then
    args+=(--video)
  fi

  if [[ -d "${instance_dir}" ]]; then
    status="$(instance_status)"
    if [[ "${status}" == "Running" && ! -S "${instance_dir}/ha.sock" ]]; then
      if [[ "${want_video}" == "1" ]]; then
        recreate_vm "${want_video}"
        return
      fi

      echo "Existing Lima instance '${instance}' is in a stale state; forcing a stop and retry." >&2
      limactl stop "${instance}" >/dev/null 2>&1 || true
    fi

    if limactl start "${instance}" && limactl shell "${instance}" /bin/true >/dev/null 2>&1; then
      return
    fi

    if [[ "${want_video}" == "1" ]]; then
      recreate_vm "${want_video}"
      return
    fi

    echo "Existing Lima instance '${instance}' did not start cleanly; forcing a stop and retry." >&2
    limactl stop "${instance}" >/dev/null 2>&1 || true

    if limactl start "${instance}" && limactl shell "${instance}" /bin/true >/dev/null 2>&1; then
      return
    fi

    echo "Unable to start existing Lima instance '${instance}'." >&2
    exit 1
  fi

  limactl start \
    -y \
    --name "${instance}" \
    --mount-only "${root_dir}:w" \
    "${args[@]}" \
    "${root_dir}/lima/mymill-linuxcnc.yaml"
}

guest_shell() {
  limactl shell --start --workdir "${root_dir}" "${instance}" "$@"
}

guest_bash() {
  guest_shell /bin/bash -lc "$1"
}

bootstrap_guest() {
  guest_bash "cd '${root_dir}' && ./scripts/lima_guest_bootstrap.sh"
}

guest_needs_display_reboot() {
  guest_bash 'if [[ "$(uname -r)" == *-cloud-* ]] || [[ ! -e /dev/dri/card0 ]]; then exit 0; fi; exit 1'
}

guest_has_display_device() {
  guest_bash 'test -e /dev/dri/card0'
}

guest_has_active_x11() {
  guest_bash 'DISPLAY=:0 xset q >/dev/null 2>&1'
}

guest_has_linuxcnc() {
  guest_bash "pgrep -af linuxcncsvr | grep -F -- '${root_dir}/sim/mymill-sim.ini' >/dev/null 2>&1"
}

start_x11_session() {
  guest_bash 'rm -f ~/.Xauthority /tmp/mymill-x11.log && nohup startx /usr/bin/openbox-session -- :0 >/tmp/mymill-x11.log 2>&1 &'
}

wait_for_x11() {
  local attempt
  for attempt in {1..30}; do
    if guest_has_active_x11; then
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for the guest X11 session. Recent X11 log output:" >&2
  guest_bash 'tail -n 60 /tmp/mymill-x11.log 2>/dev/null || true' >&2
  return 1
}

reboot_vm() {
  limactl stop "${instance}" >/dev/null
  limactl start "${instance}" >/dev/null
}

recreate_vm() {
  local want_video="${1:-0}"
  echo "Recreating Lima instance '${instance}' to apply the required video settings." >&2
  limactl delete -f "${instance}" >/dev/null 2>&1 || true
  start_vm "${want_video}"
}

prepare_gui_guest() {
  bootstrap_guest
  if guest_needs_display_reboot; then
    reboot_vm
  fi
}

launch_gui() {
  if guest_has_linuxcnc; then
    echo "LinuxCNC is already running in the guest on DISPLAY=:0." >&2
    return 0
  fi

  if ! guest_has_active_x11; then
    start_x11_session
    wait_for_x11
  fi

  guest_bash "cd '${root_dir}' && export DISPLAY=:0 && exec linuxcnc -r sim/mymill-sim.ini"
}

case "${command}" in
  up)
    start_vm 0
    bootstrap_guest
    ;;
  bootstrap)
    bootstrap_guest
    ;;
  gui)
    start_vm 1
    prepare_gui_guest
    if ! guest_has_display_device; then
      recreate_vm 1
      prepare_gui_guest
    fi
    if ! guest_has_display_device; then
      echo "The guest still does not expose /dev/dri/card0 after recreation. Check the Lima video backend on the host." >&2
      exit 1
    fi
    launch_gui
    ;;
  shell)
    guest_shell /bin/bash
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
