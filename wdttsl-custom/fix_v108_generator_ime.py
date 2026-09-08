#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
rel = "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
path = ROOT / rel
text = path.read_text(encoding="utf-8")

# Remove the previous double IME compensation. Android already resizes the window.
text = text.replace("import androidx.compose.foundation.layout.imePadding\n", "")

# Imports needed for a dedicated compact keyboard-open layout.
anchor = "import androidx.compose.foundation.layout.Row\n"
imports = (
    "import androidx.compose.foundation.layout.Row\n"
    "import androidx.compose.foundation.layout.Spacer\n"
    "import androidx.compose.foundation.layout.WindowInsets\n"
    "import androidx.compose.foundation.layout.height\n"
    "import androidx.compose.foundation.layout.ime\n"
)
if "import androidx.compose.foundation.layout.WindowInsets\n" not in text:
    if anchor not in text:
        raise SystemExit("missing layout import anchor")
    text = text.replace(anchor, imports, 1)

if "import androidx.compose.ui.platform.LocalDensity\n" not in text:
    anchor2 = "import androidx.compose.ui.platform.LocalContext\n"
    if anchor2 not in text:
        raise SystemExit("missing LocalContext import anchor")
    text = text.replace(anchor2, anchor2 + "import androidx.compose.ui.platform.LocalDensity\n", 1)

# Detect IME once per recomposition. No imePadding: only use the signal to switch layouts.
anchor3 = "    val scope = rememberCoroutineScope()\n"
if "val imeVisible = WindowInsets.ime.getBottom(LocalDensity.current) > 0" not in text:
    if anchor3 not in text:
        raise SystemExit("missing scope anchor")
    text = text.replace(
        anchor3,
        anchor3 + "    val imeVisible = WindowInsets.ime.getBottom(LocalDensity.current) > 0\n",
        1,
    )

start = text.find("            RouteSubTab.GENERATOR -> {")
end_marker = "        }\n    }\n}\n\n@Composable\nprivate fun RouteSubTabs"
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("generator branch anchors not found")

branch = '''            RouteSubTab.GENERATOR -> {
                if (imeVisible) {
                    // Keyboard-open mode: do not let LazyColumn auto-scroll the focused
                    // field toward the top. Keep only the input controls and anchor them
                    // low in the resized viewport, directly above the keyboard.
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .padding(top = 6.dp, bottom = 8.dp),
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
                        Spacer(modifier = Modifier.height(14.dp))
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

text = text[:start] + branch + text[end:]

checks = [
    "val imeVisible = WindowInsets.ime.getBottom(LocalDensity.current) > 0",
    "Spacer(modifier = Modifier.weight(1f))",
    "if (imeVisible)",
]
for marker in checks:
    if marker not in text:
        raise SystemExit(f"verification failed: {marker}")
if "imePadding" in text:
    raise SystemExit("old imePadding still present")

path.write_text(text, encoding="utf-8")
print("VPNSL 1.0.8 generator: compact bottom-anchored IME layout applied")
