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

# Native dependencies/modules for the physical-mobile direct path.
cargo = read("rust-client/Cargo.toml")
if 'futures = "0.3.31"' not in cargo:
    cargo = cargo.replace(
        'crossbeam-queue = "0.3.13"\n',
        'crossbeam-queue = "0.3.13"\nfutures = "0.3.31"\nnetstack-smoltcp = "0.2.4"\n',
        1,
    )
write("rust-client/Cargo.toml", cargo)

main = read("rust-client/main.rs")
if "mod direct_path;" not in main:
    main = main.replace("mod dispatcher;\n", "mod dispatcher;\nmod direct_path;\nmod flow_policy;\n", 1)
write("rust-client/main.rs", main)

# Reuse the one-byte payload already sent beside the TUN fd: 1=classic, 2=combined.
tun = read("rust-client/tun.rs")
old_tun_import = "use std::fs::File;\nuse tokio_util::sync::CancellationToken;"
new_tun_import = """use std::{
    fs::File,
    sync::atomic::{AtomicBool, Ordering},
};
use tokio_util::sync::CancellationToken;

static COMBINED_ROUTING: AtomicBool = AtomicBool::new(false);

pub fn combined_routing() -> bool {
    COMBINED_ROUTING.load(Ordering::Acquire)
}"""
if old_tun_import not in tun:
    raise SystemExit("TUN import anchor not found")
tun = tun.replace(old_tun_import, new_tun_import, 1)
needle = """                                {
                                    let file = unsafe { File::from_raw_fd(descriptor) };
                                    configure_nonblocking(file.as_raw_fd())?;"""
replacement = """                                {
                                    COMBINED_ROUTING.store(data[0] == 2, Ordering::Release);
                                    let file = unsafe { File::from_raw_fd(descriptor) };
                                    configure_nonblocking(file.as_raw_fd())?;"""
if needle not in tun:
    raise SystemExit("TUN receive anchor not found")
tun = tun.replace(needle, replacement, 1)
write("rust-client/tun.rs", tun)

# Split MOBILE packets before the unchanged WDTTSL framing/worker dispatcher.
dispatcher = read("rust-client/dispatcher.rs")
setup_anchor = """        use std::os::fd::AsRawFd;

        let mut scheduler = FastPathScheduler::new();"""
setup_new = """        use std::os::fd::AsRawFd;

        let combined_routing = tun::combined_routing();
        let direct_path = if combined_routing {
            match crate::direct_path::DirectPath::start(
                self.clone(),
                pool.clone(),
                self.cancel.clone(),
            ) {
                Ok(path) => Some(path),
                Err(error) => {
                    crate::log_error!("[ROUTING] Не удалось запустить MOBILE direct path: {error:#}");
                    return;
                }
            }
        } else {
            None
        };
        let mut flow_policy = combined_routing.then(crate::flow_policy::FlowPolicyClient::new);
        if combined_routing {
            crate::log_error!("[ROUTING] Combined OR policy активна: APP || ROUTE -> WDTTSL, остальное -> MOBILE");
        }

        let mut scheduler = FastPathScheduler::new();"""
if setup_anchor not in dispatcher:
    raise SystemExit("dispatcher setup anchor not found")
dispatcher = dispatcher.replace(setup_anchor, setup_new, 1)
packet_anchor = """                        if packet.set_read_len(length).is_err() {
                            return;
                        }
                        if !frame_outbound_packet(&mut flow_sequences, &mut packet) {
                            continue;
                        }"""
packet_new = """                        if packet.set_read_len(length).is_err() {
                            return;
                        }
                        if combined_routing
                            && flow_policy
                                .as_mut()
                                .expect("combined flow policy")
                                .decide(packet.as_slice())
                                == crate::flow_policy::FlowDecision::Mobile
                        {
                            if let Some(path) = direct_path.as_ref()
                                && let Err(error) = path.send(packet.as_slice()).await
                            {
                                crate::log_error!("[ROUTING] MOBILE direct path stopped: {error:#}");
                                return;
                            }
                            continue;
                        }
                        if !frame_outbound_packet(&mut flow_sequences, &mut packet) {
                            continue;
                        }"""
