use nexi_daemon::InputEvent;
use sled::Db;
use chrono::{DateTime, Utc};
use std::collections::{HashMap, HashSet};

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

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
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


const MIN_PATTERN_LEN: usize = 3;
const MAX_PATTERN_LEN: usize = 8;
const MIN_OCCURRENCES: usize = 3;
const MIN_SESSIONS: usize = 2;

#[derive(Debug)]
struct WorkflowPattern {
    tokens: Vec<Token>,
    occurrences: usize,
    session_count: usize,
}

/// Stage 4: slide windows of length MIN_PATTERN_LEN..=MAX_PATTERN_LEN over
/// every session's token sequence, count how often each exact window
/// recurs, and in how many distinct sessions. Only keeps sequences that
/// clear both MIN_OCCURRENCES and MIN_SESSIONS — a pattern that repeated
/// 5 times in one session but never appeared elsewhere isn't a workflow,
/// it's a one-off habit from that sitting.
fn mine_patterns(sessions: &[Vec<Token>]) -> Vec<WorkflowPattern> {
    let mut counts: HashMap<Vec<Token>, (usize, HashSet<usize>)> = HashMap::new();

    for (session_idx, tokens) in sessions.iter().enumerate() {
        for window_len in MIN_PATTERN_LEN..=MAX_PATTERN_LEN {
            if tokens.len() < window_len {
                continue;
            }
            for start in 0..=(tokens.len() - window_len) {
                let window = tokens[start..start + window_len].to_vec();
                let entry = counts.entry(window).or_insert_with(|| (0, HashSet::new()));
                entry.0 += 1;
                entry.1.insert(session_idx);
            }
        }
    }

    let mut patterns: Vec<WorkflowPattern> = counts
        .into_iter()
        .filter(|(_, (count, session_set))| {
            *count >= MIN_OCCURRENCES && session_set.len() >= MIN_SESSIONS
        })
        .map(|(tokens, (count, session_set))| WorkflowPattern {
            tokens,
            occurrences: count,
            session_count: session_set.len(),
        })
        .collect();

    patterns.sort_by(|a, b| b.occurrences.cmp(&a.occurrences));
    patterns
}

    /// True if `needle` appears as a contiguous subsequence anywhere in
/// `haystack`.
fn contains_subsequence(haystack: &[Token], needle: &[Token]) -> bool {
    if needle.len() > haystack.len() {
        return false;
    }
    haystack.windows(needle.len()).any(|w| w == needle)
}

/// Drops any pattern that's fully contained, as a contiguous subsequence,
/// inside a longer pattern that also survived thresholding. A 3-token
/// fragment of a real 6-token workflow isn't a separate pattern — it's
/// noise from mine_patterns scanning every window length independently.
/// Once the full 6-token version exists, the fragment is discarded.
fn dedupe_maximal(mut patterns: Vec<WorkflowPattern>) -> Vec<WorkflowPattern> {
    // Longest first, so every fragment gets checked against the fullest
    // version already accepted before we decide to drop it.
    patterns.sort_by(|a, b| b.tokens.len().cmp(&a.tokens.len()));

    let mut kept: Vec<WorkflowPattern> = Vec::new();

    'outer: for candidate in patterns {
        for existing in &kept {
            if existing.tokens.len() > candidate.tokens.len()
                && contains_subsequence(&existing.tokens, &candidate.tokens)
            {
                continue 'outer; // candidate is a fragment of something already kept
            }
        }
        kept.push(candidate);
    }

    kept.sort_by(|a, b| b.occurrences.cmp(&a.occurrences));
    kept
}

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();

    let raw = load_events(&db);
    println!("Loaded {} events", raw.len());

    let filtered = filter_noise(raw);
    println!("{} events after dropping mouse_move", filtered.len());

    let sessions = segment_sessions(filtered);
    println!("Segmented into {} sessions", sessions.len());

    let mut all_sessions: Vec<Vec<Token>> = Vec::new();

for (i, session) in sessions.iter().enumerate() {
    let tokens = abstract_session(session);
    println!(
        "\nSession {} ({} events -> {} tokens):",
        i, session.events.len(), tokens.len()
    );
    for token in &tokens {
        println!("  {:?}", token);
    }
    all_sessions.push(tokens);
}

let patterns = dedupe_maximal(mine_patterns(&all_sessions));
println!("\n=== {} recurring patterns found ===", patterns.len());
for p in &patterns {
    println!(
        "  [{}x across {} sessions] {:?}",
        p.occurrences, p.session_count, p.tokens
    );
}
}