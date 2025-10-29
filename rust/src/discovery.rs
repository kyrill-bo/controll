use crate::protocol::Message;
use std::collections::HashMap;
use std::net::{Ipv4Addr, SocketAddrV4, UdpSocket};
use std::time::{Duration, Instant};

const MCAST_GRP: Ipv4Addr = Ipv4Addr::new(239, 255, 255, 250);
const MCAST_PORT: u16 = 54545;
const BEACON_INTERVAL: Duration = Duration::from_secs(2);
const DEVICE_TTL: Duration = Duration::from_secs(8);

pub struct DeviceInfo {
    pub name: String,
    pub ip: String,
    pub ws_port: u16,
    pub last_seen: Instant,
}

pub struct Discovery {
    pub instance_id: String,
    pub name: String,
    pub ws_port: u16,
    pub devices: HashMap<String, DeviceInfo>,
    sock: UdpSocket,
}

fn primary_ip() -> String {
    let s = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok();
    if let Some(s) = s {
        let _ = s.connect((Ipv4Addr::new(8, 8, 8, 8), 80));
        if let Ok(addr) = s.local_addr() {
            return addr.ip().to_string();
        }
    }
    "127.0.0.1".to_string()
}

impl Discovery {
    pub fn new(instance_id: String, name: String, ws_port: u16) -> std::io::Result<Self> {
        let sock = UdpSocket::bind(SocketAddrV4::new(Ipv4Addr::UNSPECIFIED, MCAST_PORT))?;
        sock.set_read_timeout(Some(Duration::from_millis(500)))?;
        sock.join_multicast_v4(&MCAST_GRP, &Ipv4Addr::UNSPECIFIED)?;
        sock.set_multicast_loop_v4(true)?;
        Ok(Self { instance_id, name, ws_port, devices: HashMap::new(), sock })
    }

    fn send_unicast(&self, target_ip: &str, msg: &Message) {
        if let Ok(data) = serde_json::to_vec(msg) {
            let _ = self.sock.send_to(&data, SocketAddrV4::new(target_ip.parse().unwrap_or(Ipv4Addr::LOCALHOST), MCAST_PORT));
        }
    }

    fn send_broadcast(&self, msg: &Message) {
        if let Ok(data) = serde_json::to_vec(msg) {
            let _ = self.sock.send_to(&data, SocketAddrV4::new(MCAST_GRP, MCAST_PORT));
        }
    }

    fn prune(&mut self) {
        let now = Instant::now();
        self.devices.retain(|_, d| now.duration_since(d.last_seen) <= DEVICE_TTL);
    }

    pub fn tick(&mut self, last_beacon: &mut Instant) {
        let now = Instant::now();
        if now.duration_since(*last_beacon) >= BEACON_INTERVAL {
            let msg = Message::BEACON { instance_id: self.instance_id.clone(), name: self.name.clone(), ip: primary_ip(), ws_port: self.ws_port, version: 1 };
            self.send_broadcast(&msg);
            *last_beacon = now;
            println!("[disc] beacon sent {}:{}", primary_ip(), self.ws_port);
        }
        self.prune();

        let mut buf = [0u8; 2048];
        if let Ok((n, _src)) = self.sock.recv_from(&mut buf) {
            if let Ok(text) = std::str::from_utf8(&buf[..n]) {
                if let Ok(msg) = serde_json::from_str::<Message>(text) {
                    match msg {
                        Message::BEACON { instance_id, name, ip, ws_port, .. } => {
                            if instance_id != self.instance_id {
                                self.devices.insert(instance_id.clone(), DeviceInfo { name, ip: ip.clone(), ws_port, last_seen: Instant::now() });
                                println!("[disc] seen {} @ {}:{}", instance_id, ip, ws_port);
                            }
                        }
                        Message::REQUEST_CONTROL { from, to, name, ws_host, ws_port, options: _ } => {
                            if to.as_deref().map(|t| t == self.instance_id).unwrap_or(true) {
                                println!("[disc] request from {} ({})", name, from);
                                let resp = Message::RESPONSE_CONTROL { from: self.instance_id.clone(), accepted: true };
                                self.send_unicast(&ws_host, &resp);
                                println!("[disc] sent accept to {}", ws_host);
                            }
                        }
                        Message::RESPONSE_CONTROL { from, accepted } => {
                            println!("[disc] response from {} accepted={}", from, accepted);
                        }
                    }
                }
            }
        }
    }

    pub fn send_request(&self, target_ip: &str, options: serde_json::Value, to: Option<String>) {
        let msg = Message::REQUEST_CONTROL { from: self.instance_id.clone(), to, name: self.name.clone(), ws_host: primary_ip(), ws_port: self.ws_port, options };
        self.send_unicast(target_ip, &msg);
        println!("[disc] request sent to {}", target_ip);
    }
}

pub fn run_loop(inst: String, name: String, ws_port: u16) -> std::io::Result<()> {
    let mut disc = Discovery::new(inst, name, ws_port)?;
    let mut last_beacon = Instant::now() - BEACON_INTERVAL;
    loop { disc.tick(&mut last_beacon); }
}
