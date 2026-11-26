# Sailfish OS x86_64 Live

English | [简体中文](README.zh-CN.md)

This live image runs the Sailfish OS 5.2.0.22 i486 userspace on Ubuntu Base 24.04.5 amd64 with the generic Ubuntu kernel. The root filesystem starts from the official Sailfish SDK 5.1.0.11 emulator image and is upgraded using the official 5.2.0.22 repositories. The lock screen and home screen default to landscape. Normal boot tries GPU rendering and falls back to software rendering if the GPU or buffer sharing checks fail. The basic graphics boot option always uses software rendering.

## How it works

- GRUB supports BIOS and x86_64 UEFI boot.
- casper boots Ubuntu from SquashFS and saves changes to a persistence volume labeled `writable`. If that volume is absent, it keeps changes in RAM.
- systemd-nspawn runs Sailfish and its user session in a container. The container has `CAP_SYS_TIME` so the Sailfish clock service can set the system time.
- Xorg and Weston 9 display Lipstick's nested Wayland output. Weston 9 provides the legacy `wl_shell` protocol used by Qt 5.6.
- Mesa 25.2.8 is built from a fixed source release for amd64 and i386, with `EGL_WL_bind_wayland_display` and `wl_drm` enabled for Qt 5.6. Weston uses the amd64 build; Lipstick and Sailfish apps use the i386 build.
- [`src/wayland-parent.c`](src/wayland-parent.c) handles Lipstick's use of `WAYLAND_DISPLAY` as both a server and a client, including Wayland clients loaded on demand by GLVND. The launcher uses `sg` to preserve Lipstick's `privileged` group membership.
- The container can access `/dev/dri`, and its hardware group IDs match the Ubuntu host's. The graphics library cache lets the app preloader and regular apps load the same Mesa build.
- Ubuntu's NetworkManager manages physical network connections. Sailfish ConnMan connects automatically over virtual Ethernet. A systemd path unit syncs upstream DNS settings to a root-owned copy that Sailfish and sandboxed apps can read.
- The container's Ethernet interface is named `wlan0` before ConnMan starts. It gets an address over wired DHCP, and the developer settings show its actual IPv4 address.
- systemd-networkd manages the address pool, DHCP, and NAT for the dedicated `sfos0` bridge. The gateway address stays the same when the container reconnects.

## Build the image

Run this from the repository root, using a work directory you can write to:

```bash
SFOS_WORK="$HOME/sfos-live-work" ./build.sh
```

Downloads, caches, extracted files, and logs go under `SFOS_WORK`. If unset, the script uses `/home/bird/data/tmp/sfos-live`. The ISO is written to `dist/`.

The build uses user namespaces and subordinate UID/GID mappings. The host needs `lxc-usernsexec`, `unshare`, GCC, Python 3, QEMU tools, 7-Zip, rsync, and SquashFS tools. The script extracts `fuse2fs` into the work directory and installs image creation tools inside the Ubuntu root filesystem.

Base image versions are pinned and verified by SHA256. Ubuntu packages come from the Noble repositories. The installed versions are listed in [`dist/ubuntu-packages.tsv`](dist/ubuntu-packages.tsv) and [`dist/sailfish-packages.tsv`](dist/sailfish-packages.tsv), and the downloaded inputs are recorded in [`dist/inputs.json`](dist/inputs.json). [`config/release.json`](config/release.json) sets the target version, and each version has a separate root filesystem cache.

Mesa build dependencies, including amd64 and i386 development libraries, are installed in `$SFOS_WORK/build/graphics-sdk`. The graphics sources, build options, and file checksums are recorded in [`dist/graphics-amd64.json`](dist/graphics-amd64.json) and [`dist/graphics-i386.json`](dist/graphics-i386.json). The SDK package versions are listed in [`dist/graphics-sdk-packages.tsv`](dist/graphics-sdk-packages.tsv). The first build downloads the dependencies and compiles Mesa for both architectures.

The current image uses the SDK's original package set. Installation of extra packages is disabled.

## Boot the image

Write the generated `dist/sailfish-live-5.2.0.22-amd64.iso` to a USB drive and select it in the BIOS or UEFI boot menu. Disable Secure Boot when using UEFI to boot this image.

The default GRUB entry requests persistence. The menu offers basic graphics entries for both persistent and temporary sessions. Basic graphics adds `nomodeset`; temporary sessions add `nopersistent`.

Click and drag sideways to unlock the screen. Drag up from the bottom to open the app drawer, or swipe inward from either side of an app to return to the home screen.

On QEMU with TCG, graphics initialization can take a while. If the display goes idle, move the mouse to wake it.

## Save changes across reboots

Persistence requires the `persistent` boot option and an ext4 partition labeled `writable`. If casper cannot find that partition, it keeps changes in RAM and discards them on reboot.

For VMware, you can use `dist/sailfish-persistence-16G.vmdk` if you have a copy, or create a new VMDK on the build host:

