#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
dpkg --add-architecture i386
apt-get update
packages=(
    build-essential gcc-multilib g++-multilib pkg-config python3-venv
    python3-pip ca-certificates bison flex patchelf llvm-19-dev libllvm19:i386
    libclc-19-dev libclang-19-dev libclang-cpp19-dev libllvmspirvlib-19-dev spirv-tools
)
development_packages=(
    libdrm-dev libwayland-dev libexpat1-dev libelf-dev libzstd-dev
    libwayland-egl-backend-dev libx11-dev libx11-xcb-dev libxext-dev
    libxfixes-dev libxxf86vm-dev libxrandr-dev libxshmfence-dev libxcb-glx0-dev
    libxcb-dri2-0-dev libxcb-dri3-dev libxcb-present-dev libxcb-randr0-dev
    libxcb-shm0-dev libxcb-xfixes0-dev libxcb-sync-dev libglvnd-dev
)
for package in "${development_packages[@]}"; do
    packages+=("$package:amd64" "$package:i386")
done
apt-get install -y --no-install-recommends "${packages[@]}"
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > /etc/graphics-sdk-packages.tsv
