// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative routing UI by Sazhaev-IA.

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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.core.graphics.drawable.toBitmap
import com.csqtt.client.R
import com.csqtt.client.SettingsStore
import com.csqtt.client.TunnelManager
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

private object AppCache {
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

    var appsList by remember { mutableStateOf(AppCache.cachedList.orEmpty()) }
    var isLoading by remember { mutableStateOf(AppCache.cachedList == null) }
    var isMigrationReady by rememberSaveable { mutableStateOf(false) }
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var editorMode by rememberSaveable { mutableStateOf(RoutingSourceMode.APPLICATIONS) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            settingsStore.migrateLegacyWhitelistMode()
            settingsStore.saveIsWhitelist(true)
        }
        isMigrationReady = true

        AppCache.cachedList?.let {
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
        AppCache.cachedList = loadedApps
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
        AppSectionCard(
            contentPadding = PaddingValues(horizontal = CsqttSpacing.Md, vertical = CsqttSpacing.Sm),
            verticalArrangement = Arrangement.spacedBy(CsqttSpacing.Sm),
        ) {
            Text(
                text = "Приложения и маршруты работают одновременно. Переключатель ниже меняет только редактор.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            CsqttSegmentedControl(
                options = listOf(
                    RoutingSourceMode.APPLICATIONS to "Приложения",
                    RoutingSourceMode.ROUTE_LISTS to "Маршруты",
                ),
                selected = editorMode,
                enabled = isMigrationReady,
                onSelected = { editorMode = it },
            )

            if (editorMode == RoutingSourceMode.APPLICATIONS) {
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

        if (editorMode == RoutingSourceMode.ROUTE_LISTS) {
            RouteListsSection(Modifier.fillMaxWidth().weight(1f))
        } else {
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
                                    val newSelection = if (isSelected) selectedPackages - app.packageName else selectedPackages + app.packageName
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
