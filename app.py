from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, time, math

APP_SECRET = "change-me"
DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

app = Flask(__name__)
app.secret_key = APP_SECRET
CORS(app)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS stops(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, lat REAL, lng REAL
    );
    CREATE TABLE IF NOT EXISTS buses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS drivers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, username TEXT UNIQUE, password_hash TEXT, bus_id INTEGER,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );
    CREATE TABLE IF NOT EXISTS schedules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, bus_id INTEGER, service_date TEXT,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );
    CREATE TABLE IF NOT EXISTS schedule_times(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER, stop_id INTEGER, seq INTEGER,
        arrival TEXT, departure TEXT,
        FOREIGN KEY(schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
        FOREIGN KEY(stop_id) REFERENCES stops(id),
        UNIQUE(schedule_id, stop_id)
    );
    CREATE TABLE IF NOT EXISTS locations(
        bus_id INTEGER PRIMARY KEY, lat REAL, lng REAL, updated_at INTEGER,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );
    """)
    conn.commit()

    # Insert default data if empty
    if conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0] == 0:
        stops = [
            ("Gandhipuram (Main Bus Stand)", 11.0183, 76.9725),
            ("Ukkadam (Bus Stop)", 10.9896, 76.9610),
            ("Pollachi (Bus Stand)", 10.6580, 77.0082),
        ]
        conn.executemany("INSERT INTO stops(name,lat,lng) VALUES (?,?,?)", stops)
        conn.execute("INSERT INTO buses(name) VALUES (?)", ("Bus 101",))
        bus_id = conn.execute("SELECT id FROM buses WHERE name='Bus 101'").fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO drivers(name,username,password_hash,bus_id) VALUES (?,?,?,NULL)",
                     ("Admin", "admin", generate_password_hash("admin123")))
        conn.execute("INSERT INTO schedules(title,bus_id,service_date) VALUES (?,?,?)",
                     ("Gandhipuram → Ukkadam → Pollachi (Morning)", bus_id, "DAILY"))
        sched_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM stops")}
        times = [
            (sched_id, ids["Gandhipuram (Main Bus Stand)"], 1, "09:00", "09:00"),
            (sched_id, ids["Ukkadam (Bus Stop)"], 2, "10:00", "10:00"),
            (sched_id, ids["Pollachi (Bus Stand)"], 3, "11:00", "11:00"),
        ]
        conn.executemany("INSERT INTO schedule_times(schedule_id,stop_id,seq,arrival,departure) VALUES (?,?,?,?,?)", times)
        conn.commit()

    # Additional stops
    new_stops = [
        ("Singanallur", 11.0054, 77.0360),
        ("Ramanathapuram", 10.9982, 76.9790),
        ("Sulur", 10.9060, 77.0512),
        ("Thiruppur", 11.1085, 77.3411),
        ("Malumichampatti", 10.8805, 77.0110)
    ]
    conn.executemany("INSERT OR IGNORE INTO stops(name,lat,lng) VALUES (?,?,?)", new_stops)
    conn.commit()

    # Add new buses
    buses_to_add = [("Bus 102",), ("Bus 103",), ("Bus 104",), ("Bus 105",), ("Bus 106",), ("Bus 107",)]
    conn.executemany("INSERT OR IGNORE INTO buses(name) VALUES (?)", buses_to_add)
    conn.commit()

    # Fetch stop and bus IDs
    stop_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM stops")}
    bus_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM buses")}

    # Helper to create schedules only if not exists
    def add_schedule(title, bus_name, service_date, stop_sequence, start_hour=9):
        bus_id = bus_ids[bus_name]
        row = conn.execute("SELECT id FROM schedules WHERE title=? AND bus_id=?", (title, bus_id)).fetchone()
        if row:
            return
        conn.execute("INSERT INTO schedules(title, bus_id, service_date) VALUES (?,?,?)",
                     (title, bus_id, service_date))
        schedule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        times = []
        hour = start_hour
        for i, stop_name in enumerate(stop_sequence):
            arrival = departure = f"{hour:02d}:00"
            times.append((schedule_id, stop_ids[stop_name], i + 1, arrival, departure))
            hour += 1
        conn.executemany(
            "INSERT INTO schedule_times(schedule_id,stop_id,seq,arrival,departure) VALUES (?,?,?,?,?)",
            times
        )

    # Route definitions
    def add_morning_and_evening(title_base, bus_list, stop_sequence):
        for bus in bus_list:
            # Morning
            add_schedule(f"{title_base} (Morning)", bus, "DAILY", stop_sequence, start_hour=9)
            # Evening
            add_schedule(f"{title_base} (Evening)", bus, "DAILY", stop_sequence, start_hour=16)  # 4 PM start

    # Create routes for the buses
    add_morning_and_evening(
        "Gandhipuram → Singanallur → Ramanathapuram",
        ["Bus 102", "Bus 103"],
        ["Gandhipuram (Main Bus Stand)", "Singanallur", "Ramanathapuram"]
    )

    add_morning_and_evening(
        "Gandhipuram → Sulur → Thiruppur",
        ["Bus 104", "Bus 105"],
        ["Gandhipuram (Main Bus Stand)", "Sulur", "Thiruppur"]
    )

    add_morning_and_evening(
        "Gandhipuram → Ukkadam → Malumichampatti → Pollachi",
        ["Bus 106", "Bus 107"],
        ["Gandhipuram (Main Bus Stand)", "Ukkadam (Bus Stop)", "Malumichampatti", "Pollachi (Bus Stand)"]
    )

    conn.commit()
    conn.close()


# Initialize DB and sample data
init_db()


# --------- Routes (UI) ----------
@app.route("/")
def user_page():
    conn = get_db()
    stops = conn.execute("SELECT id,name FROM stops ORDER BY name").fetchall()
    conn.close()
    return render_template("user.html", stops=stops)


@app.route("/driver")
def driver_page():
    conn = get_db()
    buses = conn.execute("SELECT id,name FROM buses ORDER BY name").fetchall()
    schedules = conn.execute("""
        SELECT s.id, s.title, s.bus_id, b.name AS bus_name
        FROM schedules s
        JOIN buses b ON b.id = s.bus_id
    """).fetchall()
    conn.close()
    return render_template("driver.html", buses=buses, schedules=schedules)


@app.route("/admin")
def admin_page():
    conn = get_db()
    stops = conn.execute("SELECT * FROM stops ORDER BY name").fetchall()
    buses = conn.execute("SELECT * FROM buses ORDER BY name").fetchall()
    drivers = conn.execute(
        "SELECT d.id,d.name,d.username,b.name AS bus_name "
        "FROM drivers d LEFT JOIN buses b ON b.id=d.bus_id"
    ).fetchall()
    conn.close()
    stops = [dict(s) for s in stops]
    buses = [dict(b) for b in buses]
    drivers = [dict(d) for d in drivers]
    return render_template("admin.html", stops=stops, buses=buses, drivers=drivers)


# --------- Auth ----------
@app.route("/login", methods=["POST"])
def login():
    d = request.get_json() or request.form
    u, p = d.get("username", ""), d.get("password", "")
    conn = get_db()
    row = conn.execute("SELECT * FROM drivers WHERE username = ?", (u,)).fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], p):
        return jsonify({"ok": False}), 401
    session["role"] = "admin" if u == "admin" else "driver"
    session["user_id"] = row["id"]
    return jsonify({"ok": True, "role": session["role"]})


# --------- API ----------

@app.route("/api/search")
def api_search():
    from_id = request.args.get("from_id", type=int)
    to_id = request.args.get("to_id", type=int)
    q = """
    SELECT s.id AS schedule_id, s.title, b.name AS bus_name,
           MIN(ts.departure) AS from_time,
           MAX(te.arrival) AS to_time,
           b.id AS bus_id
    FROM schedules s
    JOIN buses b ON b.id = s.bus_id
    JOIN schedule_times ts ON ts.schedule_id = s.id AND ts.stop_id = ?
    JOIN schedule_times te ON te.schedule_id = s.id AND te.stop_id = ?
    WHERE ts.seq < te.seq
    GROUP BY s.id, s.title, b.name, b.id
    """
    conn = get_db()
    rows = [dict(r) for r in conn.execute(q, (from_id, to_id)).fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/schedule-stops")
def api_schedule_stops_query():
    schedule_id = request.args.get("schedule_id", type=int)
    if not schedule_id:
        return jsonify([])
    conn = get_db()
    rows = conn.execute(
        "SELECT st.seq, s.id as stop_id, s.name, s.lat, s.lng, st.arrival, st.departure "
        "FROM schedule_times st JOIN stops s ON st.stop_id = s.id "
        "WHERE st.schedule_id = ? ORDER BY st.seq", (schedule_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"seq": r["seq"], "stop_id": r["stop_id"], "name": r["name"],
                     "lat": r["lat"], "lng": r["lng"], "arrival": r["arrival"], "departure": r["departure"]} for r in rows])


@app.route("/api/schedule-stops/<int:schedule_id>")
def api_schedule_stops(schedule_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT st.seq, s.id as stop_id, s.name, s.lat, s.lng, st.arrival, st.departure "
        "FROM schedule_times st JOIN stops s ON st.stop_id = s.id "
        "WHERE st.schedule_id = ? ORDER BY st.seq", (schedule_id,)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "seq": r["seq"],
            "stop_id": r["stop_id"],
            "name": r["name"],
            "lat": r["lat"],
            "lng": r["lng"],
            "arrival": r["arrival"],
            "departure": r["departure"]
        })
    return jsonify(out)


@app.route("/api/bus-location/<int:bus_id>")
def api_bus_loc(bus_id):
    conn = get_db()
    row = conn.execute("SELECT lat,lng,updated_at FROM locations WHERE bus_id = ?", (bus_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "no location"}), 404
    return jsonify({"lat": row["lat"], "lng": row["lng"], "updated_at": row["updated_at"]})


@app.route("/api/update-location", methods=["POST"])
def api_update_loc():
    try:
        data = request.get_json(force=True)
        bus_id = int(data.get("bus_id", 0))
        lat = float(data.get("lat", 0))
        lng = float(data.get("lng", 0))

        if bus_id <= 0 or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return jsonify({"ok": False, "error": "Invalid input"}), 400

        ts = int(time.time())
        conn = get_db()
        conn.execute("""
            INSERT INTO locations(bus_id, lat, lng, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bus_id) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                updated_at = excluded.updated_at
        """, (bus_id, lat, lng, ts))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
@app.route("/api/add-bus", methods=["POST"])
def api_add_bus():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO buses(name) VALUES (?)", (name,))
    conn.commit()
    new_id = conn.execute("SELECT id FROM buses WHERE name=?", (name,)).fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/add-driver", methods=["POST"])
def api_add_driver():
    data = request.get_json()
    name = data.get("name", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    bus_id = data.get("bus_id")
    if not name or not username or not password:
        return jsonify({"ok": False, "error": "Missing fields"}), 400
    password_hash = generate_password_hash(password)
    conn = get_db()
    try:
        conn.execute("INSERT INTO drivers(name, username, password_hash, bus_id) VALUES (?,?,?,?)",
                     (name, username, password_hash, bus_id if bus_id else None))
        conn.commit()
        new_id = conn.execute("SELECT id FROM drivers WHERE username=?", (username,)).fetchone()["id"]
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"ok": False, "error": "Username already exists"}), 409
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/add-stop", methods=["POST"])
def api_add_stop():
    data = request.get_json()
    name = data.get("name", "").strip()
    lat = data.get("lat")
    lng = data.get("lng")
    if not name or lat is None or lng is None:
        return jsonify({"ok": False, "error": "Missing fields"}), 400
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO stops(name, lat, lng) VALUES (?, ?, ?)", (name, lat, lng))
    conn.commit()
    new_id = conn.execute("SELECT id FROM stops WHERE name=?", (name,)).fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/add-schedule", methods=["POST"])
def api_add_schedule():
    data = request.get_json()
    bus_id = data.get("bus_id")
    title = data.get("title", "").strip()
    stop_ids = data.get("stop_ids", [])
    if not bus_id or not title or not stop_ids:
        return jsonify({"ok": False, "error": "Missing fields"}), 400
    conn = get_db()
    conn.execute("INSERT INTO schedules(title, bus_id, service_date) VALUES (?, ?, ?)",
                 (title, bus_id, "DAILY"))
    schedule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i, stop_id in enumerate(stop_ids):
        time_str = f"{9 + i:02d}:00"
        conn.execute(
            "INSERT INTO schedule_times(schedule_id, stop_id, seq, arrival, departure) VALUES (?, ?, ?, ?, ?)",
            (schedule_id, stop_id, i+1, time_str, time_str)
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": schedule_id})


@app.route("/api/eta/<int:bus_id>/<int:to_stop_id>")
def api_eta(bus_id, to_stop_id):
    conn = get_db()
    loc = conn.execute("SELECT lat,lng FROM locations WHERE bus_id = ?", (bus_id,)).fetchone()
    stop = conn.execute("SELECT lat,lng FROM stops WHERE id = ?", (to_stop_id,)).fetchone()
    conn.close()
    if not loc or not stop:
        return jsonify({"error": "missing"}), 404
    dist = haversine(loc["lat"], loc["lng"], stop["lat"], stop["lng"])
    eta_min = int((dist / 30.0) * 60)  # assume 30 km/h
    return jsonify({"distance_km": round(dist, 2), "eta_min": eta_min})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
