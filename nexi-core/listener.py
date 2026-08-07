import socket
import json
import threading
from datetime import datetime

HOST = '127.0.0.1'
PORT = 9000

def process_event(event: dict):
    etype = event.get('event_type')
    ts = event.get('timestamp', '')
    window = event.get('window_title', 'unknown')
    process = event.get('process_name', 'unknown')

    if etype == 'mouse_click':
        btn = event.get('button', 'unknown')
        print(f"[{ts}] CLICK — {btn} | {process} | {window}")
    
    elif etype == 'key_press':
        key = event.get('key', 'unknown')
        print(f"[{ts}] KEY — {key} | {process} | {window}")
    
    elif etype == 'mouse_move':
        x = event.get('x', 0)
        y = event.get('y', 0)
        if int(x) % 50 == 0:
            print(f"[{ts}] MOVE — ({x:.0f}, {y:.0f}) | {process} | {window}")

def listen():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        print(f"Connected to Nexi daemon on {HOST}:{PORT}")
        print("Listening for events...\n")
        
        buffer = ""
        while True:
            data = s.recv(4096).decode('utf-8')
            if not data:
                print("Daemon disconnected")
                break
            
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    try:
                        event = json.loads(line)
                        process_event(event)
                    except json.JSONDecodeError:
                        print(f"Bad event: {line}")

def main():
    print("Nexi Core — Python Listener")
    print("────────────────────────────")
    t = threading.Thread(target=listen, daemon=True)
    t.start()
    
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down listener")

if __name__ == "__main__":
    main()