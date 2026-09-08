// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// WDTTSL derivative routing module.

package com.csqtt.client.routing

enum class RouteTarget {
    MOBILE,
    WDTTSL,
}

enum class RoutingSourceMode {
    APPLICATIONS,
    ROUTE_LISTS,
}

data class Ipv4Cidr(
    val network: Long,
    val prefixLength: Int,
) {
    init {
        require(prefixLength in 0..32) { "IPv4 prefix must be 0..32" }
        require(network in 0..0xffff_ffffL) { "IPv4 network is out of range" }
        require(network == (network and maskFor(prefixLength))) {
            "IPv4 address is not normalized to the network prefix"
        }
    }

    val address: String
        get() = toAddress(network)

    override fun toString(): String = "$address/$prefixLength"

    companion object {
        private const val IPV4_MAX = 0xffff_ffffL

        fun parse(raw: String): Ipv4Cidr? {
            val value = raw.trim()
            if (value.isEmpty()) return null
            val slash = value.indexOf('/')
            val addressPart = if (slash >= 0) value.substring(0, slash) else value
            val prefix = if (slash >= 0) {
                value.substring(slash + 1).toIntOrNull() ?: return null
            } else {
                32
            }
            if (prefix !in 0..32) return null
            val ip = parseAddress(addressPart) ?: return null
            val mask = maskFor(prefix)
            return Ipv4Cidr(ip and mask, prefix)
        }

        fun fromAddressAndMask(address: String, dottedMask: String): Ipv4Cidr? {
            val ip = parseAddress(address) ?: return null
            val prefix = netmaskToPrefix(dottedMask) ?: return null
            return Ipv4Cidr(ip and maskFor(prefix), prefix)
        }

        fun netmaskToPrefix(dottedMask: String): Int? {
            val mask = parseAddress(dottedMask) ?: return null
            val inverted = mask xor IPV4_MAX
            // A valid netmask has a contiguous run of 1 bits followed by 0 bits.
            // Therefore its inverted value must be 0...011...1.
            if ((inverted and (inverted + 1L)) != 0L) return null
            return java.lang.Long.bitCount(mask).coerceIn(0, 32)
        }

        fun parseAddress(raw: String): Long? {
            val parts = raw.trim().split('.')
            if (parts.size != 4) return null
            var result = 0L
            for (part in parts) {
                if (part.isEmpty() || part.length > 3) return null
                val octet = part.toIntOrNull() ?: return null
                if (octet !in 0..255) return null
                result = (result shl 8) or octet.toLong()
            }
            return result
        }

        fun toAddress(value: Long): String {
            require(value in 0..IPV4_MAX)
            return listOf(
                (value ushr 24) and 0xff,
                (value ushr 16) and 0xff,
                (value ushr 8) and 0xff,
                value and 0xff,
            ).joinToString(".")
        }

        fun maskFor(prefixLength: Int): Long {
            require(prefixLength in 0..32)
            if (prefixLength == 0) return 0L
            return (IPV4_MAX shl (32 - prefixLength)) and IPV4_MAX
        }
    }
}

data class RouteListProfile(
    val id: String,
    val name: String,
    val enabled: Boolean = true,
    val target: RouteTarget = RouteTarget.WDTTSL,
    val routes: List<Ipv4Cidr>,
)
