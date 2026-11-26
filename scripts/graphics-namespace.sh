#!/usr/bin/env bash
set -euo pipefail
project=$1
work=$2
sdk="$work/build/graphics-sdk"
base="$work/build/graphics"
if [[ ! -f "$base/sdk-root.complete" ]]; then
    mkdir -p "$sdk"
    tar --numeric-owner --exclude='./dev/*' -xpf \
        "$work/downloads/ubuntu-base-24.04.5-base-amd64.tar.gz" -C "$sdk"
    touch "$base/sdk-root.complete"
fi
cp /etc/resolv.conf "$sdk/etc/resolv.conf"
sdk_fingerprint=$(sha256sum "$project/scripts/prepare-graphics-sdk.sh" | cut -d' ' -f1)
if [[ ! -f "$base/sdk.complete" ]] || [[ $(cat "$base/sdk.complete") != "$sdk_fingerprint" ]]; then
    cp "$project/scripts/prepare-graphics-sdk.sh" "$sdk/tmp/prepare-graphics-sdk.sh"
    unshare --mount bash "$project/scripts/in-namespace.sh" "$sdk" \
        /bin/bash /tmp/prepare-graphics-sdk.sh
    printf '%s\n' "$sdk_fingerprint" > "$base/sdk.complete"
fi
mkdir -p "$sdk/mnt/graphics" "$sdk/mnt/project"
mount --bind "$base" "$sdk/mnt/graphics"
mount --bind "$project" "$sdk/mnt/project"
mount -o remount,bind,ro "$sdk/mnt/project"
unshare --mount bash "$project/scripts/in-namespace.sh" "$sdk" \
    /usr/bin/python3 /mnt/project/scripts/build-mesa.py /mnt/project /mnt/graphics
unshare --mount bash "$project/scripts/in-namespace.sh" "$sdk" \
    /bin/bash /mnt/project/scripts/check-wayland-parent.sh
