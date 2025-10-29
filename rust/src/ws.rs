use futures::{SinkExt, StreamExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::{accept_async, connect_async, tungstenite::protocol::Message as WsMsg};
use serde_json::Value;
use enigo::{Enigo, Mouse, Settings, Coordinate};

pub async fn run_ws_server(host: &str, port: u16) -> anyhow::Result<()> {
    let addr = format!("{}:{}", host, port);
    let listener = TcpListener::bind(&addr).await?;
    println!("[ws] server listening on ws://{}", addr);
    loop {
        let (stream, peer) = listener.accept().await?;
        println!("[ws] tcp accepted from {}", peer);
        tokio::spawn(async move {
            if let Err(e) = handle_ws_conn(stream).await {
                eprintln!("[ws] conn error: {e}");
            }
        });
    }
}

async fn handle_ws_conn(stream: TcpStream) -> anyhow::Result<()> {
    let mut ws = accept_async(stream).await?;
    while let Some(msg) = ws.next().await {
        match msg {
            Ok(WsMsg::Text(t)) => {
                if let Ok(v) = serde_json::from_str::<Value>(&t) {
                    if v.get("type").and_then(|s| s.as_str()) == Some("mouse_move") {
                        let x = v.get("x").and_then(|n| n.as_i64()).unwrap_or(0) as i32;
                        let y = v.get("y").and_then(|n| n.as_i64()).unwrap_or(0) as i32;
                        // Create Enigo inside the per-message scope so it doesn't cross an await
                        if let Ok(mut enigo) = Enigo::new(&Settings::default()) {
                            let _ = enigo.move_mouse(x, y, Coordinate::Abs);
                        }
                    }
                }
            }
            Ok(WsMsg::Close(_)) => break,
            Ok(_) => {}
            Err(e) => { eprintln!("[ws] recv err: {e}"); break; }
        }
    }
    Ok(())
}

pub async fn run_ws_client(url: &str) -> anyhow::Result<()> {
    println!("[ws] connecting to {}", url);
    let (mut ws, _resp) = connect_async(url).await?;
    ws.send(WsMsg::Text("ping".into())).await.ok();
    if let Some(Ok(msg)) = ws.next().await { println!("[ws] got: {:?}", msg); }
    Ok(())
}
