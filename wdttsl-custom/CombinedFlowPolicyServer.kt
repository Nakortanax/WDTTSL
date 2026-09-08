// SPDX-FileCopyrightText: 2026 Sazhaev-IA
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

package com.csqtt.client.routing

import android.net.ConnectivityManager
import android.net.LocalServerSocket
import android.net.LocalSocket
import android.net.VpnService
import android.os.Build
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.InetSocketAddress
import kotlin.concurrent.thread

/**
 * Answers per-flow routing queries from the native TUN dispatcher.
 *
 * Union policy used by VPNSL 1.0.6:
 *   destination in an enabled WDTTSL list OR owner UID belongs to a selected
 *   application -> WDTTSL; otherwise -> physical mobile network.
 */
class CombinedFlowPolicyServer(
    private val service: VpnService,
    selectedUids: Set<Int>,
    wdttslRoutes: List<Ipv4Cidr>,
) {
    private val selectedUids = selectedUids.toSet()
    private val wdttslRoutes = wdttslRoutes.toList()
    private val connectivityManager = service.getSystemService(ConnectivityManager::class.java)
    private val stateLock = Any()
    @Volatile private var running = false
    private var serverSocket: LocalServerSocket? = null
    private var worker: Thread? = null

    fun start() {
        synchronized(stateLock) {
            if (running) return
            check(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                "Совместная маршрутизация требует Android 10 или новее"
            }
            val server = LocalServerSocket(SOCKET_NAME)
            serverSocket = server
            running = true
            worker = thread(
                start = true,
                isDaemon = true,
                name = "VPNSL-flow-policy",
            ) {
                serve(server)
            }
        }
    }

    fun stop() {
        val threadToJoin = synchronized(stateLock) {
            if (!running && serverSocket == null) return
            running = false
            runCatching { serverSocket?.close() }
            serverSocket = null
            worker.also { worker = null }
        }
        if (threadToJoin != null && Thread.currentThread() !== threadToJoin) {
            runCatching { threadToJoin.join(250) }
        }
    }

    private fun serve(server: LocalServerSocket) {
        while (running) {
            val client = try {
                server.accept()
            } catch (error: Exception) {
                if (running) Log.w(TAG, "Flow policy accept failed", error)
                return
            }
            try {
                handle(client)
            } catch (error: Exception) {
                Log.w(TAG, "Flow policy query failed", error)
                runCatching {
                    client.outputStream.write(DECISION_WDTTSL.code)
                    client.outputStream.flush()
                }
            } finally {
                runCatching { client.close() }
            }
        }
    }

    private fun handle(client: LocalSocket) {
        client.soTimeout = 500
        val line = BufferedReader(InputStreamReader(client.inputStream)).readLine().orEmpty()
        val request = FlowRequest.parse(line)
        val decision = if (request == null) {
            DECISION_WDTTSL
        } else if (matchesWdttslRoute(request.destination.address)) {
            DECISION_WDTTSL
        } else {
            val uid = ownerUid(request)
            if (uid >= 0 && uid in selectedUids) DECISION_WDTTSL else DECISION_MOBILE
        }
        client.outputStream.write(decision.code)
        client.outputStream.flush()
    }

    private fun ownerUid(request: FlowRequest): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return -1
        repeat(3) { attempt ->
            val uid = runCatching {
                connectivityManager.getConnectionOwnerUid(
                    request.protocol,
                    request.source,
                    request.destination,
                )
            }.getOrDefault(-1)
            if (uid >= 0) return uid
            if (attempt < 2) Thread.sleep(2)
        }
        return -1
    }

    private fun matchesWdttslRoute(address: InetAddress): Boolean {
        val bytes = address.address
        if (bytes.size != 4) return false
        val value = ((bytes[0].toLong() and 0xffL) shl 24) or
            ((bytes[1].toLong() and 0xffL) shl 16) or
            ((bytes[2].toLong() and 0xffL) shl 8) or
            (bytes[3].toLong() and 0xffL)
        return wdttslRoutes.any { route ->
            (value and Ipv4Cidr.maskFor(route.prefixLength)) == route.network
        }
    }

    private data class FlowRequest(
        val protocol: Int,
        val source: InetSocketAddress,
        val destination: InetSocketAddress,
    ) {
        companion object {
            fun parse(raw: String): FlowRequest? {
                val parts = raw.trim().split('|')
                if (parts.size != 5) return null
                val protocol = parts[0].toIntOrNull()?.takeIf { it == 6 || it == 17 } ?: return null
                val sourcePort = parts[2].toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
                val destinationPort = parts[4].toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
                val sourceAddress = runCatching { InetAddress.getByName(parts[1]) }.getOrNull() ?: return null
                val destinationAddress = runCatching { InetAddress.getByName(parts[3]) }.getOrNull() ?: return null
                if (sourceAddress.address.size != 4 || destinationAddress.address.size != 4) return null
                return FlowRequest(
                    protocol = protocol,
                    source = InetSocketAddress(sourceAddress, sourcePort),
                    destination = InetSocketAddress(destinationAddress, destinationPort),
                )
            }
        }
    }

    companion object {
        const val SOCKET_NAME = "wdttsl_flow_policy"
        private const val TAG = "VPNSL-FlowPolicy"
        private const val DECISION_WDTTSL = 'W'
        private const val DECISION_MOBILE = 'M'
    }
}
