#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel):
    return (root / rel).read_text(encoding="utf-8")


def write(rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(rel, old, new):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"anchor not found in {rel}: {old[:120]!r}")
    write(rel, text.replace(old, new, 1))


# Version metadata and visible header.
replace_once("app/build.gradle.kts", "versionCode = 1005", "versionCode = 1006")
replace_once("app/build.gradle.kts", 'versionName = "1.0.5"', 'versionName = "1.0.6"')
replace_once(
    "app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt",
    "1.0.5 by Sazhaev-IA",
    "1.0.6 by Sazhaev-IA",
)

# New Android flow-policy service and launcher artwork.
shutil.copy2(
    root / "wdttsl-custom/CombinedFlowPolicyServer.kt",
    root / "app/src/main/java/com/csqtt/client/routing/CombinedFlowPolicyServer.kt",
)
shutil.copy2(
    root / "wdttsl-custom/ic_vpnsl_launcher.xml",
    root / "app/src/main/res/drawable/ic_vpnsl_launcher.xml",
)
manifest = read("app/src/main/AndroidManifest.xml")
manifest = manifest.replace('android:icon="@mipmap/ic_launcher"', 'android:icon="@drawable/ic_vpnsl_launcher"')
manifest = manifest.replace('android:roundIcon="@mipmap/ic_launcher_round"', 'android:roundIcon="@drawable/ic_vpnsl_launcher"')
manifest = manifest.replace('android:icon="@drawable/ic_c_logo"', 'android:icon="@drawable/ic_vpnsl_launcher"')
write("app/src/main/AndroidManifest.xml", manifest)

# Native dependencies and modules for the mobile direct path.
cargo = read("rust-client/Cargo.toml")
if 'futures = "0.3.31"' not in cargo:
    cargo = cargo.replace('crossbeam-queue = "0.3.13"\n', 'crossbeam-queue = "0.3.13"\nfutures = "0.3.31"\nnetstack-smoltcp = "0.2.4"\n', 1)
write("rust-client/Cargo.toml", cargo)

main = read("rust-client/main.rs")
if "mod direct_path;" not in main:
    main = main.replace("mod dispatcher;\n", "mod dispatcher;\nmod direct_path;\nmod flow_policy;\n", 1)
write("rust-client/main.rs", main)

# Signal combined mode in the one-byte payload already accompanying the TUN FD.
tun = read("rust-client/tun.rs")
tun = tun.replace(
    "use std::fs::File;\nuse tokio_util::sync::CancellationToken;",
    "use std::{\n    fs::File,\n    sync::atomic::{AtomicBool, Ordering},\n};\nuse tokio_util::sync::CancellationToken;\n\nstatic COMBINED_ROUTING: AtomicBool = AtomicBool::new(false);\n\npub fn combined_routing() -> bool {\n    COMBINED_ROUTING.load(Ordering::Acquire)\n}",
    1,
)
needle = """                                {\n                                    let file = unsafe { File::from_raw_fd(descriptor) };\n                                    configure_nonblocking(file.as_raw_fd())?;"""
replacement = """                                {\n                                    COMBINED_ROUTING.store(data[0] == 2, Ordering::Release);\n                                    let file = unsafe { File::from_raw_fd(descriptor) };\n                                    configure_nonblocking(file.as_raw_fd())?;"""
if needle not in tun:
    raise SystemExit("TUN receive anchor not found")
tun = tun.replace(needle, replacement, 1)
write("rust-client/tun.rs", tun)

# Split packets before the existing WDTTSL framing/dispatcher. MOBILE packets
# enter netstack-smoltcp and are emitted through ordinary app-owned sockets;
# the Android VPN excludes this app UID, so these sockets use the physical link.
dispatcher = read("rust-client/dispatcher.rs")n
