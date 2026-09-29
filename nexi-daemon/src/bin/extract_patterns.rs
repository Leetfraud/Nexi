use chrono::{DateTime, Utc};
use nexi_daemon::{events_db_path, InputEvent};
use serde::{Deserialize, Serialize};
use sled::Db;
use std::collections::{HashMap, HashSet};
use std::{error::Error, fs, path::Path};

/// Keep the actual sled key, rather than assuming it equals the timestamp.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct SourceEvent {
    db_key: Vec<u8>,
    event: InputEvent,
}

impl std::ops::Deref for SourceEvent {
    type Target = InputEvent;
    fn deref(&self) -> &InputEvent {
        &self.event
    }
}

#[derive(Debug)]
struct AbstractedSession {
    tokens: Vec<Token>,
    // Half-open ranges into the filtered session events, one per token.
    spans: Vec<std::ops::Range<usize>>,
}

/// Gap (in seconds) after which we consider the user to have stepped
/// away, and start a new session.
const SESSION_GAP_SECS: i64 = 30;

/// Gap (in seconds) within which consecutive key_press events in the
/// same process are collapsed into a single Type token.
const TYPING_BURST_GAP_SECS: i64 = 2;

#[derive(Debug)]
struct Session {
    events: Vec<SourceEvent>,
}

/// Coarse 3x3 grid position of a click within its window's bounding
/// box. Computed from window-relative coordinates (rel_x, rel_y) so it
/// stays stable across window moves and resizes, rather than raw
/// screen pixels. Unknown covers events with no rect data.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
enum Bucket {
    TopLeft,
    TopCenter,
    TopRight,
    MidLeft,
    MidCenter,
    MidRight,
    BottomLeft,
    BottomCenter,
    BottomRight,
    Unknown,
}

