#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CUSTOM = ROOT / "wdttsl-custom"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel, text):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_required(text, old, new, label):
    if old not in text:
        raise SystemExit(f"VPNSL 1.0.6 anchor missing: {label}")
    return text.replace(old, new, 1)


# 1.0.6 is intentionally applied after the exact 1.0.5 overlay.
# The editor no longer chooses APPLICATIONS OR ROUTE_LISTS. Both settings are
# active: selected applications define the VPN scope; destination profiles
# refine it. If no applications are selected, destination profiles work
# globally just as 1.0.5 route-list mode did.
exceptions_src = CUSTOM / "ExceptionsTabV106.kt"
exceptions_dst = ROOT / "app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"
if not exceptions_src.is_file():
    raise SystemExit("missing ExceptionsTabV106.kt")
shutil.copyfile(exceptions_src, exceptions_dst)

# Allow the same longest-prefix compiler to start either MOBILE (global route
# lists) or WDTTSL (selected-app full tunnel with MOBILE address exceptions).
compiler_rel = "app/src/main/java/com/csqtt/client/routing/RoutePolicyCompiler.kt"
compiler = read(compiler_rel)
compiler = replace_required(
    compiler,
    "fun compile(profiles: List<RouteListProfile>): List<Ipv4Cidr> {",
    "fun compile(\n        profiles: List<RouteListProfile>,\n        defaultTarget: RouteTarget = RouteTarget.MOBILE,\n    ): List<Ipv4Cidr> {",
    "RoutePolicyCompiler signature",
)
compiler = replace_required(
    compiler,
    "inheritedTarget = RouteTarget.MOBILE,",
    "inheritedTarget = defaultTarget,",
    "RoutePolicyCompiler default target",
)
write(compiler_rel, compiler)

applier_rel = "app/src/main/java/com/csqtt/client/routing/RoutePolicyApplier.kt"
applier = read(applier_rel)
applier = replace_required(
    applier,
    "fun apply(builder: VpnService.Builder, profiles: List<RouteListProfile>): Int {\n        val compiled = RoutePolicyCompiler.compile(profiles)",
    "fun apply(\n        builder: VpnService.Builder,\n        profiles: List<RouteListProfile>,\n        defaultTarget: RouteTarget = RouteTarget.MOBILE,\n    ): Int {\n        val compiled = RoutePolicyCompiler.compile(profiles, defaultTarget)",
    "RoutePolicyApplier default target",
)
write(applier_rel, applier)

# Combine application selection and destination routing in one VPN build.
tun_rel = "app/src/main/java/com/csqtt/client/TunVpnService.kt"
tun = read(tun_rel)
tun = tun.replace("import com.csqtt.client.routing.RoutingSourceMode\n", "")
if "import com.csqtt.client.routing.RouteTarget\n" not in tun:
    tun = replace_required(
        tun,
        "import com.csqtt.client.routing.RoutePolicyApplier\n",
        "import com.csqtt.client.routing.RoutePolicyApplier\nimport com.csqtt.client.routing.RouteTarget\n",
        "TunVpnService RouteTarget import",
    )
