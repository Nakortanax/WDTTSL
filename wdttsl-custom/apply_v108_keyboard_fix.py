#!/usr/bin/env python3
from pathlib import Path
import re
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


# Remove the large promo banner from the routing screen. The generator needs
# maximum vertical space while the software keyboard is open.
exceptions_rel = "app/src/main/java/com/csqtt/client/ui/ExceptionsTab.kt"
exceptions = read(exceptions_rel)
promo_block = '''        PromoRoutingHeader(
            mode = routingSourceMode,
            selectedApps = selectedPackages.size,
        )

'''
if promo_block in exceptions:
    exceptions = exceptions.replace(
        promo_block,
        "        // PromoRoutingHeader removed in VPNSL 1.0.8 generator hotfix\n",
        1,
    )
write(exceptions_rel, exceptions)

route_rel = "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
route = read(route_rel)

# Do not use imePadding: with Android window handling it can cause a second
# compensation. Instead detect the real IME inset and place only the generator
# controls just above the keyboard.
route = route.replace("import androidx.compose.foundation.layout.imePadding\n", "")

import_anchor = "import androidx.compose.foundation.layout.Row\n"
if "import androidx.compose.foundation.layout.Spacer\n" not in route:
    route = replace_required(
        route,
        import_anchor,
        import_anchor
        + "import androidx.compose.foundation.layout.Spacer\n"
        + "import androidx.compose.foundation.layout.WindowInsets\n"
        + "import androidx.compose.foundation.layout.height\n"
        + "import androidx.compose.foundation.layout.ime\n",
        "IME layout imports",
    )
if "import androidx.compose.ui.platform.LocalDensity\n" not in route:
    route = replace_required(
        route,
        "import androidx.compose.ui.platform.LocalContext\n",
        "import androidx.compose.ui.platform.LocalContext\nimport androidx.compose.ui.platform.LocalDensity\n",
        "LocalDensity import",
    )

scope_anchor = "    val scope = rememberCoroutineScope()\n"
if "val imeBottomPx = WindowInsets.ime.getBottom(LocalDensity.current)" not in route:
    route = replace_required(
        route,
        scope_anchor,
        scope_anchor
        + "    val density = LocalDensity.current\n"
        + "    val imeBottomPx = WindowInsets.ime.getBottom(density)\n"
        + "    val imeVisible = imeBottomPx > 0\n"
        + "    val imeBottomDp = with(density) { imeBottomPx.toDp() }\n",
        "IME state",
    )

# Remove the previous Activity soft-input override if it is present in the clean
# source produced by an earlier 1.0.8 hotfix. The new layout does not depend on
# changing Android's window mode.
route = route.replace("import android.app.Activity\n", "")
route = route.replace("import android.view.WindowManager\n", "")
route = route.replace("import androidx.compose.runtime.DisposableEffect\n", "")
route = re.sub(
    r'''    val activity = context as\? Activity\n\n    DisposableEffect\(selectedTab, activity\) \{.*?    \}\n\n''',
    "",
    route,
    count=1,
    flags=re.S,
)

start = route.find("            RouteSubTab.GENERATOR -> {")
end_marker = "        }\n    }\n}\n\n@Composable\nprivate fun RouteSubTabs"
end = route.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("VPNSL 1.0.8 keyboard fix: generator branch not found")

