// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

object RouteFileParser {
    private val routeAddRegex = Regex(
        pattern = """(?i)^\s*route\s+(?:-p\s+)?add\s+(\d{1,3}(?:\.\d{1,3}){3})(?:\s+mask\s+(\d{1,3}(?:\.\d{1,3}){3}))?(?:\s+.*)?$"""
    )

    data class ParseResult(
        val routes: List<Ipv4Cidr>,
        val rejectedLines: List<String>,
    )

    fun parse(text: String): ParseResult {
        val routes = linkedSetOf<Ipv4Cidr>()
        val rejected = mutableListOf<String>()

        text.lineSequence().forEach { rawLine ->
            val line = rawLine.trim().removePrefix("\uFEFF")
            if (line.isBlank() || isComment(line)) return@forEach

            val routeMatch = routeAddRegex.matchEntire(line)
            if (routeMatch != null) {
                val address = routeMatch.groupValues[1]
                val mask = routeMatch.groupValues[2]
                val parsed = if (mask.isBlank()) {
                    Ipv4Cidr.parse("$address/32")
                } else {
                    Ipv4Cidr.fromAddressAndMask(address, mask)
                }
                if (parsed != null) routes += parsed else rejected += rawLine
                return@forEach
            }

            // Plain list formats accepted by WDTTSL:
            // 1.2.3.0/24
            // 1.2.3.4          (treated as /32)
            val token = line.substringBefore(' ').substringBefore('\t').trim()
            val parsed = Ipv4Cidr.parse(token)
            if (parsed != null) routes += parsed else rejected += rawLine
        }

        return ParseResult(routes = routes.toList(), rejectedLines = rejected)
    }

    private fun isComment(line: String): Boolean {
        val lower = line.lowercase()
        return line.startsWith('#') ||
            line.startsWith(';') ||
            line.startsWith("::") ||
            lower == "rem" ||
            lower.startsWith("rem ")
    }
}
