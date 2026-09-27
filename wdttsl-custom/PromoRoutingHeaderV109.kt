// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL promo-style routing header by Sazhaev-IA.
// VPNSL 1.0.9: full tunnel is the primary mode.

package com.csqtt.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Route
import androidx.compose.material.icons.outlined.Smartphone
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.csqtt.client.routing.RoutingSourceMode

@Composable
fun PromoRoutingHeader(
    mode: RoutingSourceMode,
    selectedApps: Int,
) {
    val modeText = when (mode) {
        RoutingSourceMode.FULL_TUNNEL -> "Весь трафик"
        RoutingSourceMode.APPLICATIONS -> "Приложения"
        RoutingSourceMode.ROUTE_LISTS -> "IP / файлы"
    }
    val statusText = when (mode) {
        RoutingSourceMode.FULL_TUNNEL ->
            "Весь IPv4-трафик идёт домой через VPNSL; дальнейшую маршрутизацию выполняет Keenetic"
        RoutingSourceMode.APPLICATIONS ->
            "Через VPNSL идут только выбранные приложения: $selectedApps"
        RoutingSourceMode.ROUTE_LISTS ->
            "Маршруты из файлов и IP/CIDR применяются глобально"
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier
                .background(
                    Brush.linearGradient(
                        listOf(
                            MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
                            MaterialTheme.colorScheme.surface,
                        )
                    )
                )
                .padding(horizontal = 18.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "VPNSL",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Black,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Маршрутизация Android",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PromoChipV109(
                    icon = { Icon(Icons.Outlined.Smartphone, null, Modifier.size(16.dp)) },
                    text = "Android",
                    modifier = Modifier.weight(1f),
                )
                PromoChipV109(
                    icon = { Icon(Icons.Outlined.Route, null, Modifier.size(16.dp)) },
                    text = modeText,
                    modifier = Modifier.weight(1f),
                )
            }
            Text(
                text = statusText,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun PromoChipV109(
    icon: @Composable () -> Unit,
    text: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.82f),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            icon()
            Text(
                text = text,
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
            )
        }
    }
}