tun = replace_required(
    tun,
    "            val routingSourceMode = routeListStore.routingSourceMode()\n",
    "",
    "obsolete routing source mode",
)
pattern = re.compile(
    r"\n            if \(routingSourceMode == RoutingSourceMode\.APPLICATIONS\) \{.*?\n            \}\n            val pfd = builder\.establish\(\)",
    re.S,
)
replacement = r'''
            val profiles = routeListStore.loadProfiles()
            val installedSelected = userSelected
                .filter { pkg -> pkg !in transportPackages && isPackageInstalled(pkg) }
                .toSet()

            if (installedSelected.isNotEmpty()) {
                // Combined mode: selected applications are a full WDTTSL scope.
                // Destination profiles are compiled on top of WDTTSL, therefore
                // MOBILE prefixes carve deterministic holes and more-specific
                // WDTTSL prefixes can opt back in (longest-prefix wins).
                val routeCount = RoutePolicyApplier.apply(
                    builder,
                    profiles,
                    defaultTarget = RouteTarget.WDTTSL,
                )
                Log.i(TAG, "VPNSL combined mode: ${installedSelected.size} apps, $routeCount VPN routes")

                if (routeCount > 0) {
                    var validDnsServers = 0
                    dns.split(",").map { it.trim() }.filter { it.isNotEmpty() }.forEach { dnsServer ->
                        try {
                            builder.addDnsServer(dnsServer)
                            validDnsServers++
                        } catch (e: Exception) {
                            Log.w(TAG, "Invalid DNS server: $dnsServer")
                        }
                    }
                    if (validDnsServers == 0) {
                        failVpn("сервер передал некорректный DNS: $dns")
                        return
                    }
                }

                var includedCount = 0
                installedSelected.forEach { pkg ->
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
            } else {
                // No app scope selected: preserve Keenetic-style global route
                // lists from 1.0.5. MOBILE is the default and only compiled
                // WDTTSL destinations enter TUN.
                val routeCount = RoutePolicyApplier.apply(
                    builder,
                    profiles,
                    defaultTarget = RouteTarget.MOBILE,
                )
                Log.i(TAG, "VPNSL global route-list mode: $routeCount VPN routes")
                transportPackages
                    .filter { isPackageInstalled(it) }
                    .forEach { pkg ->
                        try { builder.addDisallowedApplication(pkg) } catch (_: Exception) {}
                    }
            }
            val pfd = builder.establish()'''
tun, count = pattern.subn(replacement, tun, count=1)
if count != 1:
    raise SystemExit("VPNSL 1.0.6 anchor missing: TunVpnService routing branch")
write(tun_rel, tun)

# Unit tests for the new default-target compiler behaviour.
test_src = CUSTOM / "RoutePolicyCompilerV106Test.kt"
test_dst = ROOT / "app/src/test/java/com/csqtt/client/routing/RoutePolicyCompilerV106Test.kt"
if not test_src.is_file():
    raise SystemExit("missing RoutePolicyCompilerV106Test.kt")
test_dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(test_src, test_dst)

# App identity/version.
gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1006', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.6"', gradle, count=1)
write("app/build.gradle.kts", gradle)

screen_rel = "app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt"
screen = read(screen_rel).replace("1.0.5 by Sazhaev-IA", "1.0.6 by Sazhaev-IA")
write(screen_rel, screen)

# Original VPNSL launcher icon: shield + two route branches. The adaptive-icon
# container remains unchanged, so it works on round/squircle launchers and in
# monochrome themed-icon mode.
icon = '''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="M54,17 L83,28 L83,49 C83,69 71,83 54,92 C37,83 25,69 25,49 L25,28 Z" />
    <path
        android:fillColor="#FF0474FB"
        android:pathData="M40,39 A5,5 0,1 0,40,49 A5,5 0,1 0,40,39 M68,39 A5,5 0,1 0,68,49 A5,5 0,1 0,68,39 M54,62 A6,6 0,1 0,54,74 A6,6 0,1 0,54,62 M44,44 L64,44 L64,49 L57,62 L51,62 L44,49 Z" />
</vector>
'''
write("app/src/main/res/drawable/ic_launcher_foreground.xml", icon)

checks = {
    "version 1.0.6": 'versionName = "1.0.6"' in read("app/build.gradle.kts"),
    "version code 1006": 'versionCode = 1006' in read("app/build.gradle.kts"),
    "header 1.0.6": '1.0.6 by Sazhaev-IA' in read(screen_rel),
    "combined editor": 'RoutingEditorTab' in read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"),
    "no source mode UI": 'RoutingSourceMode' not in read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"),
    "compiler default target": 'defaultTarget: RouteTarget = RouteTarget.MOBILE' in read(compiler_rel),
    "selected app full policy": 'defaultTarget = RouteTarget.WDTTSL' in read(tun_rel),
    "global route fallback": 'defaultTarget = RouteTarget.MOBILE' in read(tun_rel),
    "app allow list": 'builder.addAllowedApplication(pkg)' in read(tun_rel),
    "route tests": test_dst.is_file(),
    "custom launcher icon": 'M54,17 L83,28' in read("app/src/main/res/drawable/ic_launcher_foreground.xml"),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.6 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.6 combined applications + IP/CIDR routing applied")
