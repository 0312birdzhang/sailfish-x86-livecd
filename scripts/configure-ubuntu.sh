#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

dpkg --configure -a
apt-get update
apt-get install -y --no-install-recommends \
    linux-image-generic linux-firmware casper systemd-sysv systemd-container systemd-resolved \
    dbus xserver-xorg-core xserver-xorg-input-libinput \
    xserver-xorg-video-fbdev xserver-xorg-video-vesa \
    xinit xauth x11-xserver-utils xterm mesa-utils libgl1-mesa-dri \
    network-manager nftables pulseaudio alsa-utils sudo \
    squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin \
    mtools dosfstools curl ca-certificates weston zstd

systemctl enable sailfish-live.service NetworkManager.service systemd-networkd.service \
    systemd-resolved.service sailfish-dns.path sailfish-ssh.socket
systemctl set-default graphical.target
systemctl mask systemd-networkd-wait-online.service NetworkManager-wait-online.service \
    casper-md5check.service

mkdir -p /etc/systemd/system/serial-getty@ttyS0.service.d
cat > /etc/systemd/system/serial-getty@ttyS0.service.d/live.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin live --noclear --keep-baud 115200,57600,38400,9600 - $TERM
EOF

chmod 0600 /etc/netplan/01-live.yaml
chmod 0755 /usr/local/bin/sailfish-session
chmod 0755 /usr/local/bin/sailfish-ssh-proxy
chmod 0755 /usr/share/initramfs-tools/scripts/casper-bottom/90-sailfish-persistence
printf 'sailfish-live\n' > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 sailfish-live\n::1 localhost ip6-localhost\n' > /etc/hosts
printf 'Sailfish OS Live on Ubuntu Base\nLocal console user: live\nSailfish user: defaultuser, password: live\n\n' > /etc/issue

dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > /etc/ubuntu-live-packages.tsv
update-initramfs -u -k all
rm -f /usr/sbin/policy-rc.d /etc/machine-id /var/lib/dbus/machine-id
touch /etc/machine-id
rm -f /etc/resolv.conf
ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
rm -f /var/lib/systemd/random-seed
