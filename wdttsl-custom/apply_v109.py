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
        raise SystemExit(f"VPNSL 1.0.9 anchor missing: {label}")
    return text.replace(old, new, 1)


# VPNSL 1.0.9 keeps the complete 1.0.8 routing editor/generator and adds
# FULL_TUNNEL as the primary/default mode. Existing saved APPLICATIONS or
# ROUTE_LISTS preferences are preserved on upgrade; a fresh install defaults
# to FULL_TUNNEL.
for src_name, dst_name in (
    ("ExceptionsTabV109.kt", "ExceptionsTab.kt"),
    ("PromoRoutingHeaderV109.kt", "PromoRoutingHeader.kt"),
):
    src = CUSTOM / src_name
    dst = ROOT / f"app/src/main/java/com/csqtt/client/ui/{dst_name}"
    if not src.is_file():
        raise SystemExit(f"missing VPNSL 1.0.9 custom file: {src}")
    shutil.copyfile(src, dst)

# Locate the generated routing-mode enum and its store independently. The
# overlay keeps them in separate Kotlin files.
routing_root = ROOT / "app/src/main/java/com/csqtt/client/routing"
enum_candidates = []
store_candidates = []
for path in routing_root.rglob("*.kt"):
    text = path.read_text(encoding="utf-8")
    if "enum class RoutingSourceMode" in text:
        enum_candidates.append(path)
    if "fun routingSourceMode" in text:
        store_candidates.append(path)

if len(enum_candidates) != 1:
    raise SystemExit(
        "VPNSL 1.0.9 expected exactly one RoutingSourceMode enum, found: " +
        ", ".join(str(p.relative_to(ROOT)) for p in enum_candidates)
    )
if len(store_candidates) != 1:
    raise SystemExit(
        "VPNSL 1.0.9 expected exactly one routingSourceMode() store, found: " +
        ", ".join(str(p.relative_to(ROOT)) for p in store_candidates)
    )

enum_path = enum_candidates[0]
enum_text = enum_path.read_text(encoding="utf-8")
enum_pattern = re.compile(r"enum class RoutingSourceMode\s*\{(?P<body>.*?)\}", re.S)
enum_match = enum_pattern.search(enum_text)
if not enum_match:
    raise SystemExit("VPNSL 1.0.9 RoutingSourceMode enum body not found")
enum_body = enum_match.group("body")
if "FULL_TUNNEL" not in enum_body:
    original_enum = enum_match.group(0)
    replacement = original_enum.replace(
        "{",
        "{\n    FULL_TUNNEL,",
        1,
    )
    enum_text = enum_text[:enum_match.start()] + replacement + enum_text[enum_match.end():]
enum_path.write_text(enum_text, encoding="utf-8")

# Change only the fallback inside routingSourceMode(), so fresh installs use
# FULL_TUNNEL while already-saved APPLICATIONS/ROUTE_LISTS values remain valid.
store_path = store_candidates[0]
store_text = store_path.read_text(encoding="utf-8")
fn_start = store_text.find("fun routingSourceMode")
if fn_start < 0:
    raise SystemExit("VPNSL 1.0.9 routingSourceMode() function not found")
next_fun = store_text.find("\n    fun ", fn_start + 1)
if next_fun < 0:
    next_fun = len(store_text)
fn_segment = store_text[fn_start:next_fun]
if "RoutingSourceMode.APPLICATIONS" not in fn_segment:
    raise SystemExit(
        "VPNSL 1.0.9 default routing mode anchor not found in " +
        str(store_path.relative_to(ROOT))
    )
fn_segment = fn_segment.replace(
    "RoutingSourceMode.APPLICATIONS",
    "RoutingSourceMode.FULL_TUNNEL",
)
store_text = store_text[:fn_start] + fn_segment + store_text[next_fun:]
store_path.write_text(store_text, encoding="utf-8")

