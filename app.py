from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "esp32_gateway_multiuser_session_secret"
DB_NAME = "iot_data.db"

# ================= DATABASE CONNECTIONS =================
from database import init_db
init_db()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

# ================= LOGIN DECORATOR =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ================= HOME ROUTE =================
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('devices_page'))
    return redirect(url_for('login'))

# ================= AUTHENTICATION GATEWAY =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('devices_page'))

    if request.method == 'POST':
        data = request.get_json() or request.form
        action = data.get('action') # 'login' or 'register'
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({"status": "error", "message": "Username and password are required"}), 400

        conn = get_db()
        c = conn.cursor()

        if action == 'register':
            try:
                hashed = generate_password_hash(password)
                c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
                conn.commit()
                conn.close()
                return jsonify({"status": "success", "message": "Registration successful! Please sign in."})
            except sqlite3.IntegrityError:
                conn.close()
                return jsonify({"status": "error", "message": "Username already exists"}), 400
        else:
            # Login action
            c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
            user = c.fetchone()
            conn.close()

            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = username
                return jsonify({"status": "success", "message": "Login successful"})
            else:
                return jsonify({"status": "error", "message": "Invalid username or password"}), 401

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================= DEVICES REGISTRY PAGE =================
@app.route('/devices')
@login_required
def devices_page():
    return render_template('devices.html', username=session['username'])

# ================= DASHBOARD ROUTE =================
@app.route('/dashboard')
@login_required
def dashboard_page():
    device_id = request.args.get('device_id')
    if not device_id:
        return redirect(url_for('devices_page'))

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, device_name FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()
    conn.close()

    if not device:
        # Access denied or device does not exist
        return redirect(url_for('devices_page'))

    return render_template('dashboard.html', device_id=device_id, device_name=device['device_name'], username=session['username'])

