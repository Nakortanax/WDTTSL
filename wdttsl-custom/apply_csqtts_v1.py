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


def replace_required(text, old, new, label):
    if old not in text:
        raise SystemExit(f"CSQTTS customization anchor missing: {label}")
    return text.replace(old, new, 1)


# Replace generated route-list UI with CSQTTS v1 UI.
route_src = CUSTOM / "RouteListsSection.kt"
route_dst = ROOT / "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
if not route_src.is_file():
    raise SystemExit("wdttsl-custom/RouteListsSection.kt is missing")
shutil.copyfile(route_src, route_dst)

hero_src = CUSTOM / "CsqttsInfoHeroCard.kt"
hero_dst = ROOT / "app/src/main/java/com/csqtt/client/ui/CsqttsInfoHeroCard.kt"
if not hero_src.is_file():
    raise SystemExit("wdttsl-custom/CsqttsInfoHeroCard.kt is missing")
shutil.copyfile(hero_src, hero_dst)

# Project/app identity shown to the user.
settings = read("settings.gradle.kts")
settings = re.sub(r'rootProject\.name\s*=\s*"[^"]+"', 'rootProject.name = "CSQTTS"', settings, count=1)
write("settings.gradle.kts", settings)

gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1000', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0"', gradle, count=1)
write("app/build.gradle.kts", gradle)

strings = read("app/src/main/res/values/strings.xml")
strings = re.sub(r'<string name="app_name">.*?</string>', '<string name="app_name">CSQTTS</string>', strings, count=1)
write("app/src/main/res/values/strings.xml", strings)

manifest = read("app/src/main/AndroidManifest.xml")
manifest = manifest.replace('android:label="WDTTSL"', 'android:label="CSQTTS"')
manifest = manifest.replace('android:label="CSQTT"', 'android:label="CSQTTS"')
write("app/src/main/AndroidManifest.xml", manifest)

# Header: textual branding instead of original CSQTT/amurcanov image badges.
screen = read("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt")
old_logo = '''                Icon(\n                    painter = painterResource(id = R.drawable.ic_csqtt_logo),\n                    contentDescription = "CSQTT",\n                    tint = Color.Unspecified,\n                    modifier = Modifier.height(26.dp)\n                )'''
new_logo = '''                Text(\n                    text = "CSQTTS",\n                    style = MaterialTheme.typography.titleLarge,\n                    fontWeight = FontWeight.Bold,\n                    color = MaterialTheme.colorScheme.primary,\n                )'''
screen = replace_required(screen, old_logo, new_logo, "CsqttScreen logo")
old_version = '''                    Icon(\n                        painter = painterResource(id = R.drawable.ic_v219_by_amurcanov),\n                        contentDescription = "v2.1.9 by amurcanov",\n                        tint = Color.Unspecified,\n                        modifier = Modifier.height(19.dp)\n                    )'''
new_version = '''                    Text(\n                        text = "1.0 by Sazhaev-IA",\n                        style = MaterialTheme.typography.labelLarge,\n                        color = MaterialTheme.colorScheme.onSurfaceVariant,\n                    )'''
screen = replace_required(screen, old_version, new_version, "CsqttScreen version badge")
write("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt", screen)

