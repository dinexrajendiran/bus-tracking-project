from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, time, math

# ---------------- CONFIG ----------------
APP_SECRET = "change-me"
DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

app = Flask(__name__)
app.secret_key = APP_SECRET
CORS(app)

# ---------------- DATABASE ----------------
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
        name TEXT UNIQUE,
        lat REAL,
        lng REAL
    );

    CREATE TABLE IF NOT EXISTS buses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS drivers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        username TEXT UNIQUE,
        password_hash TEXT,
        bus_id INTEGER,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );

    CREATE TABLE IF NOT EXISTS schedules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        bus_id INTEGER,
        service_date TEXT,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );

    CREATE TABLE IF NOT EXISTS schedule_times(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER,
        stop_id INTEGER,
        seq INTEGER,
        arrival TEXT,
        departure TEXT,
        FOREIGN KEY(schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
        FOREIGN KEY(stop_id) REFERENCES stops(id),
        UNIQUE(schedule_id, stop_id)
    );

    CREATE TABLE IF NOT EXISTS locations(
        bus_id INTEGER PRIMARY KEY,
        lat REAL,
        lng REAL,
        updated_at INTEGER,
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );
    """)
    conn.commit()

    # -------- DEFAULT DATA --------
    if conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0] == 0:
        stops = [
            ("Gandhipuram (Main Bus Stand)", 11.0183, 76.9725),
            ("Ukkadam (Bus Stop)", 10.9896, 76.9610),
            ("Pollachi (Bus Stand)", 10.6580, 77.0082),
        ]
        conn.executemany("INSERT INTO stops(name,lat,lng) VALUES (?,?,?)", stops)

        conn.execute("INSERT INTO buses(name) VALUES (?)", ("Bus 101",))

        bus_id = conn.execute("SELECT id FROM buses WHERE name='Bus 101'").fetchone()["id"]

        conn.execute(
            "INSERT OR IGNORE INTO drivers(name,username,password_hash,bus_id) VALUES (?,?,?,NULL)",
            ("Admin", "admin", generate_password_hash("admin123"))
        )

        conn.execute(
            "INSERT INTO schedules(title,bus_id,service_date) VALUES (?,?,?)",
            ("Gandhipuram → Ukkadam → Pollachi (Morning)", bus_id, "DAILY")
        )

        sched_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM stops")}

        conn.executemany(
            "INSERT INTO schedule_times(schedule_id,stop_id,seq,arrival,departure) VALUES (?,?,?,?,?)",
            [
                (sched_id, ids["Gandhipuram (Main Bus Stand)"], 1, "09:00", "09:00"),
                (sched_id, ids["Ukkadam (Bus Stop)"], 2, "10:00", "10:00"),
                (sched_id, ids["Pollachi (Bus Stand)"], 3, "11:00", "11:00"),
            ]
        )
        conn.commit()

    conn.close()


init_db()

# ---------------- ROUTES ----------------
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
        SELECT s.id, s.title, b.name AS bus_name
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
    drivers = conn.execute("""
        SELECT d.id,d.name,d.username,b.name AS bus_name
        FROM drivers d
        LEFT JOIN buses b ON b.id=d.bus_id
    """).fetchall()
    conn.close()

    return render_template(
        "admin.html",
        stops=[dict(s) for s in stops],
        buses=[dict(b) for b in buses],
        drivers=[dict(d) for d in drivers]
    )

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    u = data.get("username", "")
    p = data.get("password", "")

    conn = get_db()
    row = conn.execute("SELECT * FROM drivers WHERE username=?", (u,)).fetchone()
    conn.close()

    if not row or not check_password_hash(row["password_hash"], p):
        return jsonify({"ok": False}), 401

    session["role"] = "admin" if u == "admin" else "driver"
    session["user_id"] = row["id"]

    return jsonify({"ok": True, "role": session["role"]})

# ---------------- API ----------------
@app.route("/api/add-bus", methods=["POST"])
def add_bus():
    data = request.get_json()
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400

    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO buses(name) VALUES (?)", (name,))
    conn.commit()

    row = conn.execute("SELECT id FROM buses WHERE name=?", (name,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "id": row["id"]})


@app.route("/api/add-stop", methods=["POST"])
def add_stop():
    data = request.get_json()
    name = data.get("name", "").strip()
    lat = data.get("lat")
    lng = data.get("lng")

    if not name or lat is None or lng is None:
        return jsonify({"ok": False}), 400

    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO stops(name,lat,lng) VALUES (?,?,?)", (name, lat, lng))
    conn.commit()

    row = conn.execute("SELECT id FROM stops WHERE name=?", (name,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "id": row["id"]})


@app.route("/api/add-driver", methods=["POST"])
def add_driver():
    data = request.get_json()
    name = data.get("name", "")
    username = data.get("username", "")
    password = data.get("password", "")
    bus_id = data.get("bus_id")

    if not name or not username or not password:
        return jsonify({"ok": False}), 400

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO drivers(name,username,password_hash,bus_id)
            VALUES (?,?,?,?)
        """, (name, username, generate_password_hash(password), bus_id))
        conn.commit()

        row = conn.execute("SELECT id FROM drivers WHERE username=?", (username,)).fetchone()
        return jsonify({"ok": True, "id": row["id"]})

    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Username exists"}), 409

    finally:
        conn.close()


