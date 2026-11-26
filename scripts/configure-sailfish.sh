#!/usr/bin/env bash
set -euo pipefail

release_version=$1
shift
trap '
    rm -f /etc/resolv.conf
    ln -s /run/host-resolve/resolv.conf /etc/resolv.conf
' EXIT

if ! getent passwd 100000 >/dev/null; then
    groupadd -g 100000 defaultuser
    useradd -m -u 100000 -g defaultuser \
        -G users,video,audio,input,render,privileged defaultuser
    echo 'defaultuser:live' | chpasswd
fi

/usr/lib/startup/create-home 100000
/usr/lib/startup/hw-groups 100000

if rpm -qa --qf '%{NAME}\n' | grep -Eqi 'droid|hybris'; then
    echo 'The rootfs contains an excluded Android adaptation package.' >&2
    exit 1
fi
ssu ur
. /etc/os-release
test "$VERSION_ID" = "$release_version"

dconf update

# Bind-mounted devices retain Ubuntu's numeric ownership. Firejail retains
# hardware groups by name, so align those names rather than adding unrelated
# supplementary groups (Ubuntu's render GID can be Sailfish's MDM GID).
move_group() {
    local group_name=$1 new_gid=$2 old_gid primary_users
    old_gid=$(getent group "$group_name" | cut -d: -f3)
    [ "$old_gid" = "$new_gid" ] && return 0
    primary_users=$(getent passwd | awk -F: -v gid="$old_gid" '$4 == gid {print $1}')
    groupmod -g "$new_gid" "$group_name"
    for primary_user in $primary_users; do usermod -g "$new_gid" "$primary_user"; done
    find / -xdev -group "$old_gid" -exec /bin/bash -c '
        new_gid=$1; shift
        for path in "$@"; do
            file_mode=$(stat -c %a "$path")
            chgrp -h "$new_gid" "$path"
            if [ ! -L "$path" ]; then chmod "$file_mode" "$path"; fi
        done
    ' bash "$new_gid" {} +
}
[ "$#" -eq 3 ]
for group_name in audio video render; do
    host_gid=$1
    shift
    case "$host_gid" in ''|*[!0-9]*) exit 1 ;; esac
    collision=$(getent group "$host_gid" | cut -d: -f1 || true)
    if [ -n "$collision" ] && [ "$collision" != "$group_name" ]; then
        for spare_gid in $(seq 60000 65534); do
            if ! getent group "$spare_gid" >/dev/null; then break; fi
        done
        move_group "$collision" "$spare_gid"
    fi
    move_group "$group_name" "$host_gid"
done
usermod -a -G audio,video,render,sailfish-system defaultuser
/sbin/ldconfig
chmod 0755 /usr/local/bin/sailfish-lipstick
chmod 0755 /usr/local/bin/sailfish-network
sed -i \
    -e '/^DefaultAutoConnectTechnologies=/d' \
    -e '/^\[General\]/a DefaultAutoConnectTechnologies=ethernet' \
    /etc/connman/main.conf
rm -f /etc/resolv.conf
ln -s /run/host-resolve/resolv.conf /etc/resolv.conf
systemctl set-default graphical.target
systemctl unmask sshd.socket sshd.service
systemctl disable sshd.socket sshd.service
systemctl mask run-media-defaultuser-sdk.mount etc-mersdk-share.mount \
    etc-ssh-authorized_keys.mount resize-rootfs.service vboxservice.service \
    sdk-emulan.service sdk-refresh-repos.service quota_nld.service
rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' | sort > /etc/sailfish-live-packages.tsv
rm -f /etc/machine-id /var/lib/dbus/machine-id
touch /etc/machine-id
