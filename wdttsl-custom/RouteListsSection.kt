// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative routing UI by Sazhaev-IA.

package com.csqtt.client.ui

import android.database.Cursor
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.csqtt.client.TunnelManager
import com.csqtt.client.routing.Ipv4Cidr
import com.csqtt.client.routing.RouteListProfile
import com.csqtt.client.routing.RouteListStore
import com.csqtt.client.routing.RouteTarget
import com.csqtt.client.ui.components.CsqttSegmentedControl
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

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp),
    ) {
        item(key = "manual-input") {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = routeInput,
                    onValueChange = { routeInput = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("IP-адрес или подсеть") },
                    placeholder = { Text("104.18.29.234 или 104.18.29.0/24") },
                )

                Text("Сеть для нового маршрута", style = MaterialTheme.typography.labelLarge)
                CsqttSegmentedControl(
                    options = listOf(
                        RouteTarget.MOBILE to "Мобильная сеть",
                        RouteTarget.WDTTSL to "VPNSL",
                    ),
                    selected = manualTarget,
                    onSelected = { manualTarget = it },
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
                    "Обычный IPv4 автоматически становится /32. DNS и доменные имена не используются. Каждый маршрут можно отключить, не удаляя из списка, и отдельно выбрать для него Мобильную сеть или VPNSL.",
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

        items(
            items = profiles,
            key = { it.id },
            contentType = { "route-profile" },
        ) { profile ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(profile.name, style = MaterialTheme.typography.titleSmall)
                            Text(
                                if (profile.routes.size == 1) "1 маршрут" else "${profile.routes.size} маршрутов",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            Text(
                                "Сеть: ${targetName(profile.target)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                        IconButton(onClick = {
                            store.remove(profile.id)
                            profiles = store.loadProfiles()
                            TunnelManager.reloadVpn()
                        }) {
                            Icon(Icons.Outlined.Delete, contentDescription = "Удалить")
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(if (profile.enabled) "Активен" else "Выключен", style = MaterialTheme.typography.labelLarge)
                        Switch(
                            checked = profile.enabled,
                            onCheckedChange = { enabled ->
                                persist(profiles.map {
                                    if (it.id == profile.id) it.copy(enabled = enabled) else it
                                })
                            },
                        )
                    }

                    CsqttSegmentedControl(
                        options = listOf(
                            RouteTarget.MOBILE to "Мобильная сеть",
                            RouteTarget.WDTTSL to "VPNSL",
                        ),
                        selected = profile.target,
                        onSelected = { target ->
                            persist(profiles.map {
                                if (it.id == profile.id) it.copy(target = target) else it
                            })
                        },
                    )
                }
            }
        }
    }
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
