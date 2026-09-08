// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
package com.csqtt.client.routing

import org.junit.Assert.assertEquals
import org.junit.Test

class RoutePolicyCompilerV106Test {
    @Test
    fun emptyProfiles_defaultMobile_hasNoVpnRoutes() {
        assertEquals(emptyList<Ipv4Cidr>(), RoutePolicyCompiler.compile(emptyList(), RouteTarget.MOBILE))
    }

    @Test
    fun emptyProfiles_defaultWdttsl_isFullTunnel() {
        assertEquals(
            listOf(Ipv4Cidr.parse("0.0.0.0/0")!!),
            RoutePolicyCompiler.compile(emptyList(), RouteTarget.WDTTSL),
        )
    }

    @Test
    fun mobilePrefixCarvesHoleFromSelectedApplicationFullTunnel() {
        val profiles = listOf(
            RouteListProfile(
                id = "mobile-hole",
                name = "mobile-hole",
                enabled = true,
                target = RouteTarget.MOBILE,
                routes = listOf(Ipv4Cidr.parse("10.0.0.0/8")!!),
            )
        )
        val compiled = RoutePolicyCompiler.compile(profiles, RouteTarget.WDTTSL)
        require(compiled.isNotEmpty())
        require(compiled.none { it.toString() == "0.0.0.0/0" })
        require(compiled.none { it.toString() == "10.0.0.0/8" })
    }

    @Test
    fun specificWdttslRuleWinsInsideMobileParent() {
        val profiles = listOf(
            RouteListProfile(
                id = "mobile-parent",
                name = "mobile-parent",
                enabled = true,
                target = RouteTarget.MOBILE,
                routes = listOf(Ipv4Cidr.parse("10.0.0.0/8")!!),
            ),
            RouteListProfile(
                id = "vpn-child",
                name = "vpn-child",
                enabled = true,
                target = RouteTarget.WDTTSL,
                routes = listOf(Ipv4Cidr.parse("10.1.0.0/16")!!),
            ),
        )
        val compiled = RoutePolicyCompiler.compile(profiles, RouteTarget.WDTTSL)
        require(compiled.any { it.toString() == "10.1.0.0/16" })
    }
}
