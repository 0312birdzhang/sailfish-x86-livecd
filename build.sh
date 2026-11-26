#!/usr/bin/env bash
set -euo pipefail

source_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export SFOS_WORK=${SFOS_WORK:-/home/bird/data/tmp/sfos-live}
export TMPDIR="$SFOS_WORK/build"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$SFOS_WORK"/{downloads,cache,build,logs,tools}
exec 9>"$SFOS_WORK/build.lock"
flock -n 9

for required_tool in python3 lxc-usernsexec unshare qemu-img 7z rsync mksquashfs gcc; do
    command -v "$required_tool" >/dev/null
done

python3 "$source_directory/scripts/download-inputs.py" | tee "$SFOS_WORK/logs/downloads.log"
bash "$source_directory/scripts/build-graphics.sh" "$source_directory" "$SFOS_WORK" \
    2>&1 | tee "$SFOS_WORK/logs/graphics-build.log"
if [[ ! -x "$SFOS_WORK/tools/usr/bin/fuse2fs" ]]; then
    (
        cd "$SFOS_WORK/downloads"
        apt-get download fuse2fs
        dpkg-deb -x fuse2fs_*.deb "$SFOS_WORK/tools"
    )
fi

bash "$source_directory/scripts/namespace.sh" \
    bash "$source_directory/scripts/build-rootfs.sh" "$source_directory" "$SFOS_WORK" \
    2>&1 | tee "$SFOS_WORK/logs/build.log"
