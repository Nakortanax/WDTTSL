// SPDX-FileCopyrightText: 2026 amurcanov
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class RouteListStore(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences("wdttsl_route_lists", Context.MODE_PRIVATE)

    fun routingSourceMode(): RoutingSourceMode = runCatching {
        RoutingSourceMode.valueOf(
            prefs.getString(KEY_SOURCE_MODE, RoutingSourceMode.APPLICATIONS.name)
                ?: RoutingSourceMode.APPLICATIONS.name
        )
    }.getOrDefault(RoutingSourceMode.APPLICATIONS)

    fun saveRoutingSourceMode(mode: RoutingSourceMode) {
        prefs.edit().putString(KEY_SOURCE_MODE, mode.name).apply()
    }

    fun loadProfiles(): List<RouteListProfile> {
        val raw = prefs.getString(KEY_PROFILES, null) ?: return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val obj = array.optJSONObject(index) ?: continue
                    val target = runCatching {
                        RouteTarget.valueOf(obj.optString("target", RouteTarget.WDTTSL.name))
                    }.getOrDefault(RouteTarget.WDTTSL)
                    val routesJson = obj.optJSONArray("routes") ?: JSONArray()
                    val routes = buildList {
                        for (routeIndex in 0 until routesJson.length()) {
                            Ipv4Cidr.parse(routesJson.optString(routeIndex))?.let(::add)
                        }
                    }.distinct()
                    if (routes.isNotEmpty()) {
                        add(
                            RouteListProfile(
                                id = obj.optString("id").ifBlank { UUID.randomUUID().toString() },
                                name = obj.optString("name", "routes.list"),
                                enabled = obj.optBoolean("enabled", true),
                                target = target,
                                routes = routes,
                            )
                        )
                    }
                }
            }
        }.getOrElse { emptyList() }
    }

    fun saveProfiles(profiles: List<RouteListProfile>) {
        val array = JSONArray()
        profiles.forEach { profile ->
            array.put(
                JSONObject().apply {
                    put("id", profile.id)
                    put("name", profile.name)
                    put("enabled", profile.enabled)
                    put("target", profile.target.name)
                    put("routes", JSONArray(profile.routes.map(Ipv4Cidr::toString)))
                }
            )
        }
        prefs.edit().putString(KEY_PROFILES, array.toString()).apply()
    }

    fun importProfile(
        displayName: String,
        text: String,
        target: RouteTarget = RouteTarget.WDTTSL,
    ): RouteFileParser.ParseResult {
        val result = RouteFileParser.parse(text)
        if (result.routes.isEmpty()) return result
        val current = loadProfiles().toMutableList()
        current += RouteListProfile(
            id = UUID.randomUUID().toString(),
            name = sanitizeName(displayName),
            enabled = true,
            target = target,
            routes = result.routes,
        )
        saveProfiles(current)
        return result
    }

    fun replace(profile: RouteListProfile) {
        val profiles = loadProfiles().toMutableList()
        val index = profiles.indexOfFirst { it.id == profile.id }
        if (index >= 0) profiles[index] = profile else profiles += profile
        saveProfiles(profiles)
    }

    fun remove(id: String) {
        saveProfiles(loadProfiles().filterNot { it.id == id })
    }

    private fun sanitizeName(raw: String): String {
        val fallback = "routes.list"
        return raw.trim().ifBlank { fallback }.take(120)
    }

    companion object {
        private const val KEY_PROFILES = "profiles_json_v2"
        private const val KEY_SOURCE_MODE = "routing_source_mode_v2"
    }
}
