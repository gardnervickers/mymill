#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E /usr/bin/env bash "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive

arch="$(dpkg --print-architecture)"
case "${arch}" in
  amd64)
    kernel_meta_pkg="linux-image-amd64"
    ;;
  arm64)
    kernel_meta_pkg="linux-image-arm64"
    ;;
  *)
    echo "Unsupported Debian architecture for Lima GUI bring-up: ${arch}" >&2
    exit 1
    ;;
esac

rm -f /etc/apt/sources.list.d/linuxcnc.list

apt-get update
apt-get install -y ca-certificates curl dirmngr gnupg2

tmpdir="$(mktemp -d /tmp/.gnupgXXXXXX)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

gpg --homedir "$tmpdir" --keyserver hkp://keyserver.ubuntu.com --recv-key 3CB9FD148F374FEF
gpg --homedir "$tmpdir" --export "EMC Archive Signing Key" >/usr/share/keyrings/linuxcnc-old.gpg
gpg --homedir "$tmpdir" --keyserver hkp://keyserver.ubuntu.com --recv-key E43B5A8E78CC2927
gpg --homedir "$tmpdir" --export "LinuxCNC Archive Signing Key" >/usr/share/keyrings/linuxcnc.gpg

. /etc/os-release

if [[ -z "${VERSION_CODENAME:-}" ]]; then
  echo "VERSION_CODENAME is not set in /etc/os-release" >&2
  exit 1
fi

case "$VERSION_CODENAME" in
  buster|bullseye|bookworm)
    keyring="/usr/share/keyrings/linuxcnc-old.gpg"
    ;;
  *)
    keyring="/usr/share/keyrings/linuxcnc.gpg"
    ;;
esac

cat > /etc/apt/sources.list.d/linuxcnc.list <<EOF
deb [arch=amd64,arm64 signed-by=${keyring}] https://www.linuxcnc.org/ ${VERSION_CODENAME} base 2.9-uspace 2.9-rt
EOF

apt-get update
apt-get install -y \
  linuxcnc-uspace \
  linuxcnc-uspace-dev \
  openbox \
  xauth \
  xinit \
  xorg \
  xterm \
  "${kernel_meta_pkg}"

cat > /etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF

standard_kernel=""
while IFS= read -r kernel_path; do
  kernel_name="${kernel_path##*/vmlinuz-}"
  if [[ -n "${kernel_name}" ]]; then
    standard_kernel="${kernel_name}"
  fi
done < <(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' ! -name '*-cloud-*' | sort -V)

if [[ -n "${standard_kernel}" ]]; then
  if grep -q '^GRUB_DEFAULT=' /etc/default/grub; then
    sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub
  else
    printf '\nGRUB_DEFAULT=saved\n' >> /etc/default/grub
  fi

  if grep -q '^GRUB_SAVEDEFAULT=' /etc/default/grub; then
    sed -i 's/^GRUB_SAVEDEFAULT=.*/GRUB_SAVEDEFAULT=true/' /etc/default/grub
  else
    printf 'GRUB_SAVEDEFAULT=true\n' >> /etc/default/grub
  fi

  grub-set-default "Advanced options for Debian GNU/Linux>Debian GNU/Linux, with Linux ${standard_kernel}"
  update-grub
fi
