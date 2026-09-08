#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel, text):
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_required(text, old, new, label):
    if old not in text:
        raise SystemExit(f"VPNSL 1.0.8 keyboard fix anchor missing: {label}")
    return text.replace(old, new, 1)


# Keep the original 1.0.8 screen structure and Android's normal adjustResize.
# The original generator sat inside a LazyColumn. When the field got focus,
# Android resized the window once and LazyColumn/BringIntoView scrolled it again.
# That looked like the interface moving upward twice.
#
# Do NOT switch layouts based on IME visibility: replacing the focused TextField
# when the keyboard appears destroys focus and makes the keyboard close.
# Do NOT add imePadding: adjustResize already accounts for the keyboard.
route_rel = "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
route = read(route_rel)
route = route.replace("import androidx.compose.foundation.layout.imePadding\n", "")

if "import androidx.compose.foundation.layout.Spacer\n" not in route:
    route = replace_required(
        route,
        "import androidx.compose.foundation.layout.Row\n",
        "import androidx.compose.foundation.layout.Row\nimport androidx.compose.foundation.layout.Spacer\n",
        "Spacer import",
    )

start = route.find("            RouteSubTab.GENERATOR -> {")
end_marker = "        }\n    }\n}\n\n@Composable\nprivate fun RouteSubTabs"
end = route.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("VPNSL 1.0.8 keyboard fix: generator branch not found")

branch = '''            RouteSubTab.GENERATOR -> {
                // Stable single layout: the same TextField stays composed while
                // the keyboard opens. Android adjustResize moves the available
                // window once; there is no LazyColumn auto-scroll and no IME padding.
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .padding(top = 12.dp, bottom = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text(
                        "Генератор BAT по имени сайта",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        "Введите домен или URL. VPNSL найдёт текущие IPv4-адреса (A-записи) и сформирует отдельный .bat с маршрутами /32.",
                        style = MaterialTheme.typography.bodySmall,
                    )

                    Spacer(modifier = Modifier.weight(1f))

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
                }
            }
'''

route = route[:start] + branch + route[end:]
write(route_rel, route)

checks = {
    "no imePadding": "imePadding" not in read(route_rel),
    "no IME conditional layout": "imeVisible" not in read(route_rel),
    "generator stable column": "Stable single layout" in read(route_rel),
    "generator no LazyColumn auto-scroll": "RouteSubTab.GENERATOR -> {\n                // Stable single layout" in read(route_rel),
    "field kept low": "Spacer(modifier = Modifier.weight(1f))" in read(route_rel),
    "generator DNS intact": "InetAddress.getAllByName(host)" in read(route_rel),
    "file import intact": "store.importProfile(name, text, RouteTarget.WDTTSL)" in read(route_rel),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.8 keyboard fix verification failed: " + ", ".join(failed))

print("VPNSL 1.0.8: single adjustResize movement; generator focus preserved")
