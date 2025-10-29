use crate::protocol::Message;
use std::collections::HashMap;
use std::net::{Ipv4Addr, SocketAddrV4, UdpSocket};
use std::sync::mpsc::Sender;
use std::time::{Duration, Instant};

const MCAST_GRP: Ipv4Addr = Ipv4Addr::new(239, 255, 255, 250);
const MCAST_PORT: u16 = 54545;
const BEACON_INTERVAL: Duration = Duration::from_secs(2);
const DEVICE_TTL: Duration = Duration::from_secs(8);

#[derive(Clone, Debug)]
pub struct DeviceInfo {
    pub name: String,
    pub ip: String,
    pub ws_port: u16,
    pub last_seen: Instant,
}

#[derive(Clone, Debug)]
pub enum DiscEvent {
    DevicesChanged(Vec<DeviceInfo>),
    RequestReceived { from_inst: String, from_name: String, ws_host: String, ws_port: u16 },
    ResponseAccepted { host: String, port: u16 },
}

pub struct Discovery {
    pub instance_id: String,
    pub name: String,
    pub ws_port: u16,
    pub devices: HashMap<String, DeviceInfo>,
    sock: UdpSocket,
    event_tx: Option<Sender<DiscEvent>>,
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
        Self::new_with_sender(instance_id, name, ws_port, None)
    }

    pub fn new_with_sender(instance_id: String, name: String, ws_port: u16, event_tx: Option<Sender<DiscEvent>>) -> std::io::Result<Self> {
        use socket2::{Domain, Protocol, Socket, Type};
        // Determine primary interface IP for joining/sending
        let local_ip: Ipv4Addr = primary_ip().parse().unwrap_or(Ipv4Addr::UNSPECIFIED);
        let s = Socket::new(Domain::IPV4, Type::DGRAM, Some(Protocol::UDP))?;
        s.set_reuse_address(true)?;
        #[cfg(target_os = "macos")]
        {
            use std::os::fd::AsRawFd;
            let fd = s.as_raw_fd();
            let on: i32 = 1;
            unsafe { libc::setsockopt(fd, libc::SOL_SOCKET, libc::SO_REUSEPORT, &on as *const _ as *const _, std::mem::size_of_val(&on) as libc::socklen_t) };
        }
        s.bind(&SocketAddrV4::new(Ipv4Addr::UNSPECIFIED, MCAST_PORT).into())?;
        s.join_multicast_v4(&MCAST_GRP, &local_ip)?;
        s.set_multicast_loop_v4(true)?;
        s.set_multicast_ttl_v4(32)?;
        s.set_multicast_if_v4(&local_ip)?;
        let sock: UdpSocket = s.into();
        sock.set_read_timeout(Some(Duration::from_millis(500)))?;
        Ok(Self { instance_id, name, ws_port, devices: HashMap::new(), sock, event_tx })
    }

    fn send_unicast(&self, target_ip: &str, msg: &Message) {
        if let Ok(data) = serde_json::to_vec(msg) {
            let _ = self.sock.send_to(&data, SocketAddrV4::new(target_ip.parse().unwrap_or(Ipv4Addr::LOCALHOST), MCAST_PORT));
        }
    }

    fn send_broadcast(&self, msg: &Message) {
        if let Ok(data) = serde_json::to_vec(msg) {
            // Send on the socket configured with multicast IF
            let _ = self.sock.send_to(&data, SocketAddrV4::new(MCAST_GRP, MCAST_PORT));
        }
    }

    fn prune(&mut self) {
        let now = Instant::now();
        let before = self.devices.len();
        self.devices.retain(|_, d| now.duration_since(d.last_seen) <= DEVICE_TTL);
        if self.devices.len() != before {
            if let Some(tx) = &self.event_tx {
                let list: Vec<DeviceInfo> = self.devices.values().cloned().collect();
                let _ = tx.send(DiscEvent::DevicesChanged(list));
            }
        }
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
        if let Ok((n, src)) = self.sock.recv_from(&mut buf) {
            if let Ok(text) = std::str::from_utf8(&buf[..n]) {
                if let Ok(msg) = serde_json::from_str::<Message>(text) {
                    match msg {
                        Message::BEACON { instance_id, name, ip, ws_port, .. } => {
                            if instance_id != self.instance_id {
                                self.devices.insert(instance_id.clone(), DeviceInfo { name, ip: ip.clone(), ws_port, last_seen: Instant::now() });
                                println!("[disc] seen {} @ {}:{}", instance_id, ip, ws_port);
                                if let Some(tx) = &self.event_tx {
                                    let list: Vec<DeviceInfo> = self.devices.values().cloned().collect();
                                    let _ = tx.send(DiscEvent::DevicesChanged(list));
                                }
                            }
                        }
                        Message::RequestControl { from, to, name, ws_host, ws_port, options: _ } => {
                            if to.as_deref().map(|t| t == self.instance_id).unwrap_or(true) {
                                println!("[disc] request from {} ({})", name, from);
                                if let Some(tx) = &self.event_tx {
                                    let _ = tx.send(DiscEvent::RequestReceived { from_inst: from, from_name: name, ws_host, ws_port });
                                }
                            }
                        }
                        Message::ResponseControl { from, accepted } => {
                            println!("[disc] response from {} accepted={}", from, accepted);
                            if accepted {
                                let host = match src { std::net::SocketAddr::V4(v4) => v4.ip().to_string(), _ => "127.0.0.1".to_string() };
                                let port = self.devices.get(&from).map(|d| d.ws_port).unwrap_or(self.ws_port);
                                if let Some(tx) = &self.event_tx { let _ = tx.send(DiscEvent::ResponseAccepted { host, port }); }
                            }
                        }
                    }
                }
            }
        }
    }

    pub fn send_request(&self, target_ip: &str, options: serde_json::Value, to: Option<String>) {
        let msg = Message::RequestControl { from: self.instance_id.clone(), to, name: self.name.clone(), ws_host: primary_ip(), ws_port: self.ws_port, options };
        self.send_unicast(target_ip, &msg);
        println!("[disc] request sent to {}", target_ip);
    }

    pub fn send_response(&self, target_ip: &str, accepted: bool) {
        let msg = Message::ResponseControl { from: self.instance_id.clone(), accepted };
        self.send_unicast(target_ip, &msg);
        println!("[disc] response sent to {} accepted={}", target_ip, accepted);
    }
}

pub fn run_loop_with_sender(inst: String, name: String, ws_port: u16, event_tx: Option<Sender<DiscEvent>>) -> std::io::Result<()> {
    let mut disc = Discovery::new_with_sender(inst, name, ws_port, event_tx)?;
    let mut last_beacon = Instant::now() - BEACON_INTERVAL;
    loop { disc.tick(&mut last_beacon); }
}
