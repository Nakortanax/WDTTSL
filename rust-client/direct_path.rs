// SPDX-FileCopyrightText: 2026 Sazhaev-IA
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

use crate::{dispatcher::Dispatcher, packet::PacketPool};
use anyhow::{Context, Result};
use futures::{SinkExt, StreamExt};
use netstack_smoltcp::{StackBuilder, TcpListener, UdpSocket};
use std::{collections::HashMap, net::SocketAddr, sync::Arc, time::Duration};
use tokio::{
    net::{TcpSocket, UdpSocket as TokioUdpSocket},
    sync::mpsc,
};
use tokio_util::sync::CancellationToken;

const STACK_QUEUE: usize = 512;
const UDP_QUEUE: usize = 64;
const UDP_SESSION_LIMIT: usize = 4096;
const UDP_IDLE: Duration = Duration::from_secs(120);

pub struct DirectPath {
    input: mpsc::Sender<Vec<u8>>,
    cancel: CancellationToken,
}

impl DirectPath {
    pub fn start(
        dispatcher: Arc<Dispatcher>,
        pool: Arc<PacketPool>,
        parent_cancel: CancellationToken,
    ) -> Result<Self> {
        let (stack, runner, udp_socket, tcp_listener) = StackBuilder::default()
            .stack_buffer_size(STACK_QUEUE)
            .tcp_buffer_size(32 * 1024)
            .enable_tcp(true)
            .enable_udp(true)
            .enable_icmp(false)
            .mtu(1500)
            .build()
            .context("создание userspace mobile netstack")?;
        let udp_socket = udp_socket.context("UDP netstack не создан")?;
        let tcp_listener = tcp_listener.context("TCP netstack не создан")?;
        let cancel = parent_cancel.child_token();

        if let Some(runner) = runner {
            let task_cancel = cancel.clone();
            tokio::spawn(async move {
                tokio::select! {
                    _ = task_cancel.cancelled() => {}
                    _ = runner => {}
                }
            });
        }

        let (mut stack_sink, mut stack_stream) = stack.split();
        let (input, mut input_rx) = mpsc::channel::<Vec<u8>>(STACK_QUEUE);
        let input_cancel = cancel.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = input_cancel.cancelled() => return,
                    packet = input_rx.recv() => match packet {
                        Some(packet) => {
                            if stack_sink.send(packet).await.is_err() {
                                return;
                            }
                        }
                        None => return,
                    }
                }
            }
        });

        let output_cancel = cancel.clone();
        tokio::spawn(async move {
            loop {
                let packet = tokio::select! {
                    _ = output_cancel.cancelled() => return,
                    packet = stack_stream.next() => packet,
                };
                let Some(Ok(packet)) = packet else { return; };
                let Some(mut buffer) = pool.try_acquire() else { continue; };
                let area = buffer.read_area();
                if packet.len() > area.len() {
                    continue;
                }
                area[..packet.len()].copy_from_slice(&packet);
                if buffer.set_read_len(packet.len()).is_ok() {
                    dispatcher.return_packet(buffer);
                }
            }
        });

        spawn_tcp_forwarder(tcp_listener, cancel.clone());
        spawn_udp_forwarder(udp_socket, cancel.clone());

        Ok(Self { input, cancel })
    }

    pub async fn send(&self, packet: &[u8]) -> Result<()> {
        self.input
            .send(packet.to_vec())
            .await
            .context("mobile netstack input closed")
    }
}

impl Drop for DirectPath {
    fn drop(&mut self) {
        self.cancel.cancel();
    }
}

fn spawn_tcp_forwarder(mut listener: TcpListener, cancel: CancellationToken) {
    tokio::spawn(async move {
        loop {
            let accepted = tokio::select! {
                _ = cancel.cancelled() => return,
                accepted = listener.next() => accepted,
            };
            let Some((mut local_stream, local, remote)) = accepted else { return; };
            let stream_cancel = cancel.clone();
            tokio::spawn(async move {
                match connect_tcp(remote).await {
                    Ok(mut remote_stream) => {
                        tokio::select! {
                            _ = stream_cancel.cancelled() => {}
                            result = tokio::io::copy_bidirectional(&mut local_stream, &mut remote_stream) => {
                                if let Err(error) = result {
                                    crate::log_error!("[ROUTING] MOBILE TCP {local}->{remote}: {error}");
                                }
                            }
                        }
                    }
                    Err(error) => {
                        crate::log_error!("[ROUTING] MOBILE TCP connect {remote}: {error}");
                    }
                }
            });
        }
    });
}

