// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

/**
 * Compiles user profiles into the minimum practical set of IPv4 routes that
 * must enter the WDTTSL VPN. The global default is MOBILE.
 *
 * Conflict rules:
 * 1. Longest prefix wins.
 * 2. For identical prefixes, the profile later in the list wins.
 *
 * This makes MOBILE overrides work even on Android 8-12, which do not have
 * VpnService.Builder.excludeRoute().
 */
object RoutePolicyCompiler {
    private class Node {
        var target: RouteTarget? = null
        var ordinal: Int = -1
        var zero: Node? = null
        var one: Node? = null
    }

    private data class Outcome(
        val uniform: RouteTarget?,
        val wdttslRoutes: MutableList<Ipv4Cidr> = mutableListOf(),
    )

    fun compile(profiles: List<RouteListProfile>): List<Ipv4Cidr> {
        val root = Node()
        var ordinal = 0
        profiles.forEach { profile ->
            if (!profile.enabled) return@forEach
            profile.routes.forEach { route ->
                insert(root, route, profile.target, ordinal++)
            }
        }

        val outcome = evaluate(
            node = root,
            inheritedTarget = RouteTarget.MOBILE,
            network = 0L,
            depth = 0,
        )
        return when (outcome.uniform) {
            RouteTarget.WDTTSL -> listOf(Ipv4Cidr(0L, 0))
            RouteTarget.MOBILE -> emptyList()
            null -> outcome.wdttslRoutes.sortedWith(
                compareBy<Ipv4Cidr> { it.network }.thenBy { it.prefixLength }
            )
        }
    }

    private fun insert(root: Node, route: Ipv4Cidr, target: RouteTarget, ordinal: Int) {
        var node = root
        for (depth in 0 until route.prefixLength) {
            val bit = ((route.network ushr (31 - depth)) and 1L).toInt()
            node = if (bit == 0) {
                node.zero ?: Node().also { node.zero = it }
            } else {
                node.one ?: Node().also { node.one = it }
            }
        }
        if (ordinal >= node.ordinal) {
            node.ordinal = ordinal
            node.target = target
        }
    }

    private fun evaluate(
        node: Node?,
        inheritedTarget: RouteTarget,
        network: Long,
        depth: Int,
    ): Outcome {
        if (node == null) return Outcome(uniform = inheritedTarget)

        val effectiveTarget = node.target ?: inheritedTarget
        if (depth == 32) return Outcome(uniform = effectiveTarget)

        val nextDepth = depth + 1
        val halfSize = if (nextDepth == 32) 1L else 1L shl (32 - nextDepth)

        val left = evaluate(node.zero, effectiveTarget, network, nextDepth)
        val right = evaluate(node.one, effectiveTarget, network + halfSize, nextDepth)

        if (left.uniform != null && left.uniform == right.uniform) {
            return Outcome(uniform = left.uniform)
        }

        val routes = mutableListOf<Ipv4Cidr>()
        appendChild(routes, left, network, nextDepth)
        appendChild(routes, right, network + halfSize, nextDepth)
        return Outcome(uniform = null, wdttslRoutes = routes)
    }

    private fun appendChild(
        destination: MutableList<Ipv4Cidr>,
        child: Outcome,
        childNetwork: Long,
        childDepth: Int,
    ) {
        when (child.uniform) {
            RouteTarget.WDTTSL -> destination += Ipv4Cidr(childNetwork, childDepth)
            RouteTarget.MOBILE -> Unit
            null -> destination += child.wdttslRoutes
        }
    }
}
