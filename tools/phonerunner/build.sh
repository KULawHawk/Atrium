#!/usr/bin/env bash
# Reproducible Windows build of PhoneRunner. Prints the sha256 of each program.
# Usage: ./build.sh <out-dir>
set -euo pipefail
out="${1:?usage: ./build.sh <out-dir>}"
cd "$(dirname "$0")"
mkdir -p "$out"
export CGO_ENABLED=0 GOOS=windows GOARCH=amd64 GOFLAGS=-mod=readonly
for cmd in phonerunner-service phonerunner-session phonerunner-copyoff phonerunner-check; do
  go build -trimpath -ldflags="-s -w -buildid=" -o "$out/$cmd.exe" "./cmd/$cmd"
done
( cd "$out" && sha256sum phonerunner-*.exe > SHA256SUMS.txt && cat SHA256SUMS.txt )
