// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative routing UI by Sazhaev-IA.

package com.csqtt.client.ui

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.csqtt.client.TunnelManager
import com.csqtt.client.routing.Ipv4Cidr
import com.csqtt.client.routing.RouteBatFormatter
import com.csqtt.client.routing.RouteListProfile
import com.csqtt.client.routing.RouteListStore
import com.csqtt.client.routing.RouteTarget
import java.net.IDN
import java.net.Inet4Address
import java.net.InetAddress
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private enum class RouteSubTab { ROUTES, GENERATOR }

@Composable
fun RouteListsSection(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val store = remember { RouteListStore(context) }
    var profiles by remember { mutableStateOf(store.loadProfiles()) }
    var selectedTab by remember { mutableStateOf(RouteSubTab.ROUTES) }
    var routeStatus by remember { mutableStateOf<String?>(null) }
    var saveStatus by remember { mutableStateOf<String?>(null) }
    var routeLabel by remember { mutableStateOf("") }
    var routeInput by remember { mutableStateOf("") }
    var manualTarget by remember { mutableStateOf(RouteTarget.WDTTSL) }
    var showManualTargetDialog by remember { mutableStateOf(false) }
    var targetDialogProfileId by remember { mutableStateOf<String?>(null) }

    var generatorInput by remember { mutableStateOf("") }
    var generatedHost by remember { mutableStateOf<String?>(null) }
    var generatedIpv4 by remember { mutableStateOf<List<String>>(emptyList()) }
    var generatorStatus by remember { mutableStateOf<String?>(null) }
    var resolving by remember { mutableStateOf(false) }

    var pendingLegacySave by remember { mutableStateOf<Pair<String, String>?>(null) }
    val legacySaveLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/plain"),
    ) { uri: Uri? ->
        val pending = pendingLegacySave
        pendingLegacySave = null
        if (uri == null || pending == null) return@rememberLauncherForActivityResult
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    context.contentResolver.openOutputStream(uri, "w")?.use { stream ->
                        stream.write(pending.second.toByteArray(StandardCharsets.UTF_8))
                    } ?: error("Не удалось открыть файл для записи")
                }
            }
            saveStatus = if (result.isSuccess) {
                "Файл сохранён: ${pending.first}"
            } else {
                "Ошибка сохранения: ${result.exceptionOrNull()?.message ?: "неизвестная ошибка"}"
            }
        }
    }

    fun persist(next: List<RouteListProfile>) {
        profiles = next
        store.saveProfiles(next)
        TunnelManager.reloadVpn()
    }

    fun saveBat(fileName: String, text: String) {
        saveStatus = "Сохранение $fileName…"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    saveTextToDownloads(context, fileName, text)
                }
                saveStatus = result.fold(
                    onSuccess = { path -> "Сохранено: $path" },
                    onFailure = { error -> "Ошибка сохранения: ${error.message ?: error.javaClass.simpleName}" },
                )
            }
        } else {
            pendingLegacySave = fileName to text
            legacySaveLauncher.launch(fileName)
        }
    }

    fun addManualRoute() {
        val label = routeLabel.trim()
        val raw = routeInput.trim()
        if (label.isBlank()) {
            routeStatus = "Введите подпись ресурса"
            return
        }
        if (raw.isBlank()) {
            routeStatus = "Введите IPv4-адрес или подсеть"
            return
        }

        val normalizedInput = if ('/' in raw) raw else "$raw/32"
        val route = Ipv4Cidr.parse(normalizedInput)
        if (route == null) {
            routeStatus = "Некорректный IPv4/CIDR: $raw"
            return
        }

        val canonicalRoute = route.toString()
        val profile = RouteListProfile(
            id = UUID.randomUUID().toString(),
            name = label,
            enabled = true,
            target = manualTarget,
            routes = listOf(route),
        )
        persist(listOf(profile) + profiles)
        routeLabel = ""
        routeInput = ""
        routeStatus = "Добавлен $label: $canonicalRoute → ${targetName(manualTarget)}"
    }

    val picker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        val name = displayName(context.contentResolver.query(uri, null, null, null, null), uri)
        val bytes = runCatching {
            context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
        }.getOrNull()
        if (bytes == null) {
            routeStatus = "Не удалось прочитать файл"
            return@rememberLauncherForActivityResult
        }
        val text = decodeRouteFile(bytes)
        val result = store.importProfile(name, text, RouteTarget.WDTTSL)
        profiles = store.loadProfiles()
        routeStatus = if (result.routes.isEmpty()) {
            "Маршруты не найдены"
        } else {
            buildString {
                append("Импортировано: ${result.routes.size}")
                if (result.rejectedLines.isNotEmpty()) {
                    append("; пропущено строк: ${result.rejectedLines.size}")
                }
            }
        }
        if (result.routes.isNotEmpty()) TunnelManager.reloadVpn()
    }

    if (showManualTargetDialog) {
        NetworkTargetDialog(
            selected = manualTarget,
            onDismiss = { showManualTargetDialog = false },
            onSelected = { target ->
                manualTarget = target
                showManualTargetDialog = false
            },
        )
    }

    profiles.firstOrNull { it.id == targetDialogProfileId }?.let { profile ->
        NetworkTargetDialog(
            selected = profile.target,
            onDismiss = { targetDialogProfileId = null },
            onSelected = { target ->
                persist(profiles.map {
                    if (it.id == profile.id) it.copy(target = target) else it
                })
                targetDialogProfileId = null
            },
        )
    }

    Column(modifier = modifier.fillMaxSize()) {
        RouteSubTabs(
            selected = selectedTab,
            onSelected = { selectedTab = it },
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

        when (selectedTab) {
            RouteSubTab.ROUTES -> {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentPadding = PaddingValues(bottom = 24.dp),
                ) {
                    item(key = "manual-input") {
                        Column(
                            modifier = Modifier.padding(top = 10.dp, bottom = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            OutlinedTextField(
                                value = routeLabel,
                                onValueChange = { routeLabel = it },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text("Подпись ресурса") },
                                placeholder = { Text("Например: ChatGPT") },
                            )

                            OutlinedTextField(
                                value = routeInput,
                                onValueChange = { routeInput = it },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text("IP-адрес или подсеть") },
                                placeholder = { Text("104.18.29.234 или 104.18.29.0/24") },
                            )

                            Text(
                                text = "Сеть для нового маршрута: ${targetName(manualTarget)}",
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .clickable { showManualTargetDialog = true }
                                    .padding(vertical = 6.dp),
                            )

                            Button(
                                onClick = ::addManualRoute,
                                enabled = routeInput.isNotBlank() && routeLabel.isNotBlank(),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Icon(Icons.Outlined.Add, contentDescription = null)
                                Text(" Добавить маршрут")
                            }

                            Button(
                                onClick = { picker.launch(arrayOf("*/*")) },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Icon(Icons.Outlined.UploadFile, contentDescription = null)
                                Text(" Загрузить список маршрутов")
                            }

                            Button(
                                onClick = {
                                    val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
                                    saveBat(
                                        "VPNSL-routes-$stamp.bat",
                                        RouteBatFormatter.buildAllRoutesFile(profiles),
                                    )
                                },
                                enabled = profiles.isNotEmpty(),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text("Выгрузить все маршруты (.bat)")
                            }

                            Text(
                                "Экспорт включает все сохранённые маршруты в один BAT, включая выключенные. Состояние и выбранная сеть записываются в REM-комментарии; сами route add остаются совместимыми с импортом VPNSL.",
                                style = MaterialTheme.typography.bodySmall,
                            )

                            routeStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                            saveStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }

                            if (profiles.isEmpty()) {
                                Text(
                                    "Маршрутов пока нет. Добавьте IPv4/CIDR вручную или загрузите .bat, .txt/.list.",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            }
                        }
                    }

                    itemsIndexed(
                        items = profiles,
                        key = { _, profile -> profile.id },
                        contentType = { _, _ -> "route-profile" },
                    ) { index, profile ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = profile.name,
                                        style = MaterialTheme.typography.titleSmall,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    val singleRoute = profile.routes.singleOrNull()?.toString()
                                    Text(
                                        text = singleRoute ?: routeCountText(profile.routes.size),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Text(
                                        text = "Сеть: ${targetName(profile.target)}",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier
                                            .clickable { targetDialogProfileId = profile.id }
                                            .padding(vertical = 4.dp),
                                    )
                                }

                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    Text(
                                        if (profile.enabled) "Вкл." else "Выкл.",
                                        style = MaterialTheme.typography.labelMedium,
                                    )
                                    Switch(
                                        checked = profile.enabled,
                                        onCheckedChange = { enabled ->
                                            persist(profiles.map {
                                                if (it.id == profile.id) it.copy(enabled = enabled) else it
                                            })
                                        },
                                    )
                                    IconButton(onClick = {
                                        if (targetDialogProfileId == profile.id) targetDialogProfileId = null
                                        store.remove(profile.id)
                                        profiles = store.loadProfiles()
                                        TunnelManager.reloadVpn()
                                    }) {
                                        Icon(Icons.Outlined.Delete, contentDescription = "Удалить")
                                    }
                                }
                            }

                            if (index != profiles.lastIndex) {
                                HorizontalDivider(
                                    modifier = Modifier.padding(top = 4.dp),
                                    color = MaterialTheme.colorScheme.outlineVariant,
                                )
                            }
                        }
                    }
                }
            }

            RouteSubTab.GENERATOR -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .imePadding(),
                    contentPadding = PaddingValues(top = 12.dp, bottom = 96.dp),
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
    }
}