# ================= DEVICE DATABASE CRUD APIs =================
@app.route('/api/devices', methods=['GET'])
@login_required
def api_get_devices():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT device_id, device_name, wifi_status, temp_threshold, gas_threshold, upload_interval, actuator_status, updated_at 
        FROM devices 
        WHERE user_id = ?
    """, (session['user_id'],))
    rows = c.fetchall()
    conn.close()

    devices = []
    for r in rows:
        devices.append({
            "device_id": r['device_id'],
            "device_name": r['device_name'],
            "wifi_status": r['wifi_status'],
            "temp_threshold": r['temp_threshold'],
            "gas_threshold": r['gas_threshold'],
            "upload_interval": r['upload_interval'],
            "actuator_status": r['actuator_status'],
            "updated_at": r['updated_at']
        })
    return jsonify(devices)

@app.route('/api/devices/add', methods=['POST'])
@login_required
def api_add_device():
    data = request.get_json() or request.form
    device_name = data.get('device_name', '').strip()
    device_suffix = data.get('device_suffix', '').strip()

    if not device_name:
        return jsonify({"status": "error", "message": "Device Name is required"}), 400
    if not device_suffix:
        return jsonify({"status": "error", "message": "Device ID Suffix is required"}), 400

    # Clean and validate suffix: replace spaces with underscores, allow only alphanumeric and underscores
    import re
    device_suffix = re.sub(r'\s+', '_', device_suffix)
    if not re.match(r'^[a-zA-Z0-9_]+$', device_suffix):
        return jsonify({"status": "error", "message": "Device suffix can only contain letters, numbers, and underscores"}), 400

    device_id = f"ESP32_{device_suffix}"

    conn = get_db()
    c = conn.cursor()

    # Ensure device name is unique per user
    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_name = ?", (session['user_id'], device_name))
    if c.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": f"A device named '{device_name}' already exists in your account."}), 400
    
    # Ensure device ID is globally unique
    c.execute("SELECT id FROM devices WHERE device_id = ?", (device_id,))
    if c.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": f"Device ID '{device_id}' is already registered by another device."}), 400

    try:
        c.execute("""
            INSERT INTO devices (user_id, device_id, device_name) 
            VALUES (?, ?, ?)
        """, (session['user_id'], device_id, device_name))
        conn.commit()
        conn.close()
        return jsonify({
            "status": "success", 
            "message": f"Device registered! ID: {device_id}", 
            "device_id": device_id
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "Database error while registering device"}), 400

@app.route('/api/devices/delete', methods=['POST'])
@login_required
def api_delete_device():
    data = request.get_json() or request.form
    device_id = data.get('device_id')

    if not device_id:
        return jsonify({"status": "error", "message": "Device ID is required"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Device not found or access denied"}), 404

    c.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Device deleted successfully"})

# ================= RECEIVE DATA FROM ESP32 (PUBLIC) =================
@app.route('/upload', methods=['POST'])
def upload():
    data = request.get_json()
    device_id = data.get('device_id', 'ESP32_Env_Monitor')

    conn = get_db()
    c = conn.cursor()

    # Look up settings for this specific device
    c.execute("SELECT temp_threshold, gas_threshold, upload_interval, actuator_status, alarm_muted FROM devices WHERE device_id = ?", (device_id,))
    device = c.fetchone()

    temp_thresh = device['temp_threshold'] if device else 35.0
    gas_thresh = device['gas_threshold'] if device else 300
    upload_int = device['upload_interval'] if device else 2
    actuator_stat = device['actuator_status'] if device else 0
    alarm_muted = device['alarm_muted'] if device else 0

    # Classify safety status dynamically
    status = "Normal"
    if data.get('gas', 0) >= gas_thresh:
        status = "Critical"
    elif data.get('temp', 0.0) >= temp_thresh:
        status = "Warning"

    # Log telemetry only if device is registered
    if device:
        c.execute('''
            INSERT INTO sensor_data (device_id, temperature, humidity, gas, light, sound, distance, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id,
            data['temp'],
            data['humidity'],
            data['gas'],
            data['light'],
            data['sound'],
            data['distance'],
            status
        ))

        # Mark device as connected and sync client-side alarm mute state
        client_muted = data.get('alarm_muted')
        if client_muted is not None:
            try:
                client_muted = int(client_muted)
                c.execute("""
                    UPDATE devices 
                    SET wifi_status = 'Connected',
                        alarm_muted = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE device_id = ?
                """, (client_muted, device_id))
            except ValueError:
                c.execute("""
                    UPDATE devices 
                    SET wifi_status = 'Connected',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE device_id = ?
                """, (device_id,))
        else:
            c.execute("""
                UPDATE devices 
                SET wifi_status = 'Connected',
                    updated_at = CURRENT_TIMESTAMP
                WHERE device_id = ?
            """, (device_id,))
        conn.commit()
        
    conn.close()

    print(f"[UPLOAD] DATA RECEIVED FROM {device_id}:", data)

    # Return active configs back to ESP32
    return {
        "status": "success",
        "actuator_status": actuator_stat,
        "upload_interval": upload_int,
        "temp_threshold": temp_thresh,
        "gas_threshold": gas_thresh,
        "alarm_muted": alarm_muted
    }

# ================= LATEST LOG API =================
@app.route('/latest')
@login_required
def latest():
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    conn = get_db()
    c = conn.cursor()

    # Verify ownership
    c.execute("SELECT temp_threshold, gas_threshold, upload_interval, actuator_status, alarm_muted, wifi_status, device_name FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    # Get latest reading
    c.execute("""
        SELECT device_id, temperature, humidity, gas, light, sound, distance, status, timestamp 
        FROM sensor_data 
        WHERE device_id = ?
        ORDER BY id DESC 
        LIMIT 1
    """, (device_id,))
    sensor_row = c.fetchone()

    conn.close()

    response = {}
    if sensor_row:
        response["sensor"] = {
            "device_id": sensor_row['device_id'],
            "temperature": sensor_row['temperature'],
            "humidity": sensor_row['humidity'],
            "gas": sensor_row['gas'],
            "light": sensor_row['light'],
            "sound": sensor_row['sound'],
            "distance": sensor_row['distance'],
            "status": sensor_row['status'],
            "timestamp": sensor_row['timestamp']
        }
    else:
        response["sensor"] = None

    response["settings"] = {
        "device_id": device_id,
        "device_name": device['device_name'],
        "wifi_status": device['wifi_status'],
        "temp_threshold": device['temp_threshold'],
        "gas_threshold": device['gas_threshold'],
        "upload_interval": device['upload_interval'],
        "actuator_status": device['actuator_status'],
        "alarm_muted": device['alarm_muted']
    }

    return jsonify(response)

# ================= HISTORICAL LOG API =================
@app.route('/data')
@login_required
def data():
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    c.execute("""
        SELECT temperature, humidity, gas, light, sound, distance, status, timestamp 
        FROM sensor_data 
        WHERE device_id = ?
        ORDER BY id DESC 
        LIMIT 20
    """, (device_id,))
    rows = c.fetchall()
    conn.close()

    formatted_data = []
    for row in rows:
        formatted_data.append({
            "temperature": row['temperature'],
            "humidity": row['humidity'],
            "gas": row['gas'],
            "light": row['light'],
            "sound": row['sound'],
            "distance": row['distance'],
            "status": row['status'],
            "timestamp": row['timestamp']
        })

    formatted_data.reverse()
    return jsonify(formatted_data)

# ================= GATEWAY SETTINGS API =================
@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    data = request.get_json() or request.form
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    if request.method == 'POST':
        temp_thresh = data.get('temp_threshold')
        gas_thresh = data.get('gas_threshold')
        upload_int = data.get('upload_interval')

        c.execute("""
            UPDATE devices 
            SET temp_threshold = COALESCE(?, temp_threshold),
                gas_threshold = COALESCE(?, gas_threshold),
                upload_interval = COALESCE(?, upload_interval),
                updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        """, (temp_thresh, gas_thresh, upload_int, device_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    
    else:
        c.execute("""
            SELECT device_id, temp_threshold, gas_threshold, upload_interval 
            FROM devices 
            WHERE device_id = ?
        """, (device_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({
            "device_id": row['device_id'],
            "temp_threshold": row['temp_threshold'],
            "gas_threshold": row['gas_threshold'],
            "upload_interval": row['upload_interval']
        })

# ================= GATEWAY MANUAL CONTROL API =================
@app.route('/api/control', methods=['POST'])
@login_required
def api_control():
    data = request.get_json() or request.form
    device_id = data.get('device_id')
    status = data.get('actuator_status')

    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    if status is None:
        return jsonify({"error": "actuator_status required"}), 400

    try:
        status = int(status)
    except ValueError:
        return jsonify({"error": "Invalid actuator status value"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    c.execute("""
        UPDATE devices 
        SET actuator_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE device_id = ?
    """, (status, device_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "actuator_status": status})

# ================= GATEWAY ALARM MUTE API =================
@app.route('/api/mute', methods=['POST'])
@login_required
def api_mute():
    data = request.get_json() or request.form
    device_id = data.get('device_id')
    mute_state = data.get('alarm_muted')

    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if mute_state is None:
        return jsonify({"error": "alarm_muted state required"}), 400

    try:
        mute_state = int(mute_state)
    except ValueError:
        return jsonify({"error": "Invalid mute state value"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id FROM devices WHERE user_id = ? AND device_id = ?", (session['user_id'], device_id))
    device = c.fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    c.execute("""
        UPDATE devices 
        SET alarm_muted = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE device_id = ?
    """, (mute_state, device_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "alarm_muted": mute_state})

# ================= INITIATE GATEWAY SERVER =================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)