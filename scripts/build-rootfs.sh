#!/usr/bin/env bash
set -euo pipefail

source_directory=$1
work_directory=$2
release_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$source_directory/config/release.json")
sdk_seed_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sdk_seed_version"])' "$source_directory/config/release.json")
ubuntu_root="$work_directory/build/ubuntu-root"
sailfish_root="$work_directory/build/sailfish-root-$release_version"
image_directory="$work_directory/build/iso"

if [[ ! -f "$work_directory/build/ubuntu-base.complete" ]]; then
    mkdir -p "$ubuntu_root"
    tar --numeric-owner --exclude='./dev/*' -xpf \
        "$work_directory/downloads/ubuntu-base-24.04.5-base-amd64.tar.gz" -C "$ubuntu_root"
    touch "$work_directory/build/ubuntu-base.complete"
fi

if [[ ! -f "$work_directory/build/sailfish-root-$release_version.complete" ]]; then
    mkdir -p "$work_directory/build/emulator/mounted" "$sailfish_root"
    7z x -y "-o$work_directory/build/emulator" \
        "$work_directory/downloads/Sailfish_OS-$sdk_seed_version-Sailfish_SDK_Emulator.7z"
    qemu-img convert -O raw "$work_directory/build/emulator/sailfishos.vdi" \
        "$work_directory/build/emulator/sailfishos.raw"
    dd if="$work_directory/build/emulator/sailfishos.raw" \
        of="$work_directory/build/emulator/root.ext4" \
        bs=4M skip=512 iflag=skip_bytes conv=sparse status=none
    "$work_directory/tools/usr/bin/fuse2fs" -o ro,fakeroot \
        "$work_directory/build/emulator/root.ext4" "$work_directory/build/emulator/mounted"
    rsync -aHAX --numeric-ids --exclude=/dev/ \
        "$work_directory/build/emulator/mounted/" "$sailfish_root/"
    fusermount -u "$work_directory/build/emulator/mounted"
    cp "$source_directory/scripts/upgrade-sailfish.sh" "$sailfish_root/tmp/upgrade-sailfish.sh"
    mkdir -p "$sailfish_root/tmp/sailfish-package-manager"
    cp "$work_directory/downloads/sailfish-package-manager/$release_version/"*.rpm \
        "$sailfish_root/tmp/sailfish-package-manager/"
    rm -f "$sailfish_root/etc/resolv.conf"
    cp /etc/resolv.conf "$sailfish_root/etc/resolv.conf"
    unshare --mount bash "$source_directory/scripts/in-namespace.sh" "$sailfish_root" \
        /bin/sh /tmp/upgrade-sailfish.sh "$release_version"
    rm -rf "$sailfish_root/tmp/sailfish-package-manager" "$sailfish_root/tmp/upgrade-sailfish.sh"
    printf '%s\n' "$release_version" > "$work_directory/build/sailfish-root-$release_version.complete"
fi

rsync -a "$source_directory/overlay/sailfish/" "$sailfish_root/"
mkdir -p "$sailfish_root/usr/lib/sailfish-live"
gcc -m32 -shared -fPIC -nostdlib -Wall -Wextra -Werror \
    "$source_directory/src/wayland-parent.c" \
    -o "$sailfish_root/usr/lib/sailfish-live/libwayland-parent.so"
rm -f "$ubuntu_root/etc/systemd/network/80-container-ve.network.d/live.conf"
# Let dpkg install its casper conffile before applying the LiveCD version.
rsync -a --exclude=/etc/casper.conf "$source_directory/overlay/ubuntu/" "$ubuntu_root/"
cp "$source_directory/overlay/ubuntu/etc/casper.conf" "$ubuntu_root/tmp/casper-live.conf"
rm -f "$ubuntu_root/etc/resolv.conf"
cp /etc/resolv.conf "$ubuntu_root/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$ubuntu_root/usr/sbin/policy-rc.d"
chmod 0755 "$ubuntu_root/usr/sbin/policy-rc.d"
cp "$source_directory/scripts/configure-ubuntu.sh" "$ubuntu_root/tmp/configure-live.sh"
unshare --mount bash "$source_directory/scripts/in-namespace.sh" "$ubuntu_root" \
    /bin/bash /tmp/configure-live.sh
