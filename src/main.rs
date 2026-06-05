use rdev::{listen, Event, EventType};
use serde::{Deserialize, Serialize};
use chrono::Utc;
use sled::Db;
use std::sync::{Arc, Mutex};
use std::net::{TcpListener, TcpStream};
use std::io::Write;
use std::thread;

#[derive(Serialize, Deserialize, Debug, Clone)]
struct InputEvent {
    event_type: String,
    x: Option<f64>,
    y: Option<f64>,
    button: Option<String>,
    key: Option<String>,
    timestamp: String,
}

type Clients = Arc<Mutex<Vec<TcpStream>>>;

fn handle_event(event: Event, db: Arc<Mutex<Db>>, clients: Clients) {
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

    let json = serde_json::to_string(&input).unwrap() + "\n";

    // Write to database
    let db = db.lock().unwrap();
    db.insert(now.as_bytes(), json.as_bytes()).unwrap();
    db.flush().unwrap();
    drop(db);

    // Stream to all connected Python clients
    let mut clients = clients.lock().unwrap();
    clients.retain_mut(|stream| {
        stream.write_all(json.as_bytes()).is_ok()
    });
}

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();
    let db = Arc::new(Mutex::new(db));
    let clients: Clients = Arc::new(Mutex::new(Vec::new()));

    // Start TCP socket server on port 9000
    let listener = TcpListener::bind("127.0.0.1:9000").unwrap();
    println!("Nexi daemon listening on 127.0.0.1:9000");

    let clients_clone = Arc::clone(&clients);
    thread::spawn(move || {
        for stream in listener.incoming() {
            match stream {
                Ok(s) => {
                    println!("Python client connected");
                    clients_clone.lock().unwrap().push(s);
                }
                Err(e) => eprintln!("Connection error: {}", e),
            }
        }
    });

    let db_clone = Arc::clone(&db);
    let clients_clone = Arc::clone(&clients);

    println!("Capturing input events...");
    if let Err(e) = listen(move |event| {
        handle_event(event, Arc::clone(&db_clone), Arc::clone(&clients_clone))
    }) {
        eprintln!("Error: {:?}", e);
    }
}