branch = '''            RouteSubTab.GENERATOR -> {
                if (imeVisible) {
                    // Dedicated keyboard-open layout. There is no LazyColumn here,
                    // so Compose cannot auto-scroll the focused field to the top.
                    // Only the generator controls move, and they are anchored just
                    // above the keyboard using the actual IME height.
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .padding(bottom = imeBottomDp + 12.dp),
                    ) {
                        Spacer(modifier = Modifier.weight(1f))
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            OutlinedTextField(
                                value = generatorInput,
                                onValueChange = {
                                    generatorInput = it
                                    generatedHost = null
                                    generatedIpv4 = emptyList()
                                    generatorStatus = null
                                },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text("Имя сайта") },
                                placeholder = { Text("chatgpt.com") },
                            )

                            Button(
                                onClick = {
                                    val host = normalizeHost(generatorInput)
                                    if (host == null) {
                                        generatorStatus = "Некорректное имя сайта"
                                        return@Button
                                    }
                                    resolving = true
                                    generatorStatus = "Поиск IPv4 для $host…"
                                    generatedHost = null
                                    generatedIpv4 = emptyList()
                                    scope.launch {
                                        val result = withContext(Dispatchers.IO) {
                                            runCatching {
                                                InetAddress.getAllByName(host)
                                                    .filterIsInstance<Inet4Address>()
                                                    .mapNotNull { it.hostAddress }
                                                    .distinct()
                                                    .sorted()
                                            }
                                        }
                                        resolving = false
                                        result.onSuccess { addresses ->
                                            if (addresses.isEmpty()) {
                                                generatorStatus = "IPv4-адреса для $host не найдены"
                                            } else {
                                                generatedHost = host
                                                generatedIpv4 = addresses
                                                generatorStatus = "Найдено IPv4: ${addresses.size}. BAT готов к сохранению."
                                            }
                                        }.onFailure { error ->
                                            generatorStatus = "Ошибка DNS: ${error.message ?: error.javaClass.simpleName}"
                                        }
                                    }
                                },
                                enabled = generatorInput.isNotBlank() && !resolving,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(if (resolving) "Поиск…" else "Найти IPv4 и сформировать .bat")
                            }
                        }
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        contentPadding = PaddingValues(top = 12.dp, bottom = 24.dp),
                    ) {
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text(
                                    "Генератор BAT по имени сайта",
                                    style = MaterialTheme.typography.titleMedium,
                                )
                                Text(
                                    "Введите домен или URL. VPNSL найдёт текущие IPv4-адреса (A-записи) и сформирует отдельный .bat с маршрутами /32.",
                                    style = MaterialTheme.typography.bodySmall,
                                )

                                OutlinedTextField(
                                    value = generatorInput,
                                    onValueChange = {
                                        generatorInput = it
                                        generatedHost = null
                                        generatedIpv4 = emptyList()
                                        generatorStatus = null
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true,
                                    label = { Text("Имя сайта") },
                                    placeholder = { Text("chatgpt.com") },
                                )

                                Button(
                                    onClick = {
                                        val host = normalizeHost(generatorInput)
                                        if (host == null) {
                                            generatorStatus = "Некорректное имя сайта"
                                            return@Button
                                        }
                                        resolving = true
                                        generatorStatus = "Поиск IPv4 для $host…"
                                        generatedHost = null
                                        generatedIpv4 = emptyList()
                                        scope.launch {
                                            val result = withContext(Dispatchers.IO) {
                                                runCatching {
                                                    InetAddress.getAllByName(host)
                                                        .filterIsInstance<Inet4Address>()
                                                        .mapNotNull { it.hostAddress }
                                                        .distinct()
                                                        .sorted()
                                                }
                                            }
                                            resolving = false
                                            result.onSuccess { addresses ->
                                                if (addresses.isEmpty()) {
                                                    generatorStatus = "IPv4-адреса для $host не найдены"
                                                } else {
                                                    generatedHost = host
                                                    generatedIpv4 = addresses
                                                    generatorStatus = "Найдено IPv4: ${addresses.size}. BAT готов к сохранению."
                                                }
                                            }.onFailure { error ->
                                                generatorStatus = "Ошибка DNS: ${error.message ?: error.javaClass.simpleName}"
                                            }
                                        }
                                    },
                                    enabled = generatorInput.isNotBlank() && !resolving,
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text(if (resolving) "Поиск…" else "Найти IPv4 и сформировать .bat")
                                }

                                generatedHost?.let { host ->
                                    Text(
                                        "Ресурс: $host",
                                        style = MaterialTheme.typography.labelLarge,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    generatedIpv4.forEach { address ->
                                        Text("• $address/32", style = MaterialTheme.typography.bodyMedium)
                                    }

                                    Button(
                                        onClick = {
                                            saveBat(
                                                "${safeFileStem(host)}.bat",
                                                RouteBatFormatter.buildSiteRoutesFile(host, generatedIpv4),
                                            )
                                        },
                                        enabled = generatedIpv4.isNotEmpty(),
                                        modifier = Modifier.fillMaxWidth(),
                                    ) {
                                        Text("Сохранить .bat в Загрузки")
                                    }
                                }

                                generatorStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                                saveStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                                Text(
                                    "DNS-адреса сайтов могут со временем меняться. При необходимости сформируйте файл заново, чтобы получить актуальные IPv4.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
'''

route = route[:start] + branch + route[end:]
write(route_rel, route)

checks = {
    "banner removed": "        PromoRoutingHeader(" not in read(exceptions_rel),
    "no double ime padding": "imePadding" not in read(route_rel),
    "IME detected": "val imeVisible = imeBottomPx > 0" in read(route_rel),
    "keyboard branch has no lazy scroll": "Dedicated keyboard-open layout" in read(route_rel),
    "field anchored above keyboard": ".padding(bottom = imeBottomDp + 12.dp)" in read(route_rel),
    "field pushed downward": "Spacer(modifier = Modifier.weight(1f))" in read(route_rel),
    "generator DNS intact": "InetAddress.getAllByName(host)" in read(route_rel),
    "file import intact": "store.importProfile(name, text, RouteTarget.WDTTSL)" in read(route_rel),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.8 keyboard fix verification failed: " + ", ".join(failed))

print("VPNSL 1.0.8: generator field anchored low above IME without LazyColumn auto-scroll")
