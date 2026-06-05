use sled::Db;

fn main() {
    let db: Db = sled::open("D:/Project 5/Nexi/nexi-daemon/nexi_events.db").unwrap();
    
    println!("Events stored in database:");
    println!("──────────────────────────");
    
    for item in db.iter() {
        let (_, value) = item.unwrap();
        let json = String::from_utf8(value.to_vec()).unwrap();
        println!("{}", json);
    }

    println!("──────────────────────────");
    println!("Total: {} events", db.len());
}