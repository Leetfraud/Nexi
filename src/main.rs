use rdev::{listen, Event, EventType};
use serde::{Deserialize, Serialize};
use chrono::Utc;
use sled::Db;
use std::sync::{Arc, Mutex};

#[derive(Serialize, Deserialize, Debug)]
struct InputEvent {
    event_type: String,
    x: Option<f64>,
    y: Option<f64>,
    button: Option<String>,
    key: Option<String>,
    timestamp: String,
}

fn handle_event(event: Event, db: Arc<Mutex<Db>>) {
    let now = Utc::now().to_rfc3339();

    let input = match event.event_type {
        EventType::MouseMove { x, y } => InputEvent {
            event_type: "mouse_move".into(),
            x: Some(x),
            y: Some(y),
            button: None,
            key: None,
            timestamp: now.clone(),
        },
        EventType::ButtonPress(btn) => InputEvent {
            event_type: "mouse_click".into(),
            x: None,
            y: None,
            button: Some(format!("{:?}", btn)),
            key: None,
            timestamp: now.clone(),
        },
        EventType::KeyPress(key) => InputEvent {
            event_type: "key_press".into(),
            x: None,
            y: None,
            button: None,
            key: Some(format!("{:?}", key)),
            timestamp: now.clone(),
        },
        _ => return,
    };

    let json = serde_json::to_string(&input).unwrap();
    println!("{}", json);

    let db = db.lock().unwrap();
    db.insert(now.as_bytes(), json.as_bytes()).unwrap();
    db.flush().unwrap();
}

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();
    let db = Arc::new(Mutex::new(db));
    let db_clone = Arc::clone(&db);

    println!("Nexi daemon started — listening and storing input events...");

    if let Err(e) = listen(move |event| handle_event(event, Arc::clone(&db_clone))) {
        eprintln!("Error: {:?}", e);
    }
}