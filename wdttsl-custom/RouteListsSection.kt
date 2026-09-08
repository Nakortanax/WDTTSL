// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative routing UI by Sazhaev-IA.

package com.csqtt.client.ui

import android.database.Cursor
import android.net.Uri
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.csqtt.client.TunnelManager
import com.csqtt.client.routing.Ipv4Cidr
import com.csqtt.client.routing.RouteListProfile
import com.csqtt.client.routing.RouteListStore
import com.csqtt.client.routing.RouteTarget
import java.nio.ByteBuffer
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.UUID

@Composable
fun RouteListsSection(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val store = remember { RouteListStore(context) }
    var profiles by remember { mutableStateOf(store.loadProfiles()) }
    var status by remember { mutableStateOf<String?>(null) }
    var routeInput by remember { mutableStateOf("") }
    var manualTarget by remember { mutableStateOf(RouteTarget.WDTTSL) }
    var showManualTargetDialog by remember { mutableStateOf(false) }
    var targetDialogProfileId by remember { mutableStateOf<String?>(null) }

    fun persist(next: List<RouteListProfile>) {
        profiles = next
        store.saveProfiles(next)
        TunnelManager.reloadVpn()
    }

    fun addManualRoute() {
        val raw = routeInput.trim()
        if (raw.isBlank()) {
            status = "Введите IPv4-адрес или подсеть"
            return
        }

        val normalizedInput = if ('/' in raw) raw else "$raw/32"
        val route = Ipv4Cidr.parse(normalizedInput)
        if (route == null) {
            status = "Некорректный IPv4/CIDR: $raw"
            return
        }

        val canonicalRoute = route.toString()
        val profile = RouteListProfile(
            id = UUID.randomUUID().toString(),
            name = canonicalRoute,
            enabled = true,
            target = manualTarget,
            routes = listOf(route),
        )
        persist(listOf(profile) + profiles)
        routeInput = ""
        status = "Добавлен $canonicalRoute → ${targetName(manualTarget)}"
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
            status = "Не удалось прочитать файл"
            return@rememberLauncherForActivityResult
        }
        val text = decodeRouteFile(bytes)
        val result = store.importProfile(name, text, RouteTarget.WDTTSL)
        profiles = store.loadProfiles()
        status = if (result.routes.isEmpty()) {
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

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item(key = "manual-input") {
            Column(
                modifier = Modifier.padding(bottom = 12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
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
                    enabled = routeInput.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Outlined.Add, contentDescription = null)
                    Text(" Добавить маршрут")
                }

                Text(
                    "Обычный IPv4 автоматически становится /32. DNS и доменные имена не используются. Нажмите на строку «Сеть», чтобы выбрать Мобильную сеть или VPNSL. Каждый маршрут можно отключить без удаления.",
                    style = MaterialTheme.typography.bodySmall,
                )

                Button(
                    onClick = { picker.launch(arrayOf("*/*")) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Outlined.UploadFile, contentDescription = null)
                    Text(" Загрузить список маршрутов")
                }

                status?.let { Text(it, style = MaterialTheme.typography.bodySmall) }

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
                        Text(
                            text = routeCountText(profile.routes.size),
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
