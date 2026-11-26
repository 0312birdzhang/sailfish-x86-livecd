#!/bin/sh
set -eu
release=$1
. /etc/os-release
if [ "$VERSION_ID" = "$release" ]; then exit 0; fi
rpm -Uvh --replacepkgs /tmp/sailfish-package-manager/*.rpm
ssu re "$release"
ssu ur
zypper --non-interactive refresh
zypper --non-interactive dup --no-recommends --allow-vendor-change
# The old PC adaptation may leave /bin/bash pointing at BusyBox after the
# upgrade. Restore the packaged GNU shell required by 5.2 system scripts.
zypper --non-interactive install --force --no-recommends gnu-bash
if [ -x /usr/bin/bash ]; then ln -sfn ../usr/bin/bash /bin/bash; fi
. /etc/os-release
test "$VERSION_ID" = "$release"
