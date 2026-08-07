use rdev::{listen, Event, EventType};
use chrono::Utc;
use sled::Db;
use std::sync::{Arc, Mutex};
use std::net::{TcpListener, TcpStream};
use std::io::Write;
use std::thread;
use winapi::shared::minwindef::{DWORD, MAX_PATH};
use winapi::um::processthreadsapi::OpenProcess;
use winapi::um::winuser::{GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId};
use winapi::um::psapi::GetModuleFileNameExW;
use nexi_daemon::InputEvent;

type Clients = Arc<Mutex<Vec<TcpStream>>>;

fn get_active_window() -> (String, String) {
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.is_null() {
            return ("unknown".into(), "unknown".into());
        }

        // Get window title
        let mut title_buf = [0u16; 512];
        GetWindowTextW(hwnd, title_buf.as_mut_ptr(), 512);
        let title = String::from_utf16_lossy(
            &title_buf[..title_buf.iter().position(|&c| c == 0).unwrap_or(512)]
        );

        // Get process name
        let mut pid: DWORD = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        let handle = OpenProcess(0x0400 | 0x0010, 0, pid);
        if handle.is_null() {
            return (title, "unknown".into());
        }

        let mut proc_buf = [0u16; 512];
        GetModuleFileNameExW(handle, std::ptr::null_mut(), proc_buf.as_mut_ptr(), 512);
        let proc_path = String::from_utf16_lossy(
            &proc_buf[..proc_buf.iter().position(|&c| c == 0).unwrap_or(512)]
        );

        let proc_name = proc_path
            .split('\\')
            .last()
            .unwrap_or("unknown")
            .to_string();

        (title, proc_name)
    }
}

fn handle_event(event: Event, db: Arc<Mutex<Db>>, clients: Clients) {
    let now = Utc::now().to_rfc3339();
    let (window_title, process_name) = get_active_window();

    let input = match event.event_type {
        EventType::MouseMove { x, y } => InputEvent {
            event_type: "mouse_move".into(),
            x: Some(x),
            y: Some(y),
            button: None,
            key: None,
            timestamp: now.clone(),
            window_title,
            process_name,
        },
        EventType::ButtonPress(btn) => InputEvent {
            event_type: "mouse_click".into(),
            x: None,
            y: None,
            button: Some(format!("{:?}", btn)),
            key: None,
            timestamp: now.clone(),
            window_title,
            process_name,
        },
        EventType::KeyPress(key) => InputEvent {
            event_type: "key_press".into(),
            x: None,
            y: None,
            button: None,
            key: Some(format!("{:?}", key)),
            timestamp: now.clone(),
            window_title,
            process_name,
        },
        _ => return,
    };

    let json = serde_json::to_string(&input).unwrap() + "\n";

    let db = db.lock().unwrap();
    db.insert(now.as_bytes(), json.as_bytes()).unwrap();
    db.flush().unwrap();
    drop(db);

    let mut clients = clients.lock().unwrap();
    clients.retain_mut(|stream| {
        stream.write_all(json.as_bytes()).is_ok()
    });
}

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();
    let db = Arc::new(Mutex::new(db));
    let clients: Clients = Arc::new(Mutex::new(Vec::new()));

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

    println!("Capturing input events with window context...");
    if let Err(e) = listen(move |event| {
        handle_event(event, Arc::clone(&db_clone), Arc::clone(&clients_clone))
    }) {
        eprintln!("Error: {:?}", e);
    }
}