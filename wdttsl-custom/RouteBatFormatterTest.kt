// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RouteBatFormatterTest {
    @Test
    fun prefixMasksAreCorrect() {
        assertEquals("0.0.0.0", RouteBatFormatter.prefixToMask(0))
        assertEquals("255.0.0.0", RouteBatFormatter.prefixToMask(8))
        assertEquals("255.255.0.0", RouteBatFormatter.prefixToMask(16))
        assertEquals("255.255.255.0", RouteBatFormatter.prefixToMask(24))
        assertEquals("255.255.255.255", RouteBatFormatter.prefixToMask(32))
    }

    @Test
    fun cidrBecomesWindowsRouteCommand() {
        assertEquals(
            "route add 104.18.29.0 mask 255.255.255.0 0.0.0.0",
            RouteBatFormatter.cidrToRouteCommand("104.18.29.0/24"),
        )
        assertEquals(
            "route add 8.8.8.8 mask 255.255.255.255 0.0.0.0",
            RouteBatFormatter.cidrToRouteCommand("8.8.8.8/32"),
        )
    }

    @Test
    fun generatedSiteFileMatchesKnownWorkingMask() {
        val text = RouteBatFormatter.buildSiteRoutesFile(
            "bgdn-bpt.profiedu.ru",
            listOf("195.19.102.233"),
        )
        assertTrue(text.contains("REM VPNSL route file for bgdn-bpt.profiedu.ru"))
        assertTrue(text.contains("route add 195.19.102.233 mask 255.255.255.0 0.0.0.0"))
        assertFalse(text.contains("route add 195.19.102.233 mask 255.255.255.255 0.0.0.0"))
    }

    @Test
    fun siteFileContainsEveryIpv4Once() {
        val text = RouteBatFormatter.buildSiteRoutesFile(
            "example.com",
            listOf("8.8.8.8", "1.1.1.1", "8.8.8.8"),
        )
        assertTrue(text.contains("REM VPNSL route file for example.com"))
        assertEquals(1, Regex("route add 8\\.8\\.8\\.8").findAll(text).count())
        assertEquals(1, Regex("route add 1\\.1\\.1\\.1").findAll(text).count())
        assertTrue(text.contains("route add 8.8.8.8 mask 255.255.255.0 0.0.0.0"))
        assertTrue(text.contains("route add 1.1.1.1 mask 255.255.255.0 0.0.0.0"))
    }
}
