use rdev::{listen, Event, EventType};
use chrono::Utc;
use sled::Db;
use std::sync::{Arc, Mutex};
use std::net::{TcpListener, TcpStream};
use std::io::Write;
use std::thread;
use winapi::shared::minwindef::DWORD;
use winapi::um::processthreadsapi::OpenProcess;
use winapi::um::winuser::{GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId, GetWindowRect};
use winapi::shared::windef::RECT;
use winapi::um::psapi::GetModuleFileNameExW;
use nexi_daemon::InputEvent;

type Clients = Arc<Mutex<Vec<TcpStream>>>;
type LastPos = Arc<Mutex<(f64, f64)>>;
type WindowRect = Arc<Mutex<RECT>>;

fn get_active_window() -> (String, String, f64, f64, f64, f64) {
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.is_null() {
            return ("unknown".into(), "unknown".into(), 0.0, 0.0, 0.0, 0.0);
        }
    

        let mut rect: RECT = std::mem::zeroed();
        GetWindowRect(hwnd, &mut rect);
        let win_left = rect.left as f64;
        let win_top = rect.top as f64;
        let win_width = (rect.right - rect.left) as f64;
        let win_height = (rect.bottom - rect.top) as f64;

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
            return (title, "unknown".into(), win_left, win_top, win_width, win_height);
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

        (title, proc_name, win_left, win_top, win_width, win_height)
}
}

fn handle_event(event: Event, db: Arc<Mutex<Db>>, clients: Clients, last_pos: LastPos) {
    let now = Utc::now().to_rfc3339();
    let (window_title, process_name, win_left, win_top, win_width, win_height) = get_active_window();

    let rel = |x: f64, y: f64| -> (Option<f64>, Option<f64>) {
        if win_width > 0.0 && win_height > 0.0 {
            (Some((x - win_left) / win_width), Some((y - win_top) / win_height))
        } else {
            (None, None)
        }
    };

    let input = match event.event_type {
        EventType::MouseMove { x, y } => {
            *last_pos.lock().unwrap() = (x, y);
            let (rel_x, rel_y) = rel(x, y);
            InputEvent {
                event_type: "mouse_move".into(),
                x: Some(x),
                y: Some(y),
                button: None,
            key: None,
            timestamp: now.clone(),
            window_title,
            process_name,
            window_left: win_left,
            window_top: win_top,
            window_width: win_width,
            window_height: win_height,
            rel_x,
            rel_y,
        }
    }

        EventType::ButtonPress(btn) => {
        let (x,y)  = *last_pos.lock().unwrap();
        let (rel_x, rel_y) = rel(x, y);
        InputEvent {
            event_type: "mouse_click".into(),
            x: Some(x),
            y: Some(y),
            button: Some(format!("{:?}", btn)),
            key: None,
            timestamp: now.clone(),
            window_title,
            process_name,
            window_left: win_left,
            window_top: win_top,
            window_width: win_width,
            window_height: win_height,
            rel_x,
            rel_y,
        }
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
            window_left: win_left,
            window_top: win_top,
            window_width: win_width,
            window_height: win_height,
            rel_x: None,
            rel_y: None,
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
    let last_pos: LastPos = Arc::new(Mutex::new((0.0, 0.0)));

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
    let last_pos_clone = Arc::clone(&last_pos);

    println!("Capturing input events with window context...");
    if let Err(e) = listen(move |event| {
        handle_event(event, Arc::clone(&db_clone), Arc::clone(&clients_clone), Arc::clone(&last_pos_clone));
    }) {
        eprintln!("Error: {:?}", e);
    }
}