if packet_anchor not in dispatcher:
    raise SystemExit("dispatcher packet anchor not found")
dispatcher = dispatcher.replace(packet_anchor, packet_new, 1)
write("rust-client/dispatcher.rs", dispatcher)

# Android VPN policy. Classic app-only and route-only modes remain unchanged;
# only when both sources contain active WDTTSL rules do we capture 0/0 and
# classify each new TCP/UDP flow by destination OR owning UID (Android 10+).
vpn_path = "app/src/main/java/com/csqtt/client/TunVpnService.kt"
vpn = read(vpn_path)
vpn = vpn.replace("import android.os.ParcelFileDescriptor\n", "import android.os.Build\nimport android.os.ParcelFileDescriptor\n", 1)
vpn = vpn.replace(
    "import com.csqtt.client.routing.RouteListStore\nimport com.csqtt.client.routing.RoutePolicyApplier\nimport com.csqtt.client.routing.RoutingSourceMode\n",
    "import com.csqtt.client.routing.CombinedFlowPolicyServer\nimport com.csqtt.client.routing.RouteListStore\nimport com.csqtt.client.routing.RoutePolicyApplier\nimport com.csqtt.client.routing.RoutePolicyCompiler\n",
    1,
)
field_anchor = """    private var activeDns: String? = null
    private var recoveryAttempts = 0"""
field_new = """    private var activeDns: String? = null
    private var flowPolicyServer: CombinedFlowPolicyServer? = null
    @Volatile private var combinedRoutingActive = false
    private var recoveryAttempts = 0"""
if field_anchor not in vpn:
    raise SystemExit("VPN field anchor not found")
vpn = vpn.replace(field_anchor, field_new, 1)

reuse_anchor = """            if (existing != null) {
                sendTunFd(existing)
                return
            }

            if (VpnService.prepare(this) != null) {"""
reuse_new = """            if (existing != null) {
                sendTunFd(existing)
                return
            }

            flowPolicyServer?.stop()
            flowPolicyServer = null
            combinedRoutingActive = false

            if (VpnService.prepare(this) != null) {"""
if reuse_anchor not in vpn:
    raise SystemExit("VPN reuse anchor not found")
vpn = vpn.replace(reuse_anchor, reuse_new, 1)