async fn connect_tcp(remote: SocketAddr) -> std::io::Result<tokio::net::TcpStream> {
    let socket = if remote.is_ipv4() {
        TcpSocket::new_v4()?
    } else {
        TcpSocket::new_v6()?
    };
    let stream = socket.connect(remote).await?;
    stream.set_nodelay(true)?;
    Ok(stream)
}

fn spawn_udp_forwarder(socket: UdpSocket, cancel: CancellationToken) {
    tokio::spawn(async move {
        let (response_tx, mut response_rx) = mpsc::unbounded_channel::<(Vec<u8>, SocketAddr, SocketAddr)>();
        let (mut read_half, mut write_half) = socket.split();
        let writer_cancel = cancel.clone();
        tokio::spawn(async move {
            loop {
                let response = tokio::select! {
                    _ = writer_cancel.cancelled() => return,
                    response = response_rx.recv() => response,
                };
                let Some((data, local, remote)) = response else { return; };
                let _ = write_half.send((data, remote, local)).await;
            }
        });

        let mut sessions: HashMap<(SocketAddr, SocketAddr), mpsc::Sender<Vec<u8>>> = HashMap::new();
        loop {
            let datagram = tokio::select! {
                _ = cancel.cancelled() => return,
                datagram = read_half.next() => datagram,
            };
            let Some((data, local, remote)) = datagram else { return; };
            let key = (local, remote);
            if let Some(sender) = sessions.get(&key) {
                if sender.send(data.clone()).await.is_ok() {
                    continue;
                }
            }
            sessions.remove(&key);
            if sessions.len() >= UDP_SESSION_LIMIT {
                sessions.retain(|_, sender| !sender.is_closed());
                if sessions.len() >= UDP_SESSION_LIMIT {
                    sessions.clear();
                }
            }
            match open_udp(remote).await {
                Ok(remote_socket) => {
                    let (session_tx, mut session_rx) = mpsc::channel::<Vec<u8>>(UDP_QUEUE);
                    let responses = response_tx.clone();
                    let session_cancel = cancel.clone();
                    tokio::spawn(async move {
                        let mut buffer = vec![0u8; 65535];
                        let idle = tokio::time::sleep(UDP_IDLE);
                        tokio::pin!(idle);
                        loop {
                            tokio::select! {
                                _ = session_cancel.cancelled() => return,
                                _ = &mut idle => return,
                                payload = session_rx.recv() => match payload {
                                    Some(payload) => {
                                        if remote_socket.send(&payload).await.is_err() { return; }
                                        idle.as_mut().reset(tokio::time::Instant::now() + UDP_IDLE);
                                    }
                                    None => return,
                                },
                                received = remote_socket.recv(&mut buffer) => match received {
                                    Ok(length) => {
                                        if responses.send((buffer[..length].to_vec(), local, remote)).is_err() { return; }
                                        idle.as_mut().reset(tokio::time::Instant::now() + UDP_IDLE);
                                    }
                                    Err(_) => return,
                                }
                            }
                        }
                    });
                    let _ = session_tx.send(data).await;
                    sessions.insert(key, session_tx);
                }
                Err(error) => {
                    crate::log_error!("[ROUTING] MOBILE UDP connect {remote}: {error}");
                }
            }
        }
    });
}

async fn open_udp(remote: SocketAddr) -> std::io::Result<TokioUdpSocket> {
    let bind = if remote.is_ipv4() {
        SocketAddr::from(([0, 0, 0, 0], 0))
    } else {
        SocketAddr::from(([0u16; 8], 0))
    };
    let socket = TokioUdpSocket::bind(bind).await?;
    socket.connect(remote).await?;
    Ok(socket)
}
