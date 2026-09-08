#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel, text):
    path = ROOT / rel
    path.write_text(text, encoding="utf-8")


def replace_required(text, old, new, label):
    if old not in text:
        raise SystemExit(f"VPNSL 1.0.8 keyboard fix anchor missing: {label}")
    return text.replace(old, new, 1)


# Remove the large promo banner from the routing screen. It consumes exactly
# the vertical area that the generator needs when the software keyboard is open.
exceptions_rel = "app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"
exceptions = read(exceptions_rel)
promo_block = '''        PromoRoutingHeader(
            mode = routingSourceMode,
            selectedApps = selectedPackages.size,
        )

'''
exceptions = replace_required(exceptions, promo_block, "", "promo banner")
write(exceptions_rel, exceptions)

# Generator keyboard behaviour:
# 1) Do not resize/lift the entire Activity while the generator is selected.
# 2) Do not add imePadding to the LazyColumn (that was causing a second shift).
# 3) Keep deliberate top spacing so the site field stays lower on screen.
route_rel = "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
route = read(route_rel)
route = replace_required(
    route,
    "import android.content.ContentValues\n",
    "import android.app.Activity\nimport android.content.ContentValues\n",
    "Activity import",
)
route = replace_required(
    route,
    "import android.provider.OpenableColumns\n",
    "import android.provider.OpenableColumns\nimport android.view.WindowManager\n",
    "WindowManager import",
)
route = route.replace("import androidx.compose.foundation.layout.imePadding\n", "")
route = replace_required(
    route,
    "import androidx.compose.runtime.Composable\n",
    "import androidx.compose.runtime.Composable\nimport androidx.compose.runtime.DisposableEffect\n",
    "DisposableEffect import",
)
route = replace_required(
    route,
    '''    var selectedTab by remember { mutableStateOf(RouteSubTab.ROUTES) }
    var routeStatus by remember { mutableStateOf<String?>(null) }
''',
    '''    var selectedTab by remember { mutableStateOf(RouteSubTab.ROUTES) }
    val activity = context as? Activity

    DisposableEffect(selectedTab, activity) {
        val window = activity?.window
        val previousSoftInputMode = window?.attributes?.softInputMode
        if (selectedTab == RouteSubTab.GENERATOR && window != null) {
            window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        }
        onDispose {
            if (window != null && previousSoftInputMode != null) {
                window.setSoftInputMode(previousSoftInputMode)
            }
        }
    }

    var routeStatus by remember { mutableStateOf<String?>(null) }
''',
    "generator soft input mode",
)
route = replace_required(
    route,
    '''                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .imePadding(),
                    contentPadding = PaddingValues(top = 12.dp, bottom = 96.dp),
''',
    '''                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentPadding = PaddingValues(top = 72.dp, bottom = 28.dp),
''',
    "generator IME padding",
)
write(route_rel, route)

# Strong assertions so CI cannot silently rebuild the old broken behaviour.
checks = {
    "banner removed": "PromoRoutingHeader(" not in read(exceptions_rel),
    "activity not resized": "SOFT_INPUT_ADJUST_NOTHING" in read(route_rel),
    "no double ime padding": ".imePadding()" not in read(route_rel),
    "generator lowered": "PaddingValues(top = 72.dp, bottom = 28.dp)" in read(route_rel),
    "generator DNS intact": "InetAddress.getAllByName(host)" in read(route_rel),
    "file import intact": "store.importProfile(name, text, RouteTarget.WDTTSL)" in read(route_rel),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.8 keyboard fix verification failed: " + ", ".join(failed))

print("VPNSL 1.0.8: generator keyboard no longer lifts whole UI; field positioned lower")
