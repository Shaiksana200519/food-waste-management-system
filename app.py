from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "shaiksana_food_waste_secret_key"
DB_NAME = "food_waste_pro.db"

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
                phone TEXT NOT NULL
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
                expiry_time TEXT NOT NULL,
                location TEXT NOT NULL,
                status TEXT DEFAULT 'Available',
                claimed_by TEXT DEFAULT '-',
                created_at TEXT NOT NULL
            )
        ''')

@app.route('/')
def index():
    return render_template('index.html')

# --- Auth APIs ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password, role, phone) VALUES (?, ?, ?, ?, ?)",
                (data['name'], data['email'], generate_password_hash(data['password']), data['role'], data['phone'])
            )
        return jsonify({"message": "Account created! Please log in."}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already registered."}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (data['email'],)).fetchone()
    if user and check_password_hash(user['password'], data['password']):
        session['user'] = {
            "id": user['id'],
            "name": user['name'],
            "role": user['role'],
            "phone": user['phone']
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

# --- Donation & Dashboard APIs ---
@app.route('/api/donations', methods=['GET'])
def get_donations():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM donations ORDER BY id DESC").fetchall()
        donations = [dict(r) for r in rows]
        
        total_meals = sum(d['meals_count'] for d in donations)
        available_count = sum(1 for d in donations if d['status'] == 'Available')
        claimed_count = sum(1 for d in donations if d['status'] in ('Claimed', 'Delivered'))

        return jsonify({
            "donations": donations,
            "stats": {
                "total_listings": len(donations),
                "total_meals": total_meals,
                "available": available_count,
                "rescued": claimed_count
            }
        })

@app.route('/api/donations', methods=['POST'])
def add_donation():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Login required to post food."}), 401
    data = request.json
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    with get_db() as conn:
        conn.execute('''
            INSERT INTO donations 
            (donor_id, donor_name, phone, food_item, category, meals_count, expiry_time, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user['id'], user['name'], user['phone'], data['food_item'],
            data['category'], int(data['meals_count']), data['expiry_time'],
            data['location'], now
        ))
    return jsonify({"message": "Food listing added!"}), 201

@app.route('/api/donations/<int:donation_id>/status', methods=['POST'])
def update_status(donation_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Login required."}), 401
    new_status = request.json.get('status')
    with get_db() as conn:
        if new_status == 'Claimed':
            conn.execute(
                "UPDATE donations SET status = 'Claimed', claimed_by = ? WHERE id = ?",
                (f"{user['name']} ({user['phone']})", donation_id)
            )
        elif new_status == 'Delivered':
            conn.execute("UPDATE donations SET status = 'Delivered' WHERE id = ?", (donation_id,))
    return jsonify({"message": f"Marked as {new_status}"})

@app.route('/api/donations/<int:donation_id>', methods=['DELETE'])
def delete_donation(donation_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Login required."}), 401
    with get_db() as conn:
        conn.execute("DELETE FROM donations WHERE id = ? AND donor_id = ?", (donation_id, user['id']))
    return jsonify({"message": "Deleted"})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
