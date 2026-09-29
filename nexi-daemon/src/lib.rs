use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Shared location of the daemon's recorded events.
const EVENTS_DB_PATH: &str =
    "D:/Project 5/Nexi/nexi-daemon/nexi_events.db";

pub fn events_db_path() -> PathBuf {
    PathBuf::from(EVENTS_DB_PATH)
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct InputEvent {
    pub event_type: String,
    pub x: Option<f64>,
    pub y: Option<f64>,
    pub button: Option<String>,
    pub key: Option<String>,
    pub timestamp: String,
    #[serde(default)]
    pub window_title: String,
    #[serde(default)]
    pub process_name: String,
    #[serde(default)]
    pub window_left: f64,
    #[serde(default)]
    pub window_top: f64,
    #[serde(default)]
    pub window_width: f64,
    #[serde(default)]
    pub window_height: f64,
    pub rel_x: Option<f64>,
    pub rel_y: Option<f64>,
}