@app.route("/api/add-schedule", methods=["POST"])
def add_schedule():
    data = request.get_json()
    bus_id = data.get("bus_id")
    title = data.get("title", "")
    stop_ids = data.get("stop_ids", [])

    if not bus_id or not title or len(stop_ids) < 2:
        return jsonify({"ok": False}), 400

    conn = get_db()

    conn.execute(
        "INSERT INTO schedules(title,bus_id,service_date) VALUES (?,?,?)",
        (title, bus_id, "DAILY")
    )

    schedule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for i, stop_id in enumerate(stop_ids):
        t = f"{9+i:02d}:00"
        conn.execute("""
            INSERT INTO schedule_times(schedule_id,stop_id,seq,arrival,departure)
            VALUES (?,?,?,?,?)
        """, (schedule_id, stop_id, i+1, t, t))

    conn.commit()
    conn.close()

    return jsonify({"ok": True, "id": schedule_id})


@app.route("/api/update-location", methods=["POST"])
def update_location():
    data = request.get_json()
    bus_id = int(data.get("bus_id", 0))
    lat = float(data.get("lat", 0))
    lng = float(data.get("lng", 0))

    ts = int(time.time())

    conn = get_db()
    conn.execute("""
        INSERT INTO locations(bus_id,lat,lng,updated_at)
        VALUES (?,?,?,?)
        ON CONFLICT(bus_id) DO UPDATE SET
        lat=excluded.lat,
        lng=excluded.lng,
        updated_at=excluded.updated_at
    """, (bus_id, lat, lng, ts))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/bus-location/<int:bus_id>")
def bus_location(bus_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM locations WHERE bus_id=?", (bus_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "not found"}), 404

    return jsonify(dict(row))


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)

    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)

    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))


@app.route("/api/eta/<int:bus_id>/<int:stop_id>")
def eta(bus_id, stop_id):
    conn = get_db()

    loc = conn.execute("SELECT lat,lng FROM locations WHERE bus_id=?", (bus_id,)).fetchone()
    stop = conn.execute("SELECT lat,lng FROM stops WHERE id=?", (stop_id,)).fetchone()

    conn.close()

    if not loc or not stop:
        return jsonify({"error": "missing"}), 404

    dist = haversine(loc["lat"], loc["lng"], stop["lat"], stop["lng"])
    eta = int((dist / 30) * 60)

    return jsonify({"distance_km": round(dist, 2), "eta_min": eta})

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
