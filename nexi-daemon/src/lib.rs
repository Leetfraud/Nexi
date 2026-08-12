use serde::{Deserialize, Serialize};

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