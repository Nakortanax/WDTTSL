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


# Replace the generated route/exceptions UI with the tested 1.0.2 layout.
for name in ("RouteListsSection.kt", "ExceptionsTab.kt"):
    src = CUSTOM / name
    dst = ROOT / f"app/src/main/java/com/csqtt/client/ui/{name}"
    if not src.is_file():
        raise SystemExit(f"missing custom file: {src}")
    shutil.copyfile(src, dst)

# Version bump.
gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1002', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.2"', gradle, count=1)
write("app/build.gradle.kts", gradle)

screen = read("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt")
screen = screen.replace('1.0.1 by Sazhaev-IA', '1.0.2 by Sazhaev-IA')
write("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt", screen)

# The app has a global horizontal tab-swipe detector. On the routing page a
# diagonal vertical scroll could accumulate enough X movement to switch from
# Exceptions to Deploy. Disable that gesture only on tab id 3; bottom navigation
# buttons remain fully functional.
main = read("app/src/main/java/com/csqtt/client/MainActivity.kt")
anchor = '.pointerInput(selectedTab, csqttLinkMode) {\n                        var totalDrag = 0f'
replacement = '.pointerInput(selectedTab, csqttLinkMode) {\n                        if (selectedTab == 3) return@pointerInput\n                        var totalDrag = 0f'
if anchor not in main:
    raise SystemExit("MainActivity navigation swipe anchor missing")
main = main.replace(anchor, replacement, 1)
write("app/src/main/java/com/csqtt/client/MainActivity.kt", main)

checks = {
    "version 1.0.2": 'versionName = "1.0.2"' in read("app/build.gradle.kts"),
    "version code 1002": 'versionCode = 1002' in read("app/build.gradle.kts"),
    "header version": '1.0.2 by Sazhaev-IA' in screen,
    "route lazy list": 'LazyColumn(' in read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"),
    "route activation": 'Switch(' in read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"),
    "route network label": 'Сеть: ${targetName(profile.target)}' in read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"),
    "manual newest first": 'persist(listOf(profile) + profiles)' in read("app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"),
    "route owns remaining height": 'RouteListsSection(Modifier.fillMaxWidth().weight(1f))' in read("app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"),
    "exceptions swipe disabled": 'if (selectedTab == 3) return@pointerInput' in main,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.2 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.2 UI/routing-page fixes applied")
