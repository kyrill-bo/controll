use futures::{SinkExt, StreamExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::{accept_async, connect_async, tungstenite::protocol::Message as WsMsg};

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
    ws.send(WsMsg::Text("hello".into())).await.ok();
    while let Some(msg) = ws.next().await {
        match msg {
            Ok(m) => {
                let is_close = m.is_close();
                let should_echo = m.is_text() || m.is_binary();
                if should_echo {
                    ws.send(m).await.ok();
                }
                if is_close { break; }
            }
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
