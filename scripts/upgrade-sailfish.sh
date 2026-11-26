#!/bin/sh
set -eu
release=$1
. /etc/os-release
if [ "$VERSION_ID" = "$release" ]; then exit 0; fi
rpm -Uvh --replacepkgs /tmp/sailfish-package-manager/*.rpm
ssu re "$release"
ssu ur

# The SSU plugin asks D-Bus for credentials for adaptation0. The emulator
# packages are also published on the release server without authentication.
# Use that URL during the chroot upgrade and keep the image's SSU repos intact.
build_repos=$(mktemp -d)
trap 'rm -r -- "$build_repos"' EXIT
cp /etc/zypp/repos.d/*.repo "$build_repos/"
adaptation_repo="$build_repos/ssu_adaptation0_release.repo"
adaptation_url="https://releases.jolla.com/releases/$release/jolla-hw/adaptation-jolla-x86-emul/i486/"
sed -i "s|^baseurl=plugin:ssu?repo=adaptation0\$|baseurl=$adaptation_url|" "$adaptation_repo"
grep -Fxq "baseurl=$adaptation_url" "$adaptation_repo"

build_zypper() {
    zypper --non-interactive --reposd-dir "$build_repos" "$@"
}

build_zypper refresh
history=/var/log/zypp/history
history_lines=0
if [ -f "$history" ]; then
    history_lines=$(wc -l < "$history")
fi
if build_zypper dup --no-recommends --allow-vendor-change; then
    :
else
    status=$?
    # 107 means RPM installed the packages, but a scriptlet failed. Check
    # only this transaction and stop for any failure we don't recognize.
    [ "$status" -eq 107 ] || exit "$status"
    failures=$(tail -n "+$((history_lines + 1))" "$history" |
        sed -n '/scriptlet failed, exit status/p')
    [ -n "$failures" ] || exit "$status"
    while IFS= read -r failure; do
        case "$failure" in
            # configure-sailfish.sh rebuilds the library cache with ldconfig.
            '# warning: %postun(qt5-qtdeclarative-qtquickparticles-'*') scriptlet failed, exit status 1') ;;
            # The LiveCD boots Ubuntu's kernel and GRUB, not these SDK components.
            '# warning: %post(kernel-adaptation-pc-'*') scriptlet failed, exit status 2') ;;
            '# warning: %post(syslinux-extlinux-'*') scriptlet failed, exit status 64') ;;
            *) printf 'Unexpected RPM scriptlet failure: %s\n' "$failure" >&2; exit "$status" ;;
        esac
    done <<EOF
$failures
EOF
    printf '%s\n' 'Continuing after known SDK scriptlet failures.'
fi
# Replace the BusyBox bash links and install GNU Bash in the same transaction.
# Selecting both changes lets the solver proceed without an interactive choice.
if rpm -q busybox-symlinks-bash >/dev/null; then
    set -- -busybox-symlinks-bash
else
    set --
fi
build_zypper install --force --no-recommends -- gnu-bash "$@"
if [ -x /usr/bin/bash ]; then ln -sfn ../usr/bin/bash /bin/bash; fi
/bin/bash -c 'test -n "$BASH_VERSION"'
. /etc/os-release
test "$VERSION_ID" = "$release"