rm -f "$ubuntu_root/tmp/configure-live.sh" "$ubuntu_root/tmp/casper-live.conf"
mkdir -p "$ubuntu_root/opt/weston9"
dpkg-deb -x "$work_directory/downloads/weston_9.0.0-4ubuntu1_amd64.deb" "$ubuntu_root/opt/weston9"
dpkg-deb -x "$work_directory/downloads/libweston-9-0_9.0.0-4ubuntu1_amd64.deb" "$ubuntu_root/opt/weston9"
ln -sfn /opt/weston9/usr/lib/x86_64-linux-gnu/libweston-9 \
    "$ubuntu_root/usr/lib/x86_64-linux-gnu/libweston-9"

rsync -a "$work_directory/build/graphics/amd64/payload/" "$ubuntu_root/"
rsync -a "$work_directory/build/graphics/i386/payload/" "$sailfish_root/"
cp "$source_directory/scripts/configure-sailfish.sh" "$sailfish_root/tmp/configure-live.sh"
rm -f "$sailfish_root/etc/resolv.conf"
cp /etc/resolv.conf "$sailfish_root/etc/resolv.conf"
host_audio_gid=$(awk -F: '$1 == "audio" {print $3}' "$ubuntu_root/etc/group")
host_video_gid=$(awk -F: '$1 == "video" {print $3}' "$ubuntu_root/etc/group")
host_render_gid=$(awk -F: '$1 == "render" {print $3}' "$ubuntu_root/etc/group")
unshare --mount bash "$source_directory/scripts/in-namespace.sh" "$sailfish_root" \
    /bin/bash /tmp/configure-live.sh "$release_version" "$host_audio_gid" "$host_video_gid" "$host_render_gid"
rm -f "$sailfish_root/tmp/configure-live.sh"

mkdir -p "$ubuntu_root/opt/sailfish/rootfs"
rsync -aHAX --delete --numeric-ids "$sailfish_root/" "$ubuntu_root/opt/sailfish/rootfs/"
mkdir -p "$image_directory"/{casper,boot/grub} "$source_directory/dist"
cp -L "$ubuntu_root/boot/vmlinuz" "$image_directory/casper/vmlinuz"
cp -L "$ubuntu_root/boot/initrd.img" "$image_directory/casper/initrd"
cp "$source_directory/boot/grub.cfg" "$image_directory/boot/grub/grub.cfg"

mksquashfs "$ubuntu_root" "$image_directory/casper/filesystem.squashfs.partial" \
    -noappend -comp zstd -Xcompression-level 15 -processors 4 -wildcards \
    -e var/cache/apt/archives var/lib/apt/lists tmp/* var/log/* \
    opt/sailfish/rootfs/home/.zypp-cache opt/sailfish/rootfs/tmp/* \
    opt/sailfish/rootfs/var/log/*
mv "$image_directory/casper/filesystem.squashfs.partial" "$image_directory/casper/filesystem.squashfs"
du -sx --block-size=1 --exclude=var/cache/apt/archives --exclude=var/lib/apt/lists \
    "$ubuntu_root" | cut -f1 > "$image_directory/casper/filesystem.size"

mkdir -p "$ubuntu_root/mnt/iso" "$ubuntu_root/mnt/output"
mount --bind "$image_directory" "$ubuntu_root/mnt/iso"
mount --bind "$source_directory/dist" "$ubuntu_root/mnt/output"
unshare --mount bash "$source_directory/scripts/in-namespace.sh" "$ubuntu_root" \
    /usr/bin/grub-mkrescue -o "/mnt/output/sailfish-live-$release_version-amd64.iso.partial" \
    /mnt/iso -- -volid SFOS_LIVE
umount "$ubuntu_root/mnt/iso" "$ubuntu_root/mnt/output"

cd "$source_directory/dist"
mv "sailfish-live-$release_version-amd64.iso.partial" "sailfish-live-$release_version-amd64.iso"
cp "$ubuntu_root/etc/ubuntu-live-packages.tsv" ubuntu-packages.tsv
cp "$sailfish_root/etc/sailfish-live-packages.tsv" sailfish-packages.tsv
cp "$work_directory/downloads/inputs.json" inputs.json
cp "$work_directory/build/graphics/amd64/complete.json" graphics-amd64.json
cp "$work_directory/build/graphics/i386/complete.json" graphics-i386.json
cp "$work_directory/build/graphics/sdk-packages.tsv" graphics-sdk-packages.tsv
sha256sum "sailfish-live-$release_version-amd64.iso" > SHA256SUMS.partial
mv SHA256SUMS.partial SHA256SUMS
