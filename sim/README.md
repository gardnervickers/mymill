# Simulator scaffold

This directory is a Linux-only startup scaffold for LinuxCNC. It is not meant to replace the real machine config. It exists so you can validate that LinuxCNC starts, the INI parses, and the HAL graph loads without Mesa hardware or the XHC pendant.

## What it does

- Reuses the same `XYZA` kinematics and joint limits as the real config.
- Avoids `hm2_eth`, Mesa pins, and the pendant userspace component.
- Loops commanded joint position directly into motor feedback so axes track perfectly.
- Stubs home, limit, probe, spindle, tool-change, and estop signals to safe defaults.

## Mac workflow

On macOS, use the static linter first:

```sh
nix develop "path:$PWD"
python scripts/hal_lint.py
```

or:

```sh
nix run "path:$PWD"#hal-lint
```

That catches wiring regressions without needing LinuxCNC.

## Linux simulator workflow

Run this config inside a Linux VM or host with LinuxCNC installed:

```sh
linuxcnc sim/mymill-sim.ini
```

This should be treated as a startup and config-integrity check, not a fidelity test for real hardware timing or UI plugins.

## Spindle command test

The sim cannot reproduce the real 7i76E TB4 electrical behavior, but it can validate the LinuxCNC command flow for the open-loop spindle setup.

The sim exports these monitor signals:

- `spindle-enable`
- `spindle-fwd`
- `spindle-rev`
- `spindle-speed-loopback`

You can inspect them with `halcmd show sig spindle-` or with HAL Meter/HAL Show while Axis is running.

In Axis MDI, use this sequence:

```ngc
M3 S1000
M5
M4 S1000
M5
```

Expected behavior:

- `M3 S1000`: `spindle-enable=true`, `spindle-fwd=true`, `spindle-rev=false`
- `M4 S1000`: `spindle-enable=true`, `spindle-fwd=false`, `spindle-rev=true`
- `M5`: all three go false

`spindle-speed-loopback` should follow the absolute commanded spindle speed, so `spindle.0.speed-in` behaves like an open-loop feedback echo.

## Lima on macOS

Lima is a reasonable way to host the Linux VM, but keep the expectations narrow:

- The LinuxCNC simulator itself belongs inside the Linux guest, not on macOS.
- GUI support in Lima is possible, but the built-in VNC display path is still experimental.
- If GUI forwarding is unreliable, the fallback is still useful: use Lima for Linux-only startup checks and keep the day-to-day static validation on the Mac host via `nix run "path:$PWD"#hal-lint`.

This repo now includes a Lima template at `lima/mymill-linuxcnc.yaml`, a guest bootstrap script at `scripts/lima_guest_bootstrap.sh`, and a host wrapper at `scripts/lima_mymill_sim.sh`.

The flake exposes the wrapper, but it intentionally uses the host `limactl` binary instead of bundling Lima from the pinned `nixos-25.05` input, because that package is currently marked insecure in that channel.

The wrapper is exposed through the flake, so the default flows are:

```sh
nix run "path:$PWD"#mymill-lima-sim -- gui
```

On a fresh instance, this now does the full GUI bring-up path:

- creates the VM with video enabled
- mounts the repo as the only writable mount
- installs `linuxcnc-uspace`, the X11/Openbox packages, and the full Debian kernel
- switches GRUB away from the cloud kernel so `virtio_gpu` is available
- reboots once if needed
- starts X11 in the guest and launches `linuxcnc sim/mymill-sim.ini`

If you only want to pre-bootstrap the VM without opening `axis`, use:

```sh
nix run "path:$PWD"#mymill-lima-sim -- up
```

That prepares the guest packages and kernel, but does not start X11 or LinuxCNC.

If you want to force a backend, set `LIMA_VM_TYPE=vz` or `LIMA_VM_TYPE=qemu`.
