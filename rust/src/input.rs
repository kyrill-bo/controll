use futures::SinkExt;
use rdev::{Event, EventType, Key};

use crate::state::set_capture;

pub fn run_capture_client(url: String) {
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
    std::thread::spawn(move || {
        if let Ok(rt) = tokio::runtime::Runtime::new() {
            rt.block_on(async move {
                if let Ok((mut ws, _)) = tokio_tungstenite::connect_async(&url).await {
                    while let Some(msg) = rx.recv().await {
                        let _ = ws.send(tokio_tungstenite::tungstenite::protocol::Message::Text(msg)).await;
                    }
                }
            });
        }
    });

    let capturing = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let capturing_cb = capturing.clone();

    // Global grab: suppress local when capturing (toggle on F12)
    let _ = rdev::grab(move |event: Event| {
        match event.event_type {
            EventType::KeyPress(k) => {
                // Toggle on F13 (macOS keycode 105). Fallback: also accept F12.
                let mut is_f13 = false;
                #[allow(unused_mut)]
                let mut code_opt: Option<u32> = None;
                if let Key::Unknown(c) = k { code_opt = Some(c); }
                #[cfg(target_os = "macos")]
                { if let Some(c) = code_opt { if c == 105 { is_f13 = true; } } }
                if is_f13 || matches!(k, Key::F12) {
                    let now = !capturing_cb.load(std::sync::atomic::Ordering::Relaxed);
                    capturing_cb.store(now, std::sync::atomic::Ordering::Relaxed);
                    return Some(event);
                }
            }
            EventType::MouseMove { x, y } => {
                if capturing_cb.load(std::sync::atomic::Ordering::Relaxed) {
                    let payload = serde_json::json!({ "type": "mouse_move", "x": x as i32, "y": y as i32 }).to_string();
                    let _ = tx.send(payload);
                    return None; // suppress locally
                }
            }
            _ => {
                if capturing_cb.load(std::sync::atomic::Ordering::Relaxed) { return None; }
            }
        }
        Some(event)
    });
}
