#!/usr/bin/env bash
# Verify and build isolated upstream CSQTT 2.5.0; never install/restart a server.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
command -v cargo >/dev/null || { echo "cargo is required (Rust 1.97.1)" >&2; exit 2; }
command -v rustc >/dev/null || { echo "rustc is required (Rust 1.97.1)" >&2; exit 2; }
command -v zig >/dev/null || { echo "zig is required for Linux MUSL C++ builds" >&2; exit 2; }

echo "=== Verify exact upstream Git blobs ==="
while IFS=$'\t' read -r expected relative; do
  [[ -n "$expected" ]] || continue
  [[ -f "$HERE/$relative" ]] || { echo "Missing $relative" >&2; exit 1; }
  actual="$(git hash-object "$HERE/$relative")"
  [[ "$expected" == "$actual" ]] || {
    echo "Mismatch: $relative expected $expected got $actual" >&2
    exit 1
  }
done < "$HERE/UPSTREAM_BLOBS.tsv"
bash -n "$HERE/deploy.sh"

echo "=== Linux MUSL toolchain ==="
rustc --version
cargo --version
zig version
target="x86_64-unknown-linux-musl"
zig_target="x86_64-linux-musl"
wrappers="$HERE/.staging-tools/zig-wrappers"
mkdir -p "$wrappers"

# Follow upstream build_linux.sh: use Zig both for C and C++ and as Rust's linker.
# musl-tools provides musl-gcc, but Debian does not ship x86_64-linux-musl-g++.
cat > "$wrappers/zigcc" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args=()
for arg in "$@"; do
  [[ "$arg" == --target=* ]] || args+=("$arg")
done
exec zig cc -target x86_64-linux-musl "${args[@]}"
SH
cat > "$wrappers/zigcxx" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args=()
for arg in "$@"; do
  [[ "$arg" == --target=* ]] || args+=("$arg")
done
exec zig c++ -target x86_64-linux-musl "${args[@]}"
SH
cat > "$wrappers/zigar" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exec zig ar "$@"
SH
chmod 0755 "$wrappers/zigcc" "$wrappers/zigcxx" "$wrappers/zigar"

export CC_x86_64_unknown_linux_musl="$wrappers/zigcc"
export CXX_x86_64_unknown_linux_musl="$wrappers/zigcxx"
export AR_x86_64_unknown_linux_musl="$wrappers/zigar"
export CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER="$wrappers/zigcc"

# Print compiler identity early, before expensive dependency compilation.
"$CXX_x86_64_unknown_linux_musl" --version | head -n 1
"$CC_x86_64_unknown_linux_musl" --version | head -n 1

cd "$HERE/rust-server"
echo "=== Cargo tests: $target ==="
cargo test --locked --target "$target"
echo "=== Cargo release build: $target ==="
cargo build --locked --release --target "$target"
binary="target/$target/release/csqtt"
test -s "$binary"
revision="$("$binary" --protocol-revision)"
[[ "$revision" == 'CSQTT-WIRE-3' ]] || {
  echo "Unexpected revision: $revision" >&2
  exit 1
}
printf '\nSource integrity and build OK; wire marker = %s\n' "$revision"
printf '%s\n' 'NOTE: Compatibility with VPNSL Android 1.0.10 / Windows 1.0.3 is NOT established. Do not deploy.'
