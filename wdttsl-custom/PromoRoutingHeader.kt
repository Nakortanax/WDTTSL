// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL 1.0.8: routing promo banner intentionally removed to free vertical space.

package com.csqtt.client.ui

import androidx.compose.runtime.Composable
import com.csqtt.client.routing.RoutingSourceMode

@Composable
fun PromoRoutingHeader(
    mode: RoutingSourceMode,
    selectedApps: Int,
) {
    // Intentionally empty. The routing screen keeps the compact mode selector,
    // while the large promo card is removed so the generator remains usable
    // when the Android keyboard is visible.
}
