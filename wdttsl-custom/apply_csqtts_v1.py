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
        raise SystemExit(f"VPNSL customization anchor missing: {label}")
    return text.replace(old, new, 1)


# Replace generated route-list UI with the current VPNSL custom UI.
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

# Project/app identity shown to the user. Keep applicationId unchanged so existing
# installations keep their app data/device identity when Android accepts the update signature.
settings = read("settings.gradle.kts")
settings = re.sub(r'rootProject\.name\s*=\s*"[^"]+"', 'rootProject.name = "VPNSL"', settings, count=1)
write("settings.gradle.kts", settings)

gradle = read("app/build.gradle.kts")
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1001', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.1"', gradle, count=1)
write("app/build.gradle.kts", gradle)

strings = read("app/src/main/res/values/strings.xml")
strings = re.sub(r'<string name="app_name">.*?</string>', '<string name="app_name">VPNSL</string>', strings, count=1)
write("app/src/main/res/values/strings.xml", strings)

manifest = read("app/src/main/AndroidManifest.xml")
manifest = manifest.replace('android:label="WDTTSL"', 'android:label="VPNSL"')
manifest = manifest.replace('android:label="CSQTT"', 'android:label="VPNSL"')
manifest = manifest.replace('android:label="CSQTTS"', 'android:label="VPNSL"')
write("app/src/main/AndroidManifest.xml", manifest)

# Header: textual VPNSL branding instead of original image badges.
screen = read("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt")
old_logo = '''                Icon(\n                    painter = painterResource(id = R.drawable.ic_csqtt_logo),\n                    contentDescription = "CSQTT",\n                    tint = Color.Unspecified,\n                    modifier = Modifier.height(26.dp)\n                )'''
new_logo = '''                Text(\n                    text = "VPNSL",\n                    style = MaterialTheme.typography.titleLarge,\n                    fontWeight = FontWeight.Bold,\n                    color = MaterialTheme.colorScheme.primary,\n                )'''
screen = replace_required(screen, old_logo, new_logo, "CsqttScreen logo")
old_version = '''                    Icon(\n                        painter = painterResource(id = R.drawable.ic_v219_by_amurcanov),\n                        contentDescription = "v2.1.9 by amurcanov",\n                        tint = Color.Unspecified,\n                        modifier = Modifier.height(19.dp)\n                    )'''
new_version = '''                    Text(\n                        text = "1.0.1 by Sazhaev-IA",\n                        style = MaterialTheme.typography.labelLarge,\n                        color = MaterialTheme.colorScheme.onSurfaceVariant,\n                    )'''
screen = replace_required(screen, old_version, new_version, "CsqttScreen version badge")
write("app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt", screen)

# All public/update GitHub links point to Nakortanax/WDTTSL.
constants = read("app/src/main/java/com/csqtt/client/Constants.kt")
constants = constants.replace('const val APP_NAME = "CSQTT"', 'const val APP_NAME = "VPNSL"')
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
    raise SystemExit("VPNSL customization anchor missing: InfoHeroCard call")
info = info.replace('    var showCryptoDialog by remember { mutableStateOf(false) }\n', '')
info = re.sub(
    r'''\n\s*if \(showCryptoDialog\) \{\n\s*CryptoDonateDialog\(onDismiss = \{ showCryptoDialog = false \}\)\n\s*\}\n''',
    '\n',
    info,
    count=1,
)
info = info.replace('title = "Автор Android-версии"', 'title = "Автор VPNSL"')
info = info.replace('subtitle = "GitHub профиль amurcanov"', 'subtitle = "Sazhaev-IA · GitHub Nakortanax"')
info = info.replace('title = "Репозиторий CSQTT"', 'title = "Репозиторий VPNSL"')
info = info.replace('ClipData.newPlainText("CSQTT Report", buildSupportReport())', 'ClipData.newPlainText("VPNSL Report", buildSupportReport())')
write("app/src/main/java/com/csqtt/client/ui/InfoTab.kt", info)

# Update HTTP identity and use only Releases from the fork. A fork can inherit
# upstream tags such as v2.1.9, which are not VPNSL releases.
update = read("app/src/main/java/com/csqtt/client/AppUpdate.kt")
update = update.replace('"CSQTTAndroid/${BuildConfig.VERSION_NAME}"', '"VPNSLAndroid/${BuildConfig.VERSION_NAME}"')
old_fetch = """suspend fun fetchLatestReleaseInfo(localVersion: String? = null): AppReleaseInfo? = withContext(Dispatchers.IO) {
    val latestRelease = fetchReleaseFromLatestWebRedirect()
        ?: fetchReleaseFromLatestEndpoint()
        ?: fetchLatestStableReleaseFromList()
    val latestTag = fetchLatestTagFromList()

    when {
        latestRelease == null -> latestTag
        latestTag == null -> latestRelease
        isNewerVersion(latestRelease.versionTag, latestTag.versionTag) -> latestTag
        else -> latestRelease
    }
}"""
new_fetch = """suspend fun fetchLatestReleaseInfo(localVersion: String? = null): AppReleaseInfo? = withContext(Dispatchers.IO) {
    fetchReleaseFromLatestWebRedirect()
        ?: fetchReleaseFromLatestEndpoint()
        ?: fetchLatestStableReleaseFromList()
}"""
update = replace_required(update, old_fetch, new_fetch, "VPNSL releases-only updater")
write("app/src/main/java/com/csqtt/client/AppUpdate.kt", update)

# Visible VPN/session/notification branding. Protocol/event constants remain CSQTT
# because the server wire protocol must stay compatible with CSQTT-WIRE-3.
tun = read("app/src/main/java/com/csqtt/client/TunVpnService.kt")
tun = tun.replace('.setSession("WDTTSL")', '.setSession("VPNSL")')
tun = tun.replace('.setSession("CSQTT")', '.setSession("VPNSL")')
tun = tun.replace('.setSession("CSQTTS")', '.setSession("VPNSL")')
write("app/src/main/java/com/csqtt/client/TunVpnService.kt", tun)

service = read("app/src/main/java/com/csqtt/client/TunnelService.kt")
service = service.replace('"CSQTT Туннель"', '"VPNSL Туннель"')
service = service.replace('.setContentTitle("CSQTT")', '.setContentTitle("VPNSL")')
service = service.replace('"WDTTSL"', '"VPNSL"')
service = service.replace('"CSQTTS"', '"VPNSL"')
write("app/src/main/java/com/csqtt/client/TunnelService.kt", service)

# Sanity checks. DNS is allowed only as a user-invoked BAT generator in later
# VPNSL versions; actual VPN routing still consumes explicit IPv4/CIDR entries.
route_text = route_dst.read_text(encoding="utf-8")
checks = {
    "version 1.0.1": 'versionName = "1.0.1"' in read("app/build.gradle.kts"),
    "version code 1001": 'versionCode = 1001' in read("app/build.gradle.kts"),
    "app name": '>VPNSL</string>' in read("app/src/main/res/values/strings.xml"),
    "github repo": 'https://github.com/Nakortanax/WDTTSL' in read("app/src/main/java/com/csqtt/client/Constants.kt"),
    "manual IPv4 route UI": 'IP-адрес или подсеть' in route_text,
    "new header": '1.0.1 by Sazhaev-IA' in screen,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL customization verification failed: " + ", ".join(failed))

print("VPNSL base customizations applied")
