controll-rs (prototype)

A minimal Rust prototype of the discovery/request flow for your KVM tool.

Build and run:
  cd rust
  cargo run -- run
  cargo run -- list
  cargo run -- request <ip>
  cargo run -- ws-server 0.0.0.0 8765
  cargo run -- ws-client ws://127.0.0.1:8765
