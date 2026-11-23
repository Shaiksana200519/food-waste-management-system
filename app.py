from flask import Flask, render_template, request, jsonify, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import random
import csv
import io
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "shaiksana_enterprise_foodshare_key"
DB_NAME = "foodshare_enterprise.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                phone TEXT NOT NULL,
                city TEXT DEFAULT 'Hyderabad'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER,
                donor_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                food_item TEXT NOT NULL,
                category TEXT NOT NULL,
                meals_count INTEGER NOT NULL,
                expiry_iso TEXT NOT NULL,
                location TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                status TEXT DEFAULT 'Available',
                claimed_by TEXT DEFAULT '-',
                pickup_otp TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        # Seed realistic demo data if empty so app looks alive immediately
        count = conn.execute("SELECT COUNT(*) FROM donations").fetchone()[0]
        if count == 0:
            now = datetime.now()
            demo_items = [
                (0, "Paradise Grand Kitchen", "+91 98765 43210", "Hyderabadi Veg Dum Biryani & Raita", "Vegetarian", 45,
                 (now + timedelta(hours=3, minutes=30)).isoformat(), "Banjara Hills, Road No. 12, Hyderabad", 17.4126, 78.4392,
                 "Available", "-", "4821", now.strftime("%d %b, %I:%M %p")),
                (0, "Royal Banquet & Events", "+91 91234 56789", "Paneer Butter Masala, Naan & Gulab Jamun", "Vegetarian", 80,
                 (now + timedelta(hours=5)).isoformat(), "Jubilee Hills Checkpost, Hyderabad", 17.4311, 78.4071,
                 "Claimed", "Robin Hood Army Hyd (+91 99887 76655)", "7394", now.strftime("%d %b, %I:%M %p")),
                (0, "FreshBake Artisans", "+91 90001 11222", "Assorted Whole Wheat Breads & Croissants", "Bakery / Packaged", 30,
                 (now + timedelta(hours=12)).isoformat(), "Gachibowli IT Park, Hyderabad", 17.4401, 78.3489,
                 "Delivered", "Hope Foundation NGO (+91 98480 12345)", "1950", now.strftime("%d %b, %I:%M %p"))
            ]
            conn.executemany('''
                INSERT INTO donations (donor_id, donor_name, phone, food_item, category, meals_count, expiry_iso, location, lat, lng, status, claimed_by, pickup_otp, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', demo_items)

@app.route('/')
def index():
    return render_template('index.html')

# --- Auth Routes ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password, role, phone, city) VALUES (?, ?, ?, ?, ?, ?)",
                (data['name'], data['email'], generate_password_hash(data['password']), data['role'], data['phone'], data.get('city', 'Hyderabad'))
            )
        return jsonify({"message": "Account created! Please sign in."}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already registered."}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (data['email'],)).fetchone()
    if user and check_password_hash(user['password'], data['password']):
        session['user'] = {
            "id": user['id'], "name": user['name'], "role": user['role'],
            "phone": user['phone'], "city": user['city']
        }
        return jsonify({"user": session['user']})
    return jsonify({"error": "Invalid email or password."}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({"message": "Logged out"})

@app.route('/api/me', methods=['GET'])
def current_user():
    return jsonify({"user": session.get('user')})

# --- Core App Routes ---
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM donations ORDER BY id DESC").fetchall()
        donations = [dict(r) for r in rows]

        total_meals = sum(d['meals_count'] for d in donations)
        rescued_meals = sum(d['meals_count'] for d in donations if d['status'] in ('Claimed', 'Delivered'))
        co2_saved = round(rescued_meals * 2.5, 1)  # ~2.5 kg CO2 saved per rescued meal
        active_pickups = sum(1 for d in donations if d['status'] == 'Available')

        # Leaderboard aggregation
        leaderboard_rows = conn.execute('''
            SELECT donor_name, SUM(meals_count) as total_meals, COUNT(id) as donations_count
            FROM donations GROUP BY donor_name ORDER BY total_meals DESC LIMIT 5
        ''').fetchall()

        return jsonify({
            "donations": donations,
            "leaderboard": [dict(r) for r in leaderboard_rows],
            "stats": {
                "total_meals": total_meals,
                "rescued_meals": rescued_meals,
                "co2_saved": co2_saved,
                "active_pickups": active_pickups
            }
        })

@app.route('/api/donations', methods=['POST'])
def create_donation():
    user = session.get('user')
    if not user or user['role'] != 'Donor':
        return jsonify({"error": "Only logged-in Donors can post food."}), 401
    data = request.json
    hours = float(data.get('expiry_hours', 4))
    expiry_iso = (datetime.now() + timedelta(hours=hours)).isoformat()
    otp = str(random.randint(1000, 9999))
    # Slight random offset around default coordinates if user didn't pick custom lat/lng
    lat = float(data.get('lat') or (17.3850 + random.uniform(-0.04, 0.04)))
    lng = float(data.get('lng') or (78.4867 + random.uniform(-0.04, 0.04)))

    with get_db() as conn:
        conn.execute('''
            INSERT INTO donations (donor_id, donor_name, phone, food_item, category, meals_count, expiry_iso, location, lat, lng, pickup_otp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user['id'], user['name'], user['phone'], data['food_item'], data['category'],
            int(data['meals_count']), expiry_iso, data['location'], lat, lng, otp,
            datetime.now().strftime("%d %b, %I:%M %p")
        ))
    return jsonify({"message": f"Donation published! Pickup OTP: {otp}"}), 201

@app.route('/api/donations/<int:donation_id>/claim', methods=['POST'])
def claim_donation(donation_id):
    user = session.get('user')
    if not user or user['role'] != 'NGO':
        return jsonify({"error": "Log in as an NGO / Volunteer to claim pickups."}), 401
    with get_db() as conn:
        row = conn.execute("SELECT pickup_otp FROM donations WHERE id = ?", (donation_id,)).fetchone()
        conn.execute(
            "UPDATE donations SET status = 'Claimed', claimed_by = ? WHERE id = ?",
            (f"{user['name']} ({user['phone']})", donation_id)
        )
    return jsonify({"message": f"Claimed! Show OTP {row['pickup_otp']} at pickup."})

@app.route('/api/donations/<int:donation_id>/deliver', methods=['POST'])
def verify_delivery(donation_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Login required."}), 401
    entered_otp = request.json.get('otp', '').strip()
    with get_db() as
