import sqlite3

DB_NAME = "iot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Enable Foreign Key constraints in SQLite
    c.execute("PRAGMA foreign_keys = ON;")

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            device_id TEXT UNIQUE NOT NULL,
            device_name TEXT NOT NULL,
            wifi_status TEXT DEFAULT 'Disconnected',
            temp_threshold REAL DEFAULT 35.0,
            gas_threshold INTEGER DEFAULT 300,
            upload_interval INTEGER DEFAULT 2,
            actuator_status INTEGER DEFAULT 0,
            alarm_muted INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            temperature REAL,
            humidity REAL,
            gas INTEGER,
            light INTEGER,
            sound INTEGER,
            distance REAL,
            status TEXT DEFAULT 'Normal',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
        )
    ''')

    # Auto-migration block to add alarm_muted to devices table if it doesn't exist
    try:
        c.execute("ALTER TABLE devices ADD COLUMN alarm_muted INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass # Column already exists, safe to ignore

    conn.commit()
    conn.close()
    print("Database initialized")

if __name__ == "__main__":
    init_db()