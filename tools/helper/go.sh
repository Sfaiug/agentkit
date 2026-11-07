#!/bin/sh
# go.sh FROM DIR INTO: the suite helper's Go (tools/helper/Containerfile), the release DIR/go.mod's
# toolchain line names for this machine, fetched from FROM and unpacked into INTO only when its
# sha256 is the one DIR/toolchain.sha256 lists for that file name. That Go judges and builds every
# change the helper tests, so a download that is not the release's own, tampered or cut short,
# never becomes the judge.
set -eu
file=$(sed -n 's/^toolchain //p' "$2/go.mod").linux-$(dpkg --print-architecture).tar.gz
sum=$(awk -v file="$file" '$2 == file { print $1 }' "$2/toolchain.sha256")
refuse() { echo "go.sh: $file is not unpacked: $*" >&2; exit 1; }
# Listed first, so a release nobody listed is never fetched.
[ -n "$sum" ] || refuse "$2/toolchain.sha256 lists no sha256 for it"
archive=$(mktemp)
trap 'rm -f "$archive"' EXIT
curl -fsSLo "$archive" "$1/$file" || refuse "it did not download from $1"
printf '%s  %s\n' "$sum" "$archive" | sha256sum -c --status ||
  refuse "its sha256 is not the one $2/toolchain.sha256 lists"
tar -xzf "$archive" -C "$3"