# Wrap the proven 1.0.8 APPLICATIONS/ROUTE_LISTS runtime without rewriting it.
# FULL_TUNNEL explicitly installs 0.0.0.0/0, DNS from the server and excludes
# VPNSL/VK transport processes so the carrier cannot loop into its own VPN.
tun_rel = "app/src/main/java/com/csqtt/client/TunVpnService.kt"
tun = read(tun_rel)
app_marker = "            if (routingSourceMode == RoutingSourceMode.APPLICATIONS) {"
full_tunnel_branch = '''            if (routingSourceMode == RoutingSourceMode.FULL_TUNNEL) {
                builder.addRoute("0.0.0.0", 0)

                var fullTunnelDnsServers = 0
                dns.split(",").map { it.trim() }.filter { it.isNotEmpty() }.forEach { dnsServer ->
                    try {
                        builder.addDnsServer(dnsServer)
                        fullTunnelDnsServers++
                    } catch (error: Exception) {
                        Log.w(TAG, "Invalid DNS server in full-tunnel mode: $dnsServer", error)
                    }
                }
                if (fullTunnelDnsServers == 0) {
                    failVpn("сервер передал некорректный DNS: $dns")
                    return
                }

                try {
                    builder.addDisallowedApplication(applicationContext.packageName)
                } catch (error: Exception) {
                    Log.e(TAG, "Unable to exclude VPNSL UID from its own VPN", error)
                    failVpn("Android не разрешил исключить VPNSL из собственного VPN")
                    return
                }
                transportPackages
                    .filter { pkg -> pkg != applicationContext.packageName && isPackageInstalled(pkg) }
                    .forEach { pkg ->
                        try {
                            builder.addDisallowedApplication(pkg)
                        } catch (error: Exception) {
                            Log.w(TAG, "Unable to exclude transport package $pkg from full-tunnel VPN", error)
                        }
                    }

                Log.i(TAG, "VPNSL full-tunnel mode: 0.0.0.0/0 through VPN")
            } else {
                if (routingSourceMode == RoutingSourceMode.APPLICATIONS) {'''
tun = replace_required(
    tun,
    app_marker,
    full_tunnel_branch,
    "TunVpnService APPLICATIONS branch",
)
pfd_marker = "\n            val pfd = builder.establish()"
pfd_index = tun.find(pfd_marker, tun.find("RoutingSourceMode.FULL_TUNNEL"))
if pfd_index < 0:
    raise SystemExit("VPNSL 1.0.9 TunVpnService establish() anchor missing")
tun = tun[:pfd_index] + "\n            }" + tun[pfd_index:]
write(tun_rel, tun)

# Version bump.
gradle_rel = "app/build.gradle.kts"
gradle = read(gradle_rel)
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1009', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.9"', gradle, count=1)
write(gradle_rel, gradle)

screen_rel = "app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt"
screen = read(screen_rel).replace("1.0.8 by Sazhaev-IA", "1.0.9 by Sazhaev-IA")
write(screen_rel, screen)

# Strong invariants: new default plus all 1.0.8 optional routing/generator paths.
mode_after = enum_path.read_text(encoding="utf-8") + "\n" + store_path.read_text(encoding="utf-8")
tun_after = read(tun_rel)
exceptions = read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt")
route = read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt")
checks = {
    "version 1.0.9": 'versionName = "1.0.9"' in read(gradle_rel),
    "version code 1009": 'versionCode = 1009' in read(gradle_rel),
    "header 1.0.9": '1.0.9 by Sazhaev-IA' in read(screen_rel),
    "FULL_TUNNEL enum": "FULL_TUNNEL" in mode_after,
    "fresh default full tunnel": "RoutingSourceMode.FULL_TUNNEL" in mode_after[mode_after.find("fun routingSourceMode"):],
    "full tunnel default route": 'builder.addRoute("0.0.0.0", 0)' in tun_after,
    "full tunnel DNS": "fullTunnelDnsServers" in tun_after,
    "transport bypass": "builder.addDisallowedApplication(applicationContext.packageName)" in tun_after,
    "application mode preserved": "if (routingSourceMode == RoutingSourceMode.APPLICATIONS)" in tun_after,
    "application allow-list preserved": "builder.addAllowedApplication(pkg)" in tun_after,
    "route-list runtime preserved": "RoutePolicyApplier.apply(builder, routeListStore.loadProfiles())" in tun_after,
    "three routing modes UI": 'RoutingSourceMode.FULL_TUNNEL to "Весь трафик"' in exceptions
        and 'RoutingSourceMode.APPLICATIONS to "Приложения"' in exceptions
        and 'RoutingSourceMode.ROUTE_LISTS to "IP / файлы"' in exceptions,
    "manual IP/CIDR preserved": "IP-адрес или подсеть" in route,
    "BAT generator preserved": "Генератор BAT по имени сайта" in route,
    "DNS generator preserved": "InetAddress.getAllByName(host)" in route,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.9 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.9: full tunnel default + optional applications/IP routing preserved")