fn bucket(rel_x: Option<f64>, rel_y: Option<f64>) -> Bucket {
    let (Some(x), Some(y)) = (rel_x, rel_y) else {
        return Bucket::Unknown;
    };
    let x = x.clamp(0.0, 1.0);
    let y = y.clamp(0.0, 1.0);

    let col = if x < 1.0 / 3.0 {
        0
    } else if x < 2.0 / 3.0 {
        1
    } else {
        2
    };
    let row = if y < 1.0 / 3.0 {
        0
    } else if y < 2.0 / 3.0 {
        1
    } else {
        2
    };

    match (row, col) {
        (0, 0) => Bucket::TopLeft,
        (0, 1) => Bucket::TopCenter,
        (0, 2) => Bucket::TopRight,
        (1, 0) => Bucket::MidLeft,
        (1, 1) => Bucket::MidCenter,
        (1, 2) => Bucket::MidRight,
        (2, 0) => Bucket::BottomLeft,
        (2, 1) => Bucket::BottomCenter,
        _ => Bucket::BottomRight,
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
enum Token {
    Switch(String),
    Click(String, Bucket),
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
fn load_events(db: &Db) -> Result<Vec<SourceEvent>, sled::Error> {
    let mut events: Vec<SourceEvent> = db
        .iter()
        .map(|item| {
            let (key, value) = item?;
            Ok(match serde_json::from_slice::<InputEvent>(&value) {
                Ok(event) => Some(SourceEvent {
                    db_key: key.to_vec(),
                    event,
                }),
                Err(e) => {
                    eprintln!("Skipping unparsable event: {}", e);
                    None
                }
            })
        })
        .collect::<Result<Vec<_>, sled::Error>>()?
        .into_iter()
        .flatten()
        .collect();

    events.sort_by_key(|e| parse_ts(&e.timestamp));
    Ok(events)
}

/// Stage 1: drop mouse_move entirely. It fires far too often to carry
/// workflow signal and would dominate every downstream stage.
fn filter_noise(events: Vec<SourceEvent>) -> Vec<SourceEvent> {
    events
        .into_iter()
        .filter(|e| e.event_type != "mouse_move")
        .collect()
}

/// Stage 2: split into sessions purely on idle time. App switches are
/// NOT a session boundary — they're meaningful workflow content,
/// captured later as Switch tokens.
fn segment_sessions(events: Vec<SourceEvent>) -> Vec<Session> {
    let mut sessions = Vec::new();
    let mut current: Vec<SourceEvent> = Vec::new();
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
fn abstract_session(session: &Session) -> AbstractedSession {
    let mut tokens = Vec::new();
    let mut spans: Vec<std::ops::Range<usize>> = Vec::new();
    let mut last_process: Option<String> = None;
    let mut typing: Option<(String, DateTime<Utc>)> = None;

    for (index, event) in session.events.iter().enumerate() {
        if last_process.as_deref() != Some(event.process_name.as_str()) {
            tokens.push(Token::Switch(event.process_name.clone()));
            spans.push(index..index + 1);
            last_process = Some(event.process_name.clone());
            typing = None; // a switch always ends any active typing burst
        }

        match event.event_type.as_str() {
            "mouse_click" => {
                typing = None; // a click always ends any active typing burst
                let button = event.button.clone().unwrap_or_else(|| "unknown".into());
                let b = bucket(event.rel_x, event.rel_y);
                tokens.push(Token::Click(button, b));
                spans.push(index..index + 1);
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
                    spans.last_mut().unwrap().end = index + 1;
                    if let (Some((_, last_time)), Some(t)) = (&mut typing, now) {
                        *last_time = t;
                    }
                } else {
                    tokens.push(Token::Type(event.process_name.clone()));
                    spans.push(index..index + 1);
                    typing = None;
                    if let Some(t) = now {
                        typing = Some((event.process_name.clone(), t));
                    }
                }
            }
            _ => {}
        }
    }

    AbstractedSession { tokens, spans }
}

const MIN_PATTERN_LEN: usize = 3;
const MAX_PATTERN_LEN: usize = 8;
const MIN_OCCURRENCES: usize = 3;
const MIN_SESSIONS: usize = 2;

#[derive(Debug, Serialize, Deserialize)]
struct WorkflowPattern {
    id: String,
    name: String,
    tokens: Vec<Token>,
    occurrences: usize,
    session_count: usize,
    matches: Vec<PatternMatch>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PatternMatch {
    session_index: usize,
    token_start: usize,
    token_end: usize,
    event_start: usize,
    event_end: usize,
    source_events: Vec<SourceEvent>,
}

#[derive(Serialize, Deserialize)]
struct PatternExport {
    schema_version: u32,
    generated_at: String,
    source_db: String,
    patterns: Vec<WorkflowPattern>,
}

/// Stage 4: slide windows of length MIN_PATTERN_LEN..=MAX_PATTERN_LEN over
/// every session's token sequence, count how often each exact window
/// recurs, and in how many distinct sessions. Only keeps sequences that
/// clear both MIN_OCCURRENCES and MIN_SESSIONS — a pattern that repeated
/// 5 times in one session but never appeared elsewhere isn't a workflow,
/// it's a one-off habit from that sitting.
fn mine_patterns(sessions: &[AbstractedSession]) -> Vec<WorkflowPattern> {
    let mut counts: HashMap<Vec<Token>, (usize, HashSet<usize>)> = HashMap::new();

    for (session_idx, session) in sessions.iter().enumerate() {
        let tokens = &session.tokens;
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
            id: String::new(),
            name: tokens
                .iter()
                .map(|t| match t {
                    Token::Switch(p) => format!("Switch to {p}"),
                    Token::Click(b, position) => format!("Click {b} {position:?}"),
                    Token::Type(p) => format!("Type in {p}"),
                })
                .collect::<Vec<_>>()
                .join(" -> "),
            matches: Vec::new(),
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

/// Token encoding gives collision-free IDs independent of ranking and run order.
fn pattern_id(tokens: &[Token]) -> String {
    let bytes = serde_json::to_vec(tokens).expect("tokens serialize to JSON");
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!("pattern_v1_{hex}")
}

fn attach_sources(
    patterns: &mut [WorkflowPattern],
    sessions: &[Session],
    abstracted: &[AbstractedSession],
) {
    for pattern in patterns {
        pattern.id = pattern_id(&pattern.tokens);
        for (session_index, session) in abstracted.iter().enumerate() {
            for (start, window) in session.tokens.windows(pattern.tokens.len()).enumerate() {
                if window != pattern.tokens {
                    continue;
                }
                let end = start + window.len();
                let event_start = session.spans[start].start;
                let event_end = session.spans[end - 1].end;
                pattern.matches.push(PatternMatch {
                    session_index,
                    token_start: start,
                    token_end: end,
                    event_start,
                    event_end,
                    source_events: sessions[session_index].events[event_start..event_end].to_vec(),
                });
            }
        }
    }
}

/// Preserve edited names for patterns still found. Invalid exports are never overwritten.
fn save_patterns(
    path: &Path,
    source_db: &Path,
    mut patterns: Vec<WorkflowPattern>,
) -> Result<(), Box<dyn Error>> {
    match fs::read(path) {
        Ok(bytes) => {
            let previous: PatternExport = serde_json::from_slice(&bytes)?;
            if previous.schema_version != 1 || previous.source_db != source_db.to_string_lossy() {
                return Err(
                    "existing export has a different schema version or source database".into(),
                );
            }
            let names: HashMap<_, _> = previous
                .patterns
                .into_iter()
                .map(|p| (p.tokens, p.name))
                .collect();
            for pattern in &mut patterns {
                if let Some(name) = names.get(&pattern.tokens) {
                    pattern.name = name.clone();
                }
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    patterns.sort_by(|a, b| b.occurrences.cmp(&a.occurrences).then(a.id.cmp(&b.id)));
    let export = PatternExport {
        schema_version: 1,
        generated_at: Utc::now().to_rfc3339(),
        source_db: source_db.to_string_lossy().into_owned(),
        patterns,
    };
    let bytes = serde_json::to_vec_pretty(&export)?;
    // Complete and sync a sibling file before replacing the previous export.
    let temporary = path.with_extension("json.tmp");
    {
        use std::io::Write;
        let mut file = fs::File::create(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
    }
    fs::rename(temporary, path)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let db_path = events_db_path();
    if !db_path.is_dir() {
        return Err("event database does not exist; run the daemon first".into());
    }
    let db: Db = sled::open(&db_path)?;

    let raw = load_events(&db)?;
    println!("Loaded {} events", raw.len());

    let filtered = filter_noise(raw);
    println!("{} events after dropping mouse_move", filtered.len());

    let sessions = segment_sessions(filtered);
    println!("Segmented into {} sessions", sessions.len());

    let mut all_sessions: Vec<AbstractedSession> = Vec::new();

    for (i, session) in sessions.iter().enumerate() {
        let tokens = abstract_session(session);
        println!(
            "\nSession {} ({} events -> {} tokens):",
            i,
            session.events.len(),
            tokens.tokens.len()
        );
        for token in &tokens.tokens {
            println!("  {:?}", token);
        }
        all_sessions.push(tokens);
    }

    let mut patterns = dedupe_maximal(mine_patterns(&all_sessions));
    attach_sources(&mut patterns, &sessions, &all_sessions);
    println!("\n=== {} recurring patterns found ===", patterns.len());
    for p in &patterns {
        println!(
            "  [{}x across {} sessions] {:?}",
            p.occurrences, p.session_count, p.tokens
        );
    }
    let output = db_path.with_file_name("patterns.json");
    save_patterns(&output, &db_path, patterns)?;
    println!("Saved patterns to {}", output.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (Vec<Session>, Vec<AbstractedSession>, Vec<WorkflowPattern>) {
        let db = sled::Config::new().temporary(true).open().unwrap();
        for minute in 0..3 {
            for (second, kind) in [
                (0, "key_press"),
                (1, "key_press"),
                (2, "mouse_move"),
                (3, "mouse_click"),
            ] {
                let key = format!("source-{minute}-{second}");
                let event = serde_json::json!({
                    "event_type": kind, "timestamp": format!("2026-09-30T00:0{minute}:0{second}Z"),
                    "process_name": "Code.exe", "key": "KeyA", "button": "Left",
                    "rel_x": 0.5, "rel_y": 0.5
                });
                db.insert(key.as_bytes(), serde_json::to_vec(&event).unwrap())
                    .unwrap();
            }
        }
        let sessions = segment_sessions(filter_noise(load_events(&db).unwrap()));
        let abstracted: Vec<_> = sessions.iter().map(abstract_session).collect();
        let mut patterns = dedupe_maximal(mine_patterns(&abstracted));
        attach_sources(&mut patterns, &sessions, &abstracted);
        (sessions, abstracted, patterns)
    }

    #[test]
    fn links_all_typing_events_and_clicks_to_actual_keys() {
        let (_, abstracted, patterns) = fixture();
        assert_eq!(abstracted[0].spans, vec![0..1, 0..2, 2..3]);
        assert_eq!(patterns.len(), 1);
        let p = &patterns[0];
        assert_eq!((p.occurrences, p.session_count, p.matches.len()), (3, 3, 3));
        for (i, occurrence) in p.matches.iter().enumerate() {
            assert_eq!((occurrence.event_start, occurrence.event_end), (0, 3));
            let keys: Vec<_> = occurrence
                .source_events
                .iter()
                .map(|e| String::from_utf8(e.db_key.clone()).unwrap())
                .collect();
            assert_eq!(
                keys,
                vec![
                    format!("source-{i}-0"),
                    format!("source-{i}-1"),
                    format!("source-{i}-3")
                ]
            );
        }
        assert_eq!(p.id, pattern_id(&p.tokens));
    }

    #[test]
    fn export_preserves_names_and_rejects_corrupt_previous_file() {
        let dir = std::env::temp_dir().join(format!(
            "nexi-pattern-test-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        fs::create_dir(&dir).unwrap();
        let path = dir.join("patterns.json");
        let source = dir.join("events.db");
        let (_, _, mut patterns) = fixture();
        patterns[0].name = "Morning startup".into();
        let id = patterns[0].id.clone();
        save_patterns(&path, &source, patterns).unwrap();
        save_patterns(&path, &source, fixture().2).unwrap();
        let saved: PatternExport = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(saved.patterns[0].name, "Morning startup");
        assert_eq!(saved.patterns[0].id, id);
        fs::write(&path, b"broken json").unwrap();
        assert!(save_patterns(&path, &source, fixture().2).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"broken json");
        fs::remove_file(&path).unwrap();
        fs::remove_dir(&dir).unwrap();
    }
}
