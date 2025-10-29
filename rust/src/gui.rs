use crate::discovery::{DiscEvent, DeviceInfo};
use crate::protocol::Message;
use eframe::egui;
use std::net::{Ipv4Addr, SocketAddrV4, UdpSocket};
use std::sync::mpsc::Receiver;

pub struct UiApp {
    rx: Receiver<DiscEvent>,
    devices: Vec<DeviceInfo>,
    selected: Option<usize>,
    incoming: Option<(String, String, u16)>, // (from_name, ws_host, ws_port)
    status: String,
    ws_port: u16,
    inst: String,
    name: String,
}

impl UiApp {
    pub fn new(rx: Receiver<DiscEvent>, ws_port: u16, inst: String, name: String) -> Self {
        Self { rx, devices: vec![], selected: None, incoming: None, status: String::new(), ws_port, inst, name }
    }

    fn poll_events(&mut self) {
        while let Ok(ev) = self.rx.try_recv() {
            match ev {
                DiscEvent::DevicesChanged(list) => { self.devices = list; }
                DiscEvent::RequestReceived { from_inst: _, from_name, ws_host, ws_port } => {
                    self.incoming = Some((from_name, ws_host, ws_port));
                }
                DiscEvent::ResponseAccepted { host: _, port: _ } => {
                    self.status = "Response accepted".into();
                }
            }
        }
    }

    fn send_request_unicast(&self, ip: &str) {
        let msg = Message::RequestControl { from: self.inst.clone(), to: None, name: self.name.clone(), ws_host: primary_ip(), ws_port: self.ws_port, options: serde_json::json!({"map":"relative"}) };
        send_udp_json(ip, &msg);
    }

    fn send_response_unicast(&self, ip: &str, accepted: bool) {
        let msg = Message::ResponseControl { from: self.inst.clone(), accepted };
        send_udp_json(ip, &msg);
    }
}

fn send_udp_json(target_ip: &str, msg: &Message) {
    if let Ok(data) = serde_json::to_vec(msg) {
        if let Ok(sock) = UdpSocket::bind(SocketAddrV4::new(Ipv4Addr::UNSPECIFIED, 0)) {
            let _ = sock.send_to(&data, SocketAddrV4::new(target_ip.parse().unwrap_or(Ipv4Addr::LOCALHOST), 54545));
        }
    }
}

fn primary_ip() -> String {
    let s = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok();
    if let Some(s) = s { let _ = s.connect((Ipv4Addr::new(8,8,8,8),80)); if let Ok(addr)=s.local_addr(){ return addr.ip().to_string(); } }
    "127.0.0.1".to_string()
}

impl eframe::App for UiApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll_events();
        egui::TopBottomPanel::top("top").show(ctx, |ui| {
            ui.heading("Controll - Devices");
            ui.label(&self.status);
        });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                egui::ScrollArea::vertical().show(ui, |ui| {
                    for (i, d) in self.devices.iter().enumerate() {
                        let selected = self.selected == Some(i);
                        if ui.selectable_label(selected, format!("{} {}:{}", d.name, d.ip, d.ws_port)).clicked() {
                            self.selected = Some(i);
                        }
                    }
                });
                ui.vertical(|ui| {
                    if ui.button("Request Control").clicked() {
                        if let Some(i) = self.selected { if let Some(d) = self.devices.get(i) { self.send_request_unicast(&d.ip); self.status = format!("Requested {}", d.name); } }
                    }
                    let mut action: Option<(String, bool)> = None;
                    if let Some((from_name, ws_host, _ws_port)) = self.incoming.clone() {
                        ui.separator();
                        ui.label(format!("{} requests control", from_name));
                        if ui.button("Accept").clicked() { action = Some((ws_host.clone(), true)); }
                        if ui.button("Decline").clicked() { action = Some((ws_host.clone(), false)); }
                    }
                    if let Some((host, accepted)) = action { self.send_response_unicast(&host, accepted); self.incoming = None; }
                });
            });
        });
        ctx.request_repaint_after(std::time::Duration::from_millis(100));
    }
}
