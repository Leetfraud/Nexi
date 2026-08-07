use nexi_daemon::InputEvent;
use sled::Db;
use chrono::{DateTime, Utc};

/// Gap (in seconds) after which we consider the user to have stepped
/// away, and start a new session.
const SESSION_GAP_SECS: i64 = 30;

/// Gap (in seconds) within which consecutive key_press events in the
/// same process are collapsed into a single Type token.
const TYPING_BURST_GAP_SECS: i64 = 2;

#[derive(Debug)]
struct Session {
    events: Vec<InputEvent>,
}

#[derive(Debug, Clone)]
enum Token {
    Switch(String),
    Click(String),
    Type(String),
}

fn parse_ts(ts: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(ts)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
}

/// Reads every event out of sled, parses it, and returns them sorted
/// chronologically. Unparsable entries are logged and skipped rather
/// than failing the whole run.
fn load_events(db: &Db) -> Vec<InputEvent> {
    let mut events: Vec<InputEvent> = db
        .iter()
        .filter_map(|item| item.ok())
        .filter_map(|(_, value)| {
            let json = String::from_utf8(value.to_vec()).ok()?;
            match serde_json::from_str::<InputEvent>(&json) {
                Ok(event) => Some(event),
                Err(e) => {
                    eprintln!("Skipping unparsable event: {}", e);
                    None
                }
            }
        })
        .collect();

    events.sort_by_key(|e| parse_ts(&e.timestamp));
    events
}

/// Stage 1: drop mouse_move entirely. It fires far too often to carry
/// workflow signal and would dominate every downstream stage.
fn filter_noise(events: Vec<InputEvent>) -> Vec<InputEvent> {
    events
        .into_iter()
        .filter(|e| e.event_type != "mouse_move")
        .collect()
}

/// Stage 2: split into sessions purely on idle time. App switches are
/// NOT a session boundary — they're meaningful workflow content,
/// captured later as Switch tokens.
fn segment_sessions(events: Vec<InputEvent>) -> Vec<Session> {
    let mut sessions = Vec::new();
    let mut current: Vec<InputEvent> = Vec::new();
    let mut last_time: Option<DateTime<Utc>> = None;

    for event in events {
        let ts = parse_ts(&event.timestamp);

        if let (Some(t), Some(last)) = (ts, last_time) {
            let gap = (t - last).num_seconds();
            if gap > SESSION_GAP_SECS && !current.is_empty() {
                sessions.push(Session {
                    events: std::mem::take(&mut current),
                });
            }
        }

        last_time = ts.or(last_time);
        current.push(event);
    }

    if !current.is_empty() {
        sessions.push(Session { events: current });
    }

    sessions
}

/// Stage 3: turn one session's raw events into a compact token
/// sequence: Switch when focus changes, Click per click, and Type
/// tokens that absorb runs of same-app keypresses within
/// TYPING_BURST_GAP_SECS of each other.
fn abstract_session(session: &Session) -> Vec<Token> {
    let mut tokens = Vec::new();
    let mut last_process: Option<String> = None;
    let mut typing: Option<(String, DateTime<Utc>)> = None;

    for event in &session.events {
        if last_process.as_deref() != Some(event.process_name.as_str()) {
            tokens.push(Token::Switch(event.process_name.clone()));
            last_process = Some(event.process_name.clone());
            typing = None; // a switch always ends any active typing burst
        }

        match event.event_type.as_str() {
            "mouse_click" => {
                typing = None; // a click always ends any active typing burst
                let button = event.button.clone().unwrap_or_else(|| "unknown".into());
                tokens.push(Token::Click(button));
            }
            "key_press" => {
                let now = parse_ts(&event.timestamp);
                let extend = match (&typing, now) {
                    (Some((proc, last_time)), Some(t)) => {
                        proc == &event.process_name
                            && (t - *last_time).num_seconds() <= TYPING_BURST_GAP_SECS
                    }
                    _ => false,
                };

                if extend {
                    if let (Some((_, last_time)), Some(t)) = (&mut typing, now) {
                        *last_time = t;
                    }
                } else {
                    tokens.push(Token::Type(event.process_name.clone()));
                    if let Some(t) = now {
                        typing = Some((event.process_name.clone(), t));
                    }
                }
            }
            _ => {}
        }
    }

    tokens
}

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();

    let raw = load_events(&db);
    println!("Loaded {} events", raw.len());

    let filtered = filter_noise(raw);
    println!("{} events after dropping mouse_move", filtered.len());

    let sessions = segment_sessions(filtered);
    println!("Segmented into {} sessions", sessions.len());

    for (i, session) in sessions.iter().enumerate() {
        let tokens = abstract_session(session);
        println!(
            "\nSession {} ({} events -> {} tokens):",
            i,
            session.events.len(),
            tokens.len()
        );
        for token in &tokens {
            println!("  {:?}", token);
        }
    }
}