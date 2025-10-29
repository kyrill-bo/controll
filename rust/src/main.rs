mod protocol;
mod discovery;
mod ws;
mod gui;
mod input;

use discovery::{run_loop_with_sender, DiscEvent};
use crate::discovery::Discovery;
use serde_json::json;
use std::env;
use uuid::Uuid;

fn usage() {
    eprintln!("Usage: controll-rs <cmd> [args]\n  run [ws_port]\n  list\n  request <ip> [ws_port]\n  ws-server [host] [port]\n  ws-client <ws://host:port>\n  gui [ws_port]\n");
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 { usage(); return; }
    match args[1].as_str() {
        "run" => {
            let ws_port: u16 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(8765);
            let inst = Uuid::new_v4().to_string();
            let name = hostname();
            // start WS server
            tokio::spawn(ws::run_ws_server("0.0.0.0", ws_port));
            // channel for discovery events
            let (tx, rx) = std::sync::mpsc::channel::<DiscEvent>();
            // spawn discovery loop in a thread
            let inst2 = inst.clone();
            let name2 = name.clone();
            std::thread::spawn(move || { let _ = run_loop_with_sender(inst2, name2, ws_port, Some(tx)); });
            // forward accepted responses into WS client connects
            let handle = tokio::runtime::Handle::current();
            std::thread::spawn(move || {
                while let Ok(ev) = rx.recv() {
                    match ev {
                        DiscEvent::ResponseAccepted { host, port } => {
                            let url = format!("ws://{}:{}", host, port);
                            handle.spawn(async move { let _ = crate::ws::run_ws_client(&url).await; });
                        }
                        _ => {}
                    }
                }
            });
            // keep process alive
            futures::future::pending::<()>().await;
        }
        "list" => {
            let ws_port: u16 = 8765;
            let inst = Uuid::new_v4().to_string();
            let name = hostname();
            let mut disc = Discovery::new(inst, name, ws_port).expect("init discovery");
            let mut last_beacon = std::time::Instant::now() - std::time::Duration::from_secs(2);
            let start = std::time::Instant::now();
            while start.elapsed().as_secs() < 5 { disc.tick(&mut last_beacon); }
            println!("discovered devices:");
            for (id, d) in disc.devices.iter() { println!("{} => {}:{} ({})", id, d.ip, d.ws_port, d.name); }
        }
        "request" => {
            if args.len() < 3 { usage(); return; }
            let ip = &args[2];
            let ws_port: u16 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(8765);
            let inst = Uuid::new_v4().to_string();
            let name = hostname();
            let disc = Discovery::new(inst, name, ws_port).expect("init discovery");
            disc.send_request(ip, json!({"map":"relative"}), None);
            std::thread::sleep(std::time::Duration::from_secs(2));
        }
        "ws-server" => {
            let host = args.get(2).map(String::as_str).unwrap_or("0.0.0.0");
            let port: u16 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(8765);
            if let Err(e) = ws::run_ws_server(host, port).await { eprintln!("error: {e}"); }
        }
        "ws-client" => {
            if args.len() < 3 { usage(); return; }
            let url = &args[2];
            if let Err(e) = ws::run_ws_client(url).await { eprintln!("error: {e}"); }
        }
        "gui" => {
            let ws_port: u16 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(8765);
            let inst = Uuid::new_v4().to_string();
            let name = hostname();
            tokio::spawn(ws::run_ws_server("0.0.0.0", ws_port));
            let (tx, rx) = std::sync::mpsc::channel::<DiscEvent>();
            let inst2 = inst.clone();
            let name2 = name.clone();
            std::thread::spawn(move || { let _ = discovery::run_loop_with_sender(inst2, name2, ws_port, Some(tx)); });
            let native_options = eframe::NativeOptions::default();
            let app = gui::UiApp::new(rx, ws_port, inst, name);
            let _ = eframe::run_native("Controll", native_options, Box::new(|_| Ok::<Box<dyn eframe::App>, Box<dyn std::error::Error + Send + Sync>>(Box::new(app))));            
        }
        _ => usage(),
    }
}

fn hostname() -> String { hostname::get().ok().and_then(|s| s.into_string().ok()).unwrap_or_else(|| "host".to_string()) }
