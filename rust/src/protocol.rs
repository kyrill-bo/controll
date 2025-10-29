use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(tag = "type")]
pub enum Message {
    BEACON {
        instance_id: String,
        name: String,
        ip: String,
        ws_port: u16,
        version: u32,
    },
    RequestControl {
        from: String,
        to: Option<String>,
        name: String,
        ws_host: String,
        ws_port: u16,
        options: serde_json::Value,
    },
    ResponseControl {
        from: String,
        accepted: bool,
    },
}
