#!/usr/bin/env bash
# Read-only for production: builds the isolated upstream server but never installs/restarts it.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
command -v cargo >/dev/null || { echo "cargo is required (Rust 1.97.1)" >&2; exit 2; }
command -v rustc >/dev/null || { echo "rustc is required (Rust 1.97.1)" >&2; exit 2; }
while IFS=$'\t' read -r expected relative; do
  [[ -n "$expected" ]] || continue
  [[ -f "$HERE/$relative" ]] || { echo "Missing $relative" >&2; exit 1; }
  actual="$(git hash-object "$HERE/$relative")"
  [[ "$expected" == "$actual" ]] || { echo "Mismatch: $relative expected $expected got $actual" >&2; exit 1; }
done < "$HERE/UPSTREAM_BLOBS.tsv"
bash -n "$HERE/deploy.sh"
cd "$HERE/rust-server"
# Upstream .cargo/config.toml defaults to the MUSL target. Be explicit so the
# tested binary and the archived artifact are the same executable.
target="x86_64-unknown-linux-musl"
cargo test --locked --target "$target"
cargo build --locked --release --target "$target"
binary="target/$target/release/csqtt"
test -s "$binary"
revision="$("$binary" --protocol-revision)"
[[ "$revision" == 'CSQTT-WIRE-3' ]] || { echo "Unexpected revision: $revision" >&2; exit 1; }
printf '\nSource integrity and build OK; wire marker = %s\n' "$revision"
printf '%s\n' 'NOTE: Compatibility with VPNSL Android 1.0.10 / Windows 1.0.3 is NOT established. Do not deploy.'