@Composable
private fun RouteSubTabs(
    selected: RouteSubTab,
    onSelected: (RouteSubTab) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceEvenly,
    ) {
        TextButton(
            onClick = { onSelected(RouteSubTab.ROUTES) },
            modifier = Modifier.weight(1f),
        ) {
            Text(
                "Маршруты",
                fontWeight = if (selected == RouteSubTab.ROUTES) FontWeight.Bold else FontWeight.Normal,
                color = if (selected == RouteSubTab.ROUTES) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(
            onClick = { onSelected(RouteSubTab.GENERATOR) },
            modifier = Modifier.weight(1f),
        ) {
            Text(
                "Генератор",
                fontWeight = if (selected == RouteSubTab.GENERATOR) FontWeight.Bold else FontWeight.Normal,
                color = if (selected == RouteSubTab.GENERATOR) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun NetworkTargetDialog(
    selected: RouteTarget,
    onSelected: (RouteTarget) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Выберите сеть") },
        text = {
            Column {
                networkOptions().forEach { (target, label) ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelected(target) }
                            .padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(
                            selected = selected == target,
                            onClick = { onSelected(target) },
                        )
                        Text(
                            text = label,
                            modifier = Modifier.padding(start = 8.dp),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("Отмена")
            }
        },
    )
}

private fun networkOptions(): List<Pair<RouteTarget, String>> = listOf(
    RouteTarget.MOBILE to "Мобильная сеть",
    RouteTarget.WDTTSL to "VPNSL",
)

private fun routeCountText(count: Int): String = when {
    count % 10 == 1 && count % 100 != 11 -> "$count маршрут"
    count % 10 in 2..4 && count % 100 !in 12..14 -> "$count маршрута"
    else -> "$count маршрутов"
}

private fun targetName(target: RouteTarget): String = when (target) {
    RouteTarget.MOBILE -> "Мобильная сеть"
    RouteTarget.WDTTSL -> "VPNSL"
}

private fun normalizeHost(rawInput: String): String? {
    val raw = rawInput.trim()
    if (raw.isBlank()) return null
    val uriText = if (raw.contains("://")) raw else "https://$raw"
    val host = runCatching { URI(uriText).host }.getOrNull()?.trim()?.trimEnd('.') ?: return null
    if (host.isBlank()) return null
    return runCatching { IDN.toASCII(host.lowercase(Locale.ROOT)) }.getOrNull()
        ?.takeIf { it.isNotBlank() && '.' in it }
}

private fun safeFileStem(host: String): String = host
    .replace(Regex("[^A-Za-z0-9._-]"), "_")
    .trim('_')
    .ifBlank { "routes" }

private fun saveTextToDownloads(context: Context, fileName: String, text: String): Result<String> = runCatching {
    require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
    val resolver = context.contentResolver
    val values = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "text/plain")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        put(MediaStore.MediaColumns.IS_PENDING, 1)
    }
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        ?: error("Android не создал файл в Загрузках")
    try {
        resolver.openOutputStream(uri, "w")?.use { stream ->
            stream.write(text.toByteArray(StandardCharsets.UTF_8))
        } ?: error("Не удалось открыть файл в Загрузках")
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        "Download/$fileName"
    } catch (error: Throwable) {
        runCatching { resolver.delete(uri, null, null) }
        throw error
    }
}

private fun displayName(cursor: Cursor?, uri: Uri): String {
    cursor?.use {
        val index = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0 && it.moveToFirst()) return it.getString(index)
    }
    return uri.lastPathSegment ?: "routes.list"
}

private fun decodeRouteFile(bytes: ByteArray): String {
    val utf8 = runCatching {
        StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
    }.getOrNull()
    return utf8 ?: bytes.toString(Charset.forName("windows-1251"))
}
