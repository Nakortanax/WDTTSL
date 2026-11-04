#!/usr/bin/env bash
# Verify and compile an isolated CSQTT 2.5.0 staging server. NEVER deploy to VPS.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

for tool in git cargo rustc cc c++; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required build tool not found: $tool" >&2
    exit 2
  }
done

echo "=== Exact upstream source verification ==="
while IFS=$'\t' read -r expected relative; do
  [[ -n "$expected" ]] || continue
  [[ -f "$HERE/$relative" ]] || {
    echo "Missing upstream file: $relative" >&2
    exit 1
  }
  actual="$(git hash-object "$HERE/$relative")"
  if [[ "$expected" != "$actual" ]]; then
    echo "Upstream SHA mismatch: $relative ($actual instead of $expected)" >&2
    exit 1
  fi
done < "$HERE/UPSTREAM_BLOBS.tsv"
bash -n "$HERE/deploy.sh"

# Diagnostic build only: use GNU/glibc available in Debian 12 Forgejo job.
# Cargo's upstream .cargo/config.toml defaults to MUSL; explicit --target overrides it.
# GNU output is NOT a replacement for the static MUSL release assets.
target="x86_64-unknown-linux-gnu"
if [[ "${RUST_TARGET:-$target}" != "$target" ]]; then
  echo "This staging check is GNU-only; refusing an unexpected target" >&2
  exit 2
fi
echo "=== Diagnostic target: $target ==="
rustc --version
cargo --version
cc --version | head -n 1
c++ --version | head -n 1

cd "$HERE/rust-server"
echo "=== Run CSQTT 2.5.0 Rust tests ==="
cargo test --locked --target "$target"
echo "=== Build CSQTT 2.5.0 diagnostic GNU executable ==="
cargo build --locked --release --target "$target"

binary="target/$target/release/csqtt"
test -s "$binary"
revision="$("$binary" --protocol-revision)"
if [[ "$revision" != 'CSQTT-WIRE-3' ]]; then
  echo "Unexpected protocol revision: $revision" >&2
  exit 1
fi

printf '\nUpstream integrity, tests and diagnostic build passed; wire marker = %s\n' "$revision"
echo "CAUTION: GNU/glibc binary is lab-only. Compatibility with VPNSL Android/Windows not validated."
echo "Do not deploy to VPS or package this binary in Android/Windows."
