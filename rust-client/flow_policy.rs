// SPDX-FileCopyrightText: 2026 Sazhaev-IA
// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

use anyhow::{Context, Result};
use nix::sys::socket::{
    AddressFamily, MsgFlags, SockFlag, SockType, UnixAddr, connect, recv, send, socket,
};
use std::{
    collections::HashMap,
    net::Ipv4Addr,
    os::fd::AsRawFd,
    time::{Duration, Instant},
};

const POLICY_SOCKET: &str = "wdttsl_flow_policy";
const MAX_FLOWS: usize = 8192;
const FLOW_TTL: Duration = Duration::from_secs(180);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FlowDecision {
    Wdttsl,
    Mobile,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
struct FlowKey {
    protocol: u8,
    source: Ipv4Addr,
    source_port: u16,
    destination: Ipv4Addr,
    destination_port: u16,
}

struct CachedDecision {
    decision: FlowDecision,
    touched: Instant,
}

pub struct FlowPolicyClient {
    cache: HashMap<FlowKey, CachedDecision>,
    last_error_log: Option<Instant>,
}

impl FlowPolicyClient {
    pub fn new() -> Self {
        Self {
            cache: HashMap::with_capacity(1024),
            last_error_log: None,
        }
    }

    pub fn decide(&mut self, packet: &[u8]) -> FlowDecision {
        let Some(key) = parse_ipv4_flow(packet) else {
            // Unknown/fragmented traffic is kept on WDTTSL so that selected
            // applications can never silently leak to the mobile path.
            return FlowDecision::Wdttsl;
        };
        let now = Instant::now();
        if let Some(cached) = self.cache.get_mut(&key) {
            cached.touched = now;
            return cached.decision;
        }
        if self.cache.len() >= MAX_FLOWS {
            self.cache.retain(|_, value| now.duration_since(value.touched) < FLOW_TTL);
            if self.cache.len() >= MAX_FLOWS {
                self.cache.clear();
            }
        }
        let decision = match query_policy(key) {
            Ok(decision) => decision,
            Err(error) => {
                let should_log = self
                    .last_error_log
                    .is_none_or(|previous| now.duration_since(previous) >= Duration::from_secs(5));
                if should_log {
                    crate::log_error!("[ROUTING] Flow policy недоступна: {error:#}; fallback=WDTTSL");
                    self.last_error_log = Some(now);
                }
                FlowDecision::Wdttsl
            }
        };
        self.cache.insert(key, CachedDecision { decision, touched: now });
        decision
    }
}

fn parse_ipv4_flow(packet: &[u8]) -> Option<FlowKey> {
    if packet.len() < 20 || packet[0] >> 4 != 4 {
        return None;
    }
    let ihl = usize::from(packet[0] & 0x0f) * 4;
    if ihl < 20 || packet.len() < ihl + 4 {
        return None;
    }
    let fragment = u16::from_be_bytes([packet[6], packet[7]]);
    if fragment & 0x1fff != 0 {
        return None;
    }
    let protocol = packet[9];
    if protocol != 6 && protocol != 17 {
        return None;
    }
    let source = Ipv4Addr::new(packet[12], packet[13], packet[14], packet[15]);
    let destination = Ipv4Addr::new(packet[16], packet[17], packet[18], packet[19]);
    let source_port = u16::from_be_bytes([packet[ihl], packet[ihl + 1]]);
    let destination_port = u16::from_be_bytes([packet[ihl + 2], packet[ihl + 3]]);
    Some(FlowKey {
        protocol,
        source,
        source_port,
        destination,
        destination_port,
    })
}

fn query_policy(key: FlowKey) -> Result<FlowDecision> {
    let descriptor = socket(
        AddressFamily::Unix,
        SockType::Stream,
        SockFlag::SOCK_CLOEXEC,
        None,
    )?;
    let timeout = libc::timeval {
        tv_sec: 0,
        tv_usec: 250_000,
    };
    unsafe {
        libc::setsockopt(
            descriptor.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_RCVTIMEO,
            (&timeout as *const libc::timeval).cast(),
            std::mem::size_of::<libc::timeval>() as libc::socklen_t,
        );
    }
    connect(
        descriptor.as_raw_fd(),
        &UnixAddr::new_abstract(POLICY_SOCKET.as_bytes())?,
    )
    .context("connect flow policy UDS")?;
    let request = format!(
        "{}|{}|{}|{}|{}\n",
        key.protocol, key.source, key.source_port, key.destination, key.destination_port
    );
    send(
        descriptor.as_raw_fd(),
        request.as_bytes(),
        MsgFlags::MSG_NOSIGNAL,
    )
    .context("send flow policy query")?;
    let mut response = [0u8; 1];
    let count = recv(descriptor.as_raw_fd(), &mut response, MsgFlags::empty())
        .context("receive flow policy response")?;
    if count != 1 {
        anyhow::bail!("empty flow policy response");
    }
    match response[0] {
        b'M' => Ok(FlowDecision::Mobile),
        b'W' => Ok(FlowDecision::Wdttsl),
        other => anyhow::bail!("invalid flow policy response: {other}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_tcp_flow() {
        let mut packet = vec![0u8; 40];
        packet[0] = 0x45;
        packet[9] = 6;
        packet[12..16].copy_from_slice(&[10, 66, 66, 2]);
        packet[16..20].copy_from_slice(&[1, 2, 3, 4]);
        packet[20..22].copy_from_slice(&12345u16.to_be_bytes());
        packet[22..24].copy_from_slice(&443u16.to_be_bytes());
        let flow = parse_ipv4_flow(&packet).unwrap();
        assert_eq!(flow.source_port, 12345);
        assert_eq!(flow.destination_port, 443);
        assert_eq!(flow.destination, Ipv4Addr::new(1, 2, 3, 4));
    }

    #[test]
    fn rejects_non_initial_fragment() {
        let mut packet = vec![0u8; 40];
        packet[0] = 0x45;
        packet[6..8].copy_from_slice(&1u16.to_be_bytes());
        packet[9] = 17;
        assert!(parse_ipv4_flow(&packet).is_none());
    }
}
