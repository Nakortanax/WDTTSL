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


# Replace generated route/exceptions UI with VPNSL 1.0.3 layout.
for name in ("RouteListsSection.kt", "ExceptionsTab.kt"):
    src = CUSTOM / name
    dst = ROOT / f"app/src/main/java/com/csqtt/client/ui/{name}"
    if not src.is_file():
        raise SystemExit(f"missing custom file: {src}")
    shutil.copyfile(src, dst)

# Version bump.
gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1003', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.3"', gradle, count=1)
write("app/build.gradle.kts", gradle)

screen = read("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt")
screen = screen.replace('1.0.1 by Sazhaev-IA', '1.0.3 by Sazhaev-IA')
screen = screen.replace('1.0.2 by Sazhaev-IA', '1.0.3 by Sazhaev-IA')
write("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt", screen)

# Keep the routing-page swipe fix from 1.0.2.
main = read("app/src/main/java/com/csqtt/client/MainActivity.kt")
if 'if (selectedTab == 3) return@pointerInput' not in main:
    anchor = '.pointerInput(selectedTab, csqttLinkMode) {\n                        var totalDrag = 0f'
    replacement = '.pointerInput(selectedTab, csqttLinkMode) {\n                        if (selectedTab == 3) return@pointerInput\n                        var totalDrag = 0f'
    if anchor not in main:
        raise SystemExit("MainActivity navigation swipe anchor missing")
    main = main.replace(anchor, replacement, 1)
    write("app/src/main/java/com/csqtt/client/MainActivity.kt", main)

route = read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt")
checks = {
    "version 1.0.3": 'versionName = "1.0.3"' in read("app/build.gradle.kts"),
    "version code 1003": 'versionCode = 1003' in read("app/build.gradle.kts"),
    "header version": '1.0.3 by Sazhaev-IA' in screen,
    "route lazy list": 'LazyColumn(' in route,
    "flat route list": 'HorizontalDivider(' in route and 'Card(' not in route,
    "no Card import": 'import androidx.compose.material3.Card' not in route,
    "activation switch": 'Switch(' in route,
    "route network label": 'Сеть: ${targetName(profile.target)}' in route,
    "manual newest first": 'persist(listOf(profile) + profiles)' in route,
    "route owns remaining height": 'RouteListsSection(Modifier.fillMaxWidth().weight(1f))' in read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"),
    "exceptions swipe disabled": 'if (selectedTab == 3) return@pointerInput' in main,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.3 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.3 flat route-list UI applied")
