// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// CSQTTS derivative routing UI by Sazhaev-IA.

package com.csqtt.client.ui

import android.database.Cursor
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import java.net.IDN
import java.net.Inet4Address
import java.net.InetAddress
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun RouteListsSection(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val store = remember { RouteListStore(context) }
    val scope = rememberCoroutineScope()
    var profiles by remember { mutableStateOf(store.loadProfiles()) }
    var status by remember { mutableStateOf<String?>(null) }
    var websiteInput by remember { mutableStateOf("") }
    var websiteBusy by remember { mutableStateOf(false) }

    fun persist(next: List<RouteListProfile>) {
        profiles = next
        store.saveProfiles(next)
        TunnelManager.reloadVpn()
    }

    fun addWebsite() {
        if (websiteBusy) return
        val raw = websiteInput.trim()
        if (raw.isBlank()) {
            status = "Введите адрес сайта"
            return
        }
        websiteBusy = true
        scope.launch {
            val direct = Ipv4Cidr.parse(raw)
            val host = if (direct == null) normalizeWebsiteHost(raw) else null
            val routes = when {
                direct != null -> listOf(direct)
                host == null -> emptyList()
                else -> resolveWebsiteIpv4(host)
            }
            if (routes.isEmpty()) {
                status = if (host == null) {
                    "Не удалось распознать адрес сайта"
                } else {
                    "Для $host не найдены IPv4-адреса"
                }
                websiteBusy = false
                return@launch
            }

            val profileName = host ?: raw
            val next = profiles + RouteListProfile(
                id = UUID.randomUUID().toString(),
                name = profileName,
                enabled = true,
                target = RouteTarget.WDTTSL,
                routes = routes.distinct(),
            )
            persist(next)
            websiteInput = ""
            status = if (host == null) {
                "Маршрут $profileName добавлен"
            } else {
                "Сайт $host добавлен: ${routes.size} IPv4"
            }
            websiteBusy = false
        }
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

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        OutlinedTextField(
            value = websiteInput,
            onValueChange = { websiteInput = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            label = { Text("Добавить сайт вручную") },
            placeholder = { Text("example.com или https://example.com") },
            enabled = !websiteBusy,
        )

        Button(
            onClick = ::addWebsite,
            enabled = !websiteBusy && websiteInput.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Outlined.Add, contentDescription = null)
            Text(if (websiteBusy) " Определяем адрес..." else " Добавить сайт")
        }

        Text(
            "При добавлении сайта CSQTTS определяет его текущие IPv4-адреса и создаёт для них маршруты. Для сайтов с CDN адреса со временем могут измениться — тогда сайт нужно добавить заново.",
            style = MaterialTheme.typography.bodySmall,
        )

        Button(
            onClick = { picker.launch(arrayOf("*/*")) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Outlined.UploadFile, contentDescription = null)
            Text(" Загрузить список маршрутов")
        }

        status?.let {
            Text(it, style = MaterialTheme.typography.bodySmall)
        }

        if (profiles.isEmpty()) {
            Text(
                "Добавьте сайт вручную или загрузите .bat, .txt/.list. По умолчанию новый профиль направляется через CSQTTS.",
                style = MaterialTheme.typography.bodyMedium,
            )
        }

        profiles.forEach { profile ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = profile.enabled,
                            onCheckedChange = { enabled ->
                                persist(profiles.map {
                                    if (it.id == profile.id) it.copy(enabled = enabled) else it
                                })
                            },
                        )
                        Column(modifier = Modifier.weight(1f)) {
                            Text(profile.name, style = MaterialTheme.typography.titleSmall)
                            Text(
                                "${profile.routes.size} маршрутов",
                                style = MaterialTheme.typography.bodySmall,
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

                    CsqttSegmentedControl(
                        options = listOf(
                            RouteTarget.MOBILE to "Мобильная сеть",
                            RouteTarget.WDTTSL to "CSQTTS",
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

private fun normalizeWebsiteHost(raw: String): String? = runCatching {
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) return@runCatching null
    val uri = if (trimmed.contains("://")) URI(trimmed) else URI("https://$trimmed")
    val host = uri.host?.trim()?.trimEnd('.')?.lowercase(Locale.ROOT) ?: return@runCatching null
    if (host.isEmpty() || host.length > 253) return@runCatching null
    IDN.toASCII(host).lowercase(Locale.ROOT)
}.getOrNull()

private suspend fun resolveWebsiteIpv4(host: String): List<Ipv4Cidr> = withContext(Dispatchers.IO) {
    runCatching {
        InetAddress.getAllByName(host)
            .asSequence()
            .filterIsInstance<Inet4Address>()
            .mapNotNull { address -> Ipv4Cidr.parse("${address.hostAddress}/32") }
            .distinct()
            .toList()
    }.getOrDefault(emptyList())
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
