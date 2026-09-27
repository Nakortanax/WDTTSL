// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative routing UI by Sazhaev-IA.
// VPNSL 1.0.9: full tunnel by default with optional application/IP routing.

package com.csqtt.client.ui

import android.content.pm.PackageManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.core.graphics.drawable.toBitmap
import com.csqtt.client.R
import com.csqtt.client.SettingsStore
import com.csqtt.client.TunnelManager
import com.csqtt.client.routing.RouteListStore
import com.csqtt.client.routing.RoutingSourceMode
import com.csqtt.client.ui.components.CsqttEmptyState
import com.csqtt.client.ui.components.CsqttLoadingState
import com.csqtt.client.ui.components.CsqttScreen
import com.csqtt.client.ui.components.CsqttSegmentedControl
import com.csqtt.client.ui.components.CsqttSettingRow
import com.csqtt.client.ui.design.CsqttShapes
import com.csqtt.client.ui.design.CsqttSizes
import com.csqtt.client.ui.design.CsqttSpacing
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private object AppCacheV109 {
    @Volatile
    var cachedList: List<AppItem>? = null
}

@Composable
fun ExceptionsTab(
    settingsStore: SettingsStore,
    savedExcluded: String,
    showSystemApps: Boolean,
    isWhitelist: Boolean,
) {
    val context = LocalContext.current.applicationContext
    val focusManager = LocalFocusManager.current
    val scope = rememberCoroutineScope()
    val persistedSelection = remember(savedExcluded) {
        savedExcluded.split(',').filter(String::isNotBlank).toSet()
    }
    var selectedPackages by remember { mutableStateOf(persistedSelection) }
    var lastSavedSelection by remember { mutableStateOf(persistedSelection) }
    var saveJob by remember { mutableStateOf<Job?>(null) }

    LaunchedEffect(persistedSelection) {
        if (persistedSelection != lastSavedSelection) selectedPackages = persistedSelection
        lastSavedSelection = persistedSelection
    }

    var appsList by remember { mutableStateOf(AppCacheV109.cachedList.orEmpty()) }
    var isLoading by remember { mutableStateOf(AppCacheV109.cachedList == null) }
    var isMigrationReady by rememberSaveable { mutableStateOf(false) }
    var searchQuery by rememberSaveable { mutableStateOf("") }
    val routeListStore = remember { RouteListStore(context) }
    var routingSourceMode by remember { mutableStateOf(routeListStore.routingSourceMode()) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            settingsStore.migrateLegacyWhitelistMode()
            settingsStore.saveIsWhitelist(true)
        }
        isMigrationReady = true

        AppCacheV109.cachedList?.let {
            appsList = it
            isLoading = false
            return@LaunchedEffect
        }

        isLoading = true
        val loadedApps = withContext(Dispatchers.IO) {
            val packageManager = context.packageManager
            packageManager
                .getInstalledApplications(PackageManager.GET_META_DATA)
                .asSequence()
                .filter { app ->
                    app.packageName != context.packageName &&
                        !app.packageName.contains("vkontakte") &&
                        !app.packageName.contains("vk.calls")
                }
                .map { app ->
                    AppItem(
                        name = app.loadLabel(packageManager).toString(),
                        packageName = app.packageName,
                        icon = runCatching { app.loadIcon(packageManager).toBitmap().asImageBitmap() }.getOrNull(),
                        isSystem = (app.flags and android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0,
                    )
                }
                .sortedBy { it.name.lowercase() }
                .toList()
        }
        AppCacheV109.cachedList = loadedApps
        appsList = loadedApps
        isLoading = false
    }

    val filteredApps = remember(appsList, showSystemApps, searchQuery) {
        val visibleApps = if (showSystemApps) {
            appsList
        } else {
            appsList.filter {
                !it.isSystem || it.packageName == "com.google.android.youtube" || it.packageName == "com.android.vending"
            }
        }
        if (searchQuery.isBlank()) visibleApps else visibleApps.filter {
            it.name.contains(searchQuery, ignoreCase = true) ||
                it.packageName.contains(searchQuery, ignoreCase = true)
        }
    }
    val listState = rememberLazyListState()

    fun persistSelection(selection: Set<String>) {
        lastSavedSelection = selection
        saveJob?.cancel()
        saveJob = scope.launch {
            delay(250)
            settingsStore.saveExcludedApps(selection.sorted().joinToString(","))
            settingsStore.saveIsWhitelist(true)
            TunnelManager.reloadVpn()
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            saveJob?.cancel()
            val pending = selectedPackages
            if (pending != persistedSelection) {
                CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
                    settingsStore.saveExcludedApps(pending.sorted().joinToString(","))
                    settingsStore.saveIsWhitelist(true)
                    TunnelManager.reloadVpn()
                }
            }
        }
    }

    CsqttScreen {
        PromoRoutingHeader(
            mode = routingSourceMode,
            selectedApps = selectedPackages.size,
        )

        AppSectionCard(
            contentPadding = PaddingValues(horizontal = CsqttSpacing.Md, vertical = CsqttSpacing.Sm),
            verticalArrangement = Arrangement.spacedBy(CsqttSpacing.Sm),
        ) {
            CsqttSegmentedControl(
                options = listOf(
                    RoutingSourceMode.FULL_TUNNEL to "Весь трафик",
                    RoutingSourceMode.APPLICATIONS to "Приложения",
                    RoutingSourceMode.ROUTE_LISTS to "IP / файлы",
                ),
                selected = routingSourceMode,
                enabled = isMigrationReady,
                onSelected = { mode ->
                    if (mode == routingSourceMode) return@CsqttSegmentedControl
                    routingSourceMode = mode
                    routeListStore.saveRoutingSourceMode(mode)
                    scope.launch {
                        settingsStore.saveIsWhitelist(true)
                        delay(150)
                        TunnelManager.reloadVpn()
                    }
                },
            )

            if (routingSourceMode == RoutingSourceMode.APPLICATIONS) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                CsqttSettingRow(
                    title = stringResource(R.string.exceptions_system_apps),
                    checked = showSystemApps,
                    onCheckedChange = { enabled ->
                        scope.launch { settingsStore.saveShowSystemApps(enabled) }
                    },
                )
            }
        }

        when (routingSourceMode) {
            RoutingSourceMode.FULL_TUNNEL -> {
                AppSectionCard(
                    contentPadding = PaddingValues(horizontal = CsqttSpacing.Md, vertical = CsqttSpacing.Md),
                    verticalArrangement = Arrangement.spacedBy(CsqttSpacing.Sm),
                ) {
                    Text(
                        text = "Весь трафик через VPNSL",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = "Весь IPv4-трафик телефона направляется через домашний VPNSL-сервер. Дальнейший выбор маршрута выполняет Keenetic: напрямую через провайдера или через настроенный на роутере VPN.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "Этот режим используется по умолчанию. Для выборочной работы переключитесь на «Приложения» или «IP / файлы».",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }

            RoutingSourceMode.ROUTE_LISTS -> {
                RouteListsSection(Modifier.fillMaxWidth().weight(1f))
            }

            RoutingSourceMode.APPLICATIONS -> {
                OutlinedTextField(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    label = {
                        Text(
                            stringResource(R.string.exceptions_search_label),
                            maxLines = 1,
                            softWrap = false,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    placeholder = {
                        Text(
                            stringResource(R.string.exceptions_search_placeholder),
                            maxLines = 1,
                            softWrap = false,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { focusManager.clearFocus() }),
                    shape = CsqttShapes.Control,
                    modifier = Modifier.fillMaxWidth(),
                )

                Text(
                    text = stringResource(R.string.exceptions_selected_count, selectedPackages.size),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                when {
                    !isMigrationReady || isLoading -> {
                        Box(modifier = Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                            CsqttLoadingState(label = stringResource(R.string.exceptions_loading))
                        }
                    }

                    filteredApps.isEmpty() -> {
                        Box(modifier = Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                            CsqttEmptyState(
                                title = stringResource(R.string.exceptions_empty_title),
                                description = stringResource(R.string.exceptions_empty_description),
                                icon = Icons.Outlined.Apps,
                            )
                        }
                    }

                    else -> {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxWidth().weight(1f),
                            contentPadding = PaddingValues(bottom = CsqttSizes.ScreenBottomPadding),
                            verticalArrangement = Arrangement.spacedBy(CsqttSpacing.Xs),
                        ) {
                            items(
                                items = filteredApps,
                                key = { it.packageName },
                                contentType = { "application" },
                            ) { app ->
                                val isSelected = app.packageName in selectedPackages
                                AppRow(
                                    app = app,
                                    isSelected = isSelected,
                                    onClick = {
                                        val newSelection = if (isSelected) {
                                            selectedPackages - app.packageName
                                        } else {
                                            selectedPackages + app.packageName
                                        }
                                        selectedPackages = newSelection
                                        persistSelection(newSelection)
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
