use sled::Db;
use nexi_daemon::InputEvent;

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();
    
    println!("Events stored in database:");
    println!("──────────────────────────");
    
    for item in db.iter() {
        let (_, value) = item.unwrap();
        let json = String::from_utf8(value.to_vec()).unwrap();
        match serde_json::from_str::<InputEvent>(&json) {
    Ok(event) => println!("{:?}", event),
    Err(e) => eprintln!("Failed to parse event: {} ({})", json, e),
}

    println!("──────────────────────────");
    println!("Total: {} events", db.len());
}}