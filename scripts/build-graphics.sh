#!/usr/bin/env bash
set -euo pipefail
project=$1
work=$2
mkdir -p "$work/build/graphics"
exec 8>"$work/graphics.lock"
flock 8
exec bash "$project/scripts/namespace.sh" \
    bash "$project/scripts/graphics-namespace.sh" "$project" "$work"