start = vpn.index("            val routeListStore = RouteListStore(applicationContext)")
end = vpn.index("            val pfd = builder.establish()", start)
new_policy = '''            val routeListStore = RouteListStore(applicationContext)
            val compiledRoutes = RoutePolicyCompiler.compile(routeListStore.loadProfiles())
            val transportPackages = setOf(
                applicationContext.packageName,
                CsqttConstants.General.PACKAGE_VK,
                CsqttConstants.General.PACKAGE_VK_CALLS
            )
            val installedIncluded = userSelected
                .filter { pkg -> pkg !in transportPackages && isPackageInstalled(pkg) }
                .toSet()
            val hasApplications = installedIncluded.isNotEmpty()
            val hasRoutes = compiledRoutes.isNotEmpty()
            val useCombined = hasApplications && hasRoutes
            var combinedSelectedUids: Set<Int> = emptySet()

            if (!hasApplications && !hasRoutes) {
                failVpn("Список пуст: выберите приложение или включите хотя бы один маршрут WDTTSL")
                return
            }
            if (useCombined && Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                failVpn("Совместный режим «Приложения + Маршруты» требует Android 10 или новее")
                return
            }

            val builder = Builder()
                .setSession("VPNSL")
                .setMtu(CsqttConstants.Vpn.DEFAULT_MTU)
                .addAddress(clientIp, 32)

            fun addConfiguredDns(): Boolean {
                var validDnsServers = 0
                dns.split(",").map { it.trim() }.filter { it.isNotEmpty() }.forEach { dnsServer ->
                    try {
                        builder.addDnsServer(dnsServer)
                        validDnsServers++
                    } catch (e: Exception) {
                        Log.w(TAG, "Invalid DNS server: $dnsServer")
                    }
                }
                return validDnsServers > 0
            }

            when {
                useCombined -> {
                    builder.addRoute("0.0.0.0", 0)
                    if (!addConfiguredDns()) {
                        failVpn("сервер передал некорректный DNS: $dns")
                        return
                    }
                    transportPackages
                        .filter { isPackageInstalled(it) }
                        .forEach { pkg ->
                            try { builder.addDisallowedApplication(pkg) } catch (_: Exception) {}
                        }
                    combinedSelectedUids = installedIncluded.mapNotNull { pkg ->
                        runCatching { packageManager.getApplicationInfo(pkg, 0).uid }.getOrNull()
                    }.toSet()
                    if (combinedSelectedUids.isEmpty()) {
                        failVpn("Не удалось определить UID выбранных приложений")
                        return
                    }
                    Log.i(TAG, "Combined routing: apps=${installedIncluded.size}, routes=${compiledRoutes.size}")
                }
                hasApplications -> {
                    builder.addRoute("0.0.0.0", 0)
                    if (!addConfiguredDns()) {
                        failVpn("сервер передал некорректный DNS: $dns")
                        return
                    }
                    var includedCount = 0
                    installedIncluded.forEach { pkg ->
                        try {
                            builder.addAllowedApplication(pkg)
                            includedCount++
                        } catch (error: Exception) {
                            Log.w(TAG, "Unable to include $pkg in VPN", error)
                        }
                    }
                    if (includedCount == 0) {
                        failVpn("Android не разрешил добавить выбранные приложения в VPN")
                        return
                    }
                }
                else -> {
                    val routeCount = RoutePolicyApplier.apply(builder, routeListStore.loadProfiles())
                    Log.i(TAG, "WDTTSL route-list mode: $routeCount VPN routes")
                    transportPackages
                        .filter { isPackageInstalled(it) }
                        .forEach { pkg ->
                            try { builder.addDisallowedApplication(pkg) } catch (_: Exception) {}
                        }
                }
            }
'''
vpn = vpn[:start] + new_policy + vpn[end:]

accepted_anchor = """            if (!accepted) {
                pfd.close()
                return
            }
            sendJob?.cancel()"""
accepted_new = """            if (!accepted) {
                pfd.close()
                return
            }

            if (useCombined) {
                try {
                    flowPolicyServer = CombinedFlowPolicyServer(
                        service = this,
                        selectedUids = combinedSelectedUids,
                        wdttslRoutes = compiledRoutes,
                    ).also { it.start() }
                    combinedRoutingActive = true
                } catch (error: Exception) {
                    Log.e(TAG, "Failed to start combined flow policy", error)
                    failVpn(error.message ?: "ошибка combined flow policy")
                    return
                }
            }
            sendJob?.cancel()"""
if accepted_anchor not in vpn:
    raise SystemExit("VPN accepted anchor not found")
vpn = vpn.replace(accepted_anchor, accepted_new, 1)

send_anchor = """                    socket.setFileDescriptorsForSend(arrayOf(pfd.fileDescriptor))
                    socket.outputStream.write(1)"""
send_new = """                    socket.setFileDescriptorsForSend(arrayOf(pfd.fileDescriptor))
                    socket.outputStream.write(if (combinedRoutingActive) 2 else 1)"""
if send_anchor not in vpn:
    raise SystemExit("VPN TUN signal anchor not found")
vpn = vpn.replace(send_anchor, send_new, 1)

stop_anchor = """    private fun stopVpn() {
        sendJob?.cancel()
        sendJob = null
        synchronized(interfaceLock) {"""
stop_new = """    private fun stopVpn() {
        sendJob?.cancel()
        sendJob = null
        combinedRoutingActive = false
        flowPolicyServer?.stop()
        flowPolicyServer = null
        synchronized(interfaceLock) {"""
if stop_anchor not in vpn:
    raise SystemExit("VPN stop anchor not found")
vpn = vpn.replace(stop_anchor, stop_new, 1)
write(vpn_path, vpn)

print("VPNSL 1.0.6 combined routing patch applied")
