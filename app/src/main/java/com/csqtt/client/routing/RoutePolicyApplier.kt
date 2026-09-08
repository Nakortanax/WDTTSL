// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

import android.net.VpnService
import android.util.Log

object RoutePolicyApplier {
    private const val TAG = "WDTTSL-RoutePolicy"

    /**
     * Applies only the destinations that should enter WDTTSL.
     * Destinations not present in this table remain on Android's physical/default route.
     */
    fun apply(builder: VpnService.Builder, profiles: List<RouteListProfile>): Int {
        val compiled = RoutePolicyCompiler.compile(profiles)
        var count = 0
        compiled.forEach { route ->
            runCatching {
                builder.addRoute(route.address, route.prefixLength)
            }.onSuccess {
                count++
            }.onFailure {
                Log.w(TAG, "Cannot add route $route", it)
            }
        }
        return count
    }
}
