// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// VPNSL derivative route export helpers by Sazhaev-IA.

package com.csqtt.client.routing

object RouteBatFormatter {
    fun cidrToRouteCommand(cidr: String): String {
        val parts = cidr.trim().split('/', limit = 2)
        require(parts.size == 2) { "CIDR prefix is required: $cidr" }
        val prefix = parts[1].toIntOrNull() ?: error("Invalid CIDR prefix: $cidr")
        require(prefix in 0..32) { "Invalid CIDR prefix: $cidr" }
        return "route add ${parts[0]} mask ${prefixToMask(prefix)} 0.0.0.0"
    }

    fun prefixToMask(prefix: Int): String {
        require(prefix in 0..32)
        val mask = if (prefix == 0) 0L else (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
        return listOf(24, 16, 8, 0)
            .joinToString(".") { shift -> ((mask shr shift) and 0xFF).toString() }
    }

    fun buildAllRoutesFile(profiles: List<RouteListProfile>): String = buildString {
        appendLine("REM VPNSL routes export")
        appendLine("REM All saved route profiles are included, including disabled ones.")
        appendLine("REM Network selection and active state are informational comments in BAT format.")
        profiles.forEachIndexed { index, profile ->
            if (index > 0) appendLine()
            appendLine("REM ${safeComment(profile.name)} | ${if (profile.enabled) "enabled" else "disabled"} | ${targetLabel(profile.target)}")
            profile.routes.forEach { route ->
                appendLine(cidrToRouteCommand(route.toString()))
            }
        }
    }

    fun buildSiteRoutesFile(host: String, ipv4: List<String>): String = buildString {
        appendLine("REM VPNSL route file for ${safeComment(host)}")
        ipv4.distinct().sorted().forEach { address ->
            appendLine(cidrToRouteCommand("$address/32"))
        }
    }

    private fun targetLabel(target: RouteTarget): String = when (target) {
        RouteTarget.MOBILE -> "MOBILE"
        RouteTarget.WDTTSL -> "VPNSL"
    }

    private fun safeComment(value: String): String = value
        .replace('\r', ' ')
        .replace('\n', ' ')
        .trim()
}