```bash
python3 scripts/create-persistence-disk.py /path/to/sailfish-data.vmdk --size 32G
```

The script creates a new VMDK with a GPT partition table and a `writable` ext4 partition. It does not modify physical disks or overwrite existing files. With the VM powered off, add the VMDK as an existing virtual disk in the hardware settings. Keep the Live ISO attached and choose **Sailfish OS Live (persistent)**. Reuse the same virtual disk after a normal shutdown. The 16 GiB image starts small and grows as data is written.

After booting, check the Ubuntu console:

```bash
cat /run/sailfish-persistence/mode
cat /run/sailfish-persistence/filesystem
```

If the mode is `persistent` and the filesystem is `ext4`, changes are being saved. A mode of `temporary` means changes will be lost on reboot. The boot log also reports the active mode. Persistence covers Ubuntu configuration and `/opt/sailfish/rootfs`, including Sailfish apps, user files, settings, the developer password, and the SSH setting. Runtime directories such as `/run` are recreated on each boot.

Persistence was verified across two complete QEMU boots and normal shutdowns. Ubuntu and Sailfish system and user files, Sailfish user file ownership, and the SSH enabled state all survived a reboot. See [`dist/persistence-validation.json`](dist/persistence-validation.json). The test used a separate disk and left the 16 GiB image in its initial state.

To repeat the test with a separate disk, you need access to the `qemu:///system` libvirt service:

```bash
python3 scripts/create-persistence-disk.py /path/to/test-data.vmdk --size 2G
python3 scripts/test-persistence-vm.py \
  --iso dist/sailfish-live-5.2.0.22-amd64.iso \
  --disk /path/to/test-data.vmdk --directory /path/to/new-test-results
```

On older images, press `e` in GRUB, append `persistent` to the `linux` line, then press `Ctrl+X` to boot. This changes the options for that boot only. The current image already includes dedicated menu entries.

## Console and networking

The Ubuntu console user is `live` and can run `sudo` without a password. The Sailfish user is `defaultuser`, with the default password `live`.

SSH access to Sailfish is off by default. In **Settings → Developer mode**, enable remote connections and set the login password. Connect to the Ubuntu host's IP address on port 2222:

```bash
ssh -p 2222 defaultuser@<ubuntu-host-ip>
```

Replace `<ubuntu-host-ip>` with the host's actual IP address. The host socket forwards connections to port 22 in the container. Disabling remote connections stops the Sailfish SSH service. The graphical user belongs to the `sailfish-system` group so the settings app can use Sailfish's native password service, which manages the SSH configuration.

Press `Ctrl+Alt+F2` to switch to the Ubuntu console and configure Wi-Fi with NetworkManager:

```bash
nmcli device
nmcli device wifi list
sudo nmcli --ask device wifi connect "YOUR_SSID"
```

To inspect boot logs and container status:

```bash
sudo journalctl -u sailfish-live.service -b
sudo machinectl list
sudo journalctl -M sailfish -b
```

## Known limitations

The image combines 64-bit Ubuntu and 32-bit Sailfish. GPU, Wi-Fi, audio, and touchscreen compatibility on physical hardware still need testing. Sailfish's Wi-Fi settings still need to be integrated with NetworkManager on the host.

Store downloads require a Jolla account. Account sign-in and app downloads have not been verified.

## Validation

The November 24, 2026 build of 5.2.0.22 was tested with GPU rendering and software fallback. The Settings app, GPU access from the sandboxed calculator, and enabling and disabling SSH through Developer mode were verified, including a password login through host port 2222. A user reported about 50 FPS in VMware with 3D acceleration enabled. See the [graphics build and testing notes (Chinese)](GRAPHICS.md) for the test procedure.

Earlier builds were tested with QEMU 6.2, 4 vCPUs, 4 GiB of RAM, and TCG:

| Check | Result |
| --- | --- |
| BIOS and UEFI boot from the ISO to the Sailfish lock screen | Passed |
| Standard VGA and `nomodeset` graphics | Passed using the generated kernel and initramfs directly |
| Mouse unlock, app drawer, and Settings app | Passed |
| Landscape lock screen, home screen, and app drawer | Passed |
| HTTPS browsing, Store launch, and Developer mode settings | Passed |
| Dynamic DNS updates and sandboxed app launch | Passed |
| `timed` clock service | Passed |
| Container DHCP, DNS, and HTTPS access | Passed |
| Gateway and connectivity after restarting ConnMan or the entire Sailfish session | Passed |
| Sailfish audio playback | Passed; QEMU's WAV backend captured nonzero PCM data |
| ISO SHA256 verification | Passed |

See the [Sailfish screenshot](dist/sailfish-live.png). The base images and compatibility components come from the official [Ubuntu Base](https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/), [Sailfish SDK emulator](https://releases.sailfishos.org/sdk/emulators/), and [Ubuntu Weston package](https://archive.ubuntu.com/ubuntu/pool/universe/w/weston/) archives.
