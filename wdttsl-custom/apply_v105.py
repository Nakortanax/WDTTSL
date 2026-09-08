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
    (ROOT / rel).write_text(text, encoding="utf-8")


# Install VPNSL routing UI plus BAT formatter and its unit tests.
for name in ("RouteListsSection.kt", "ExceptionsTab.kt"):
    src = CUSTOM / name
    dst = ROOT / f"app/src/main/java/com/csqtt/client/ui/{name}"
    if not src.is_file():
        raise SystemExit(f"missing custom file: {src}")
    shutil.copyfile(src, dst)

formatter_src = CUSTOM / "RouteBatFormatter.kt"
formatter_dst = ROOT / "app/src/main/java/com/csqtt/client/routing/RouteBatFormatter.kt"
formatter_dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(formatter_src, formatter_dst)

test_src = CUSTOM / "RouteBatFormatterTest.kt"
test_dst = ROOT / "app/src/test/java/com/csqtt/client/routing/RouteBatFormatterTest.kt"
test_dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(test_src, test_dst)

# Version bump.
gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1005', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.5"', gradle, count=1)
write("app/build.gradle.kts", gradle)

screen = read("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt")
for old in (
    '1.0.1 by Sazhaev-IA',
    '1.0.2 by Sazhaev-IA',
    '1.0.3 by Sazhaev-IA',
    '1.0.4 by Sazhaev-IA',
):
    screen = screen.replace(old, '1.0.5 by Sazhaev-IA')
write("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt", screen)

# Keep the routing-page swipe fix introduced in 1.0.2.
main = read("app/src/main/java/com/csqtt/client/MainActivity.kt")
if 'if (selectedTab == 3) return@pointerInput' not in main:
    anchor = '.pointerInput(selectedTab, csqttLinkMode) {\n                        var totalDrag = 0f'
    replacement = '.pointerInput(selectedTab, csqttLinkMode) {\n                        if (selectedTab == 3) return@pointerInput\n                        var totalDrag = 0f'
    if anchor not in main:
        raise SystemExit("MainActivity navigation swipe anchor missing")
    main = main.replace(anchor, replacement, 1)
    write("app/src/main/java/com/csqtt/client/MainActivity.kt", main)

route = read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt")
formatter = read("app/src/main/java/com/csqtt/client/routing/RouteBatFormatter.kt")
checks = {
    "version 1.0.5": 'versionName = "1.0.5"' in read("app/build.gradle.kts"),
    "version code 1005": 'versionCode = 1005' in read("app/build.gradle.kts"),
    "header version": '1.0.5 by Sazhaev-IA' in screen,
    "route lazy list": 'LazyColumn(' in route,
    "flat route list": 'HorizontalDivider(' in route and 'Card(' not in route,
    "activation switch": 'Switch(' in route,
    "network popup": 'AlertDialog(' in route and 'RadioButton(' in route,
    "manual label": 'Подпись ресурса' in route and 'name = label' in route,
    "all routes export": 'Выгрузить все маршруты (.bat)' in route and 'buildAllRoutesFile(profiles)' in route,
    "generator tab": 'RouteSubTab.GENERATOR' in route and 'Генератор BAT по имени сайта' in route,
    "dns ipv4 generator": 'InetAddress.getAllByName(host)' in route and 'filterIsInstance<Inet4Address>()' in route,
    "downloads save": 'MediaStore.Downloads.EXTERNAL_CONTENT_URI' in route and 'Environment.DIRECTORY_DOWNLOADS' in route,
    "site bat save": 'buildSiteRoutesFile(host, generatedIpv4)' in route,
    "bat route command": 'route add ${parts[0]} mask ${prefixToMask(prefix)} 0.0.0.0' in formatter,
    "no large route segmented selector": 'CsqttSegmentedControl' not in route,
    "route owns remaining height": 'RouteListsSection(Modifier.fillMaxWidth().weight(1f))' in read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"),
    "exceptions swipe disabled": 'if (selectedTab == 3) return@pointerInput' in main,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.5 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.5 route export, labels and BAT generator applied")
