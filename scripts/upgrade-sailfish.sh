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
build_zypper dup --no-recommends --allow-vendor-change
# The old PC adaptation may leave /bin/bash pointing at BusyBox after the
# upgrade. Restore the packaged GNU shell required by 5.2 system scripts.
build_zypper install --force --no-recommends gnu-bash
if [ -x /usr/bin/bash ]; then ln -sfn ../usr/bin/bash /bin/bash; fi
. /etc/os-release
test "$VERSION_ID" = "$release"
