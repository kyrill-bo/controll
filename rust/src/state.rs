use std::sync::atomic::{AtomicBool, Ordering};
use once_cell::sync::Lazy;

pub static CAPTURE_ON: Lazy<AtomicBool> = Lazy::new(|| AtomicBool::new(false));

pub fn set_capture(on: bool) {
    CAPTURE_ON.store(on, Ordering::Relaxed);
}

pub fn is_capture_on() -> bool {
    CAPTURE_ON.load(Ordering::Relaxed)
}