# All public/update GitHub links point to Nakortanax/WDTTSL.
constants = read("app/src/main/java/com/csqtt/client/Constants.kt")
constants = constants.replace('const val APP_NAME = "CSQTT"', 'const val APP_NAME = "CSQTTS"')
constants = constants.replace('https://api.github.com/repos/amurcanov/csqtt/releases?per_page=30', 'https://api.github.com/repos/Nakortanax/WDTTSL/releases?per_page=30')
constants = constants.replace('https://api.github.com/repos/amurcanov/csqtt/releases/latest', 'https://api.github.com/repos/Nakortanax/WDTTSL/releases/latest')
constants = constants.replace('https://github.com/amurcanov/csqtt/releases/latest', 'https://github.com/Nakortanax/WDTTSL/releases/latest')
constants = constants.replace('https://github.com/amurcanov/csqtt/releases/tag/', 'https://github.com/Nakortanax/WDTTSL/releases/tag/')
constants = constants.replace('https://api.github.com/repos/amurcanov/csqtt/tags?per_page=100', 'https://api.github.com/repos/Nakortanax/WDTTSL/tags?per_page=100')
constants = constants.replace('https://github.com/amurcanov/csqtt/tree/', 'https://github.com/Nakortanax/WDTTSL/tree/')
constants = constants.replace('const val RELEASES = "https://github.com/amurcanov/csqtt/releases"', 'const val RELEASES = "https://github.com/Nakortanax/WDTTSL/releases"')
constants = constants.replace('const val ISSUES = "https://github.com/amurcanov/csqtt/issues/new"', 'const val ISSUES = "https://github.com/Nakortanax/WDTTSL/issues/new"')
constants = constants.replace('const val DEVELOPER_PROFILE = "https://github.com/amurcanov"', 'const val DEVELOPER_PROFILE = "https://github.com/Nakortanax"')
constants = constants.replace('const val REPOSITORY = "https://github.com/amurcanov/csqtt"', 'const val REPOSITORY = "https://github.com/Nakortanax/WDTTSL"')
constants = constants.replace('const val DONATE = ""', 'const val DONATE = "https://github.com/Nakortanax/WDTTSL"')
write("app/src/main/java/com/csqtt/client/Constants.kt", constants)

# Info tab: no developer-support/donation controls, user GitHub identity only.
info = read("app/src/main/java/com/csqtt/client/ui/InfoTab.kt")
hero_pattern = re.compile(
    r'''\s*InfoHeroCard\(\n\s*currentVersion = currentVersion,\n\s*onSupportClick = \{ openUrlInBrowser\(context, DonateUrl\) \},\n\s*onCryptoClick = \{ showCryptoDialog = true \},\n\s*\)'''
)
info, count = hero_pattern.subn('\n            CsqttsInfoHeroCard(currentVersion = currentVersion)', info, count=1)
if count != 1:
    raise SystemExit("CSQTTS customization anchor missing: InfoHeroCard call")
info = info.replace('    var showCryptoDialog by remember { mutableStateOf(false) }\n', '')
info = re.sub(
    r'''\n\s*if \(showCryptoDialog\) \{\n\s*CryptoDonateDialog\(onDismiss = \{ showCryptoDialog = false \}\)\n\s*\}\n''',
    '\n',
    info,
    count=1,
)
info = info.replace('title = "Автор Android-версии"', 'title = "Автор CSQTTS"')
info = info.replace('subtitle = "GitHub профиль amurcanov"', 'subtitle = "Sazhaev-IA · GitHub Nakortanax"')
info = info.replace('title = "Репозиторий CSQTT"', 'title = "Репозиторий CSQTTS"')
info = info.replace('ClipData.newPlainText("CSQTT Report", buildSupportReport())', 'ClipData.newPlainText("CSQTTS Report", buildSupportReport())')
write("app/src/main/java/com/csqtt/client/ui/InfoTab.kt", info)

# Update HTTP identity to the new app name while retaining protocol internals.
update = read("app/src/main/java/com/csqtt/client/AppUpdate.kt")
update = update.replace('"CSQTTAndroid/${BuildConfig.VERSION_NAME}"', '"CSQTTSAndroid/${BuildConfig.VERSION_NAME}"')
write("app/src/main/java/com/csqtt/client/AppUpdate.kt", update)

# Visible VPN session name; protocol/event constants remain CSQTT for server compatibility.
tun = read("app/src/main/java/com/csqtt/client/TunVpnService.kt")
tun = tun.replace('.setSession("WDTTSL")', '.setSession("CSQTTS")')
tun = tun.replace('.setSession("CSQTT")', '.setSession("CSQTTS")')
write("app/src/main/java/com/csqtt/client/TunVpnService.kt", tun)

# Sanity checks.
checks = {
    "version 1.0": 'versionName = "1.0"' in read("app/build.gradle.kts"),
    "app name": '>CSQTTS</string>' in read("app/src/main/res/values/strings.xml"),
    "github repo": 'https://github.com/Nakortanax/WDTTSL' in read("app/src/main/java/com/csqtt/client/Constants.kt"),
    "manual website UI": 'Добавить сайт вручную' in route_dst.read_text(encoding="utf-8"),
    "new header": '1.0 by Sazhaev-IA' in screen,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("CSQTTS customization verification failed: " + ", ".join(failed))

print("CSQTTS v1 customizations applied")
