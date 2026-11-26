#!/usr/bin/env bash
set -euo pipefail
directory=/mnt/graphics/wayland-parent-test
mkdir -p "$directory/runtime"
chmod 0700 "$directory/runtime"
gcc -m32 -shared -fPIC -nostdlib -Wall -Wextra -Werror \
    /mnt/project/src/wayland-parent.c -o "$directory/libwayland-parent.so"
gcc -m32 -Wall -Wextra -Werror /mnt/project/src/wayland-parent-test.c \
    -lwayland-server -ldl -o "$directory/test"
XDG_RUNTIME_DIR="$directory/runtime" SFOS_PARENT_WAYLAND_DISPLAY=parent \
    WAYLAND_DISPLAY=missing LD_PRELOAD="$directory/libwayland-parent.so" "$directory/test"
