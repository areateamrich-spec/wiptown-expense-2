"""
WIPTOWN Expense Tracker — Production server (Flask + Gunicorn)

Local:    python app.py
Railway:  gunicorn app:app  (handled by Procfile)
"""
import os
import sys
import json
import logging
import traceback
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_from_directory

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = DATABASE_URL.startswith('postgres')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

log.info(f"=== WIPTOWN STARTING ===")
log.info(f"USE_PG = {USE_PG}")
log.info(f"DATABASE_URL = {'SET' if DATABASE_URL else 'NOT SET'}")

# ── DB layer ──────────────────────────────────────────────────────────────────
if USE_PG:
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool as pg_pool
        log.info("psycopg2 imported")
    except ImportError as e:
        log.error(f"FATAL: psycopg2 not installed: {e}")
        sys.exit(1)

    r = urlparse(DATABASE_URL)
    PG_KWARGS = dict(
        host=r.hostname,
        port=r.port or 5432,
        dbname=r.path.lstrip('/'),
        user=r.username,
        password=r.password,
        sslmode='require',
        connect_timeout=10,
    )
    log.info(f"PG host={r.hostname} db={r.path.lstrip('/')}")

    # Connection pool — production best practice
    try:
        DB_POOL = pg_pool.ThreadedConnectionPool(1, 10, **PG_KWARGS)
        log.info("PG pool created")
    except Exception as e:
        log.error(f"FATAL: cannot create PG pool: {e}")
        traceback.print_exc()
        DB_POOL = None
else:
    import sqlite3
    DB_PATH = os.path.join(BASE_DIR, 'wiptown.db')
    log.info(f"SQLite path = {DB_PATH}")


class DBConn:
    """Context manager for DB connections — returns dict rows from both PG and SQLite"""
    def __enter__(self):
        if USE_PG:
            self.conn = DB_POOL.getconn()
            self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
            self.cur = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.cur.close()
        if USE_PG:
            DB_POOL.putconn(self.conn)
        else:
            self.conn.close()

    def execute(self, sql, params=()):
        # Auto-convert ? to %s for postgres
        if USE_PG:
            sql = sql.replace('?', '%s')
        self.cur.execute(sql, params)
        return self

    def fetchall(self):
        rows = self.cur.fetchall()
        return [dict(r) for r in rows]


# ── Schema initialization ─────────────────────────────────────────────────────
def init_db():
    log.info("Initializing DB schema...")
    schema_pg = [
        """CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            date TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'one-time',
            tmpl_id TEXT,
            slip TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            due_day INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS month_generated (
            month_key TEXT NOT NULL,
            tmpl_id TEXT NOT NULL,
            PRIMARY KEY(month_key, tmpl_id)
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
    ]
    schema_sqlite = """
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other', date TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'one-time', tmpl_id TEXT, slip TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            due_day INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS month_generated (
            month_key TEXT NOT NULL, tmpl_id TEXT NOT NULL,
            PRIMARY KEY(month_key, tmpl_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    """

    try:
        if USE_PG:
            with DBConn() as db:
                for stmt in schema_pg:
                    db.execute(stmt)
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.executescript(schema_sqlite)
            conn.commit()
            conn.close()
        log.info("✅ DB schema ready")
    except Exception as e:
        log.error(f"DB init failed: {e}")
        traceback.print_exc()
        raise


# Initialize DB at import time (runs once per worker)
if USE_PG and DB_POOL is None:
    log.error("Cannot proceed without DB pool")
    sys.exit(1)

init_db()

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.errorhandler(Exception)
def handle_error(e):
    log.error(f"Unhandled error: {e}")
    traceback.print_exc()
    return jsonify({'error': str(e)}), 500


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/health')
def health():
    """Railway healthcheck endpoint"""
    try:
        with DBConn() as db:
            db.execute("SELECT 1")
            db.fetchall()
        return jsonify({'ok': True, 'db': 'connected'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Expenses API ──────────────────────────────────────────────────────────────
@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    with DBConn() as db:
        db.execute("SELECT id,name,amount,category,date,type,tmpl_id,slip FROM expenses ORDER BY date DESC")
        return jsonify(db.fetchall())


@app.route('/api/expenses', methods=['POST'])
def add_expense():
    b = request.get_json() or {}
    eid = b.get('id') or f"e{int(datetime.now().timestamp() * 1000)}"
    params = (
        eid, b['name'], float(b['amount']),
        b.get('category', 'other'), b['date'],
        b.get('type', 'one-time'),
        b.get('tmplId') or b.get('tmpl_id'),
        b.get('slip'),
    )
    with DBConn() as db:
        if USE_PG:
            db.execute("""
                INSERT INTO expenses(id,name,amount,category,date,type,tmpl_id,slip)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET
                  name=EXCLUDED.name, amount=EXCLUDED.amount,
                  category=EXCLUDED.category, date=EXCLUDED.date,
                  type=EXCLUDED.type,
                  slip=COALESCE(EXCLUDED.slip, expenses.slip)
            """, params)
        else:
            db.execute("""
                INSERT OR REPLACE INTO expenses
                (id,name,amount,category,date,type,tmpl_id,slip)
                VALUES(?,?,?,?,?,?,?,?)
            """, params)
    return jsonify({'ok': True, 'id': eid})


@app.route('/api/expenses/<eid>', methods=['PUT'])
def update_expense(eid):
    b = request.get_json() or {}
    params = (
        b['name'], float(b['amount']), b.get('category', 'other'),
        b['date'], b.get('type', 'one-time'), b.get('slip'), eid,
    )
    with DBConn() as db:
        if USE_PG:
            db.execute("""
                UPDATE expenses SET name=%s, amount=%s, category=%s,
                  date=%s, type=%s, slip=COALESCE(%s, slip)
                WHERE id=%s
            """, params)
        else:
            db.execute("""
                UPDATE expenses SET name=?, amount=?, category=?,
                  date=?, type=?, slip=COALESCE(?, slip)
                WHERE id=?
            """, params)
    return jsonify({'ok': True})


@app.route('/api/expenses/<eid>', methods=['DELETE'])
def delete_expense(eid):
    with DBConn() as db:
        db.execute("DELETE FROM expenses WHERE id=?", (eid,))
    return jsonify({'ok': True})


# ── Templates API ─────────────────────────────────────────────────────────────
@app.route('/api/templates', methods=['GET'])
def get_templates():
    with DBConn() as db:
        db.execute("SELECT id,name,amount,category,due_day FROM templates ORDER BY created_at")
        return jsonify(db.fetchall())


@app.route('/api/templates', methods=['POST'])
def add_template():
    b = request.get_json() or {}
    tid = b.get('id') or f"t{int(datetime.now().timestamp() * 1000)}"
    params = (
        tid, b['name'], float(b['amount']),
        b.get('category', 'other'), int(b.get('dueDay', 1)),
    )
    with DBConn() as db:
        if USE_PG:
            db.execute("""
                INSERT INTO templates(id,name,amount,category,due_day)
                VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET
                  name=EXCLUDED.name, amount=EXCLUDED.amount,
                  category=EXCLUDED.category, due_day=EXCLUDED.due_day
            """, params)
        else:
            db.execute("""
                INSERT OR REPLACE INTO templates(id,name,amount,category,due_day)
                VALUES(?,?,?,?,?)
            """, params)
    return jsonify({'ok': True, 'id': tid})


@app.route('/api/templates/<tid>', methods=['PUT'])
def update_template(tid):
    b = request.get_json() or {}
    params = (
        b['name'], float(b['amount']), b.get('category', 'other'),
        int(b.get('dueDay', 1)), tid,
    )
    with DBConn() as db:
        db.execute("UPDATE templates SET name=?, amount=?, category=?, due_day=? WHERE id=?", params)
    return jsonify({'ok': True})


@app.route('/api/templates/<tid>', methods=['DELETE'])
def delete_template(tid):
    with DBConn() as db:
        db.execute("DELETE FROM templates WHERE id=?", (tid,))
    return jsonify({'ok': True})


# ── Month generated ───────────────────────────────────────────────────────────
@app.route('/api/month-generated', methods=['GET'])
def get_month_generated():
    with DBConn() as db:
        db.execute("SELECT month_key, tmpl_id FROM month_generated")
        rows = db.fetchall()
    result = {}
    for row in rows:
        k = row['month_key']
        result.setdefault(k, []).append(row['tmpl_id'])
    return jsonify(result)


@app.route('/api/month-generated', methods=['POST'])
def set_month_generated():
    body = request.get_json() or {}
    with DBConn() as db:
        for month_key, tmpl_ids in body.items():
            for tid in tmpl_ids:
                if USE_PG:
                    db.execute(
                        "INSERT INTO month_generated(month_key,tmpl_id) VALUES(%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (month_key, tid)
                    )
                else:
                    db.execute(
                        "INSERT OR IGNORE INTO month_generated(month_key,tmpl_id) VALUES(?,?)",
                        (month_key, tid)
                    )
    return jsonify({'ok': True})


# ── Settings API ──────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    with DBConn() as db:
        db.execute("SELECT key, value FROM settings")
        rows = db.fetchall()
    return jsonify({r['key']: r['value'] for r in rows})


@app.route('/api/settings', methods=['POST'])
def save_settings():
    body = request.get_json() or {}
    with DBConn() as db:
        for k, v in body.items():
            val = str(v) if v is not None else ''
            if USE_PG:
                db.execute(
                    "INSERT INTO settings(key,value) VALUES(%s,%s) "
                    "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                    (k, val)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                    (k, val)
                )
    return jsonify({'ok': True})


# ── SMS Proxy (Thaibulksms) ───────────────────────────────────────────────────
@app.route('/api/sms/test', methods=['POST'])
def sms_test():
    """Proxy Thaibulksms API to avoid CORS"""
    import urllib.request
    import urllib.error

    b = request.get_json() or {}
    api_key = b.get('apiKey', '')
    api_secret = b.get('apiSecret', '')
    phone = b.get('phone', '')
    message = b.get('message', '[WIPTOWN] ทดสอบ SMS สำเร็จ!')

    if not api_key or not api_secret or not phone:
        return jsonify({'ok': False, 'error': 'กรุณากรอก API Key, Secret และเบอร์โทร'}), 400

    # Thaibulksms API v2
    url = 'https://bulk.thaibulksms.com/sms'
    payload = json.dumps({
        'msisdn': phone,
        'message': message,
        'sender': 'WIPTOWN',
    }).encode('utf-8')

    # Basic auth: api_key:api_secret
    import base64
    credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()

    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Basic {credentials}')

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return jsonify({'ok': True, 'result': result})
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ''
        log.error(f"Thaibulksms HTTP error {e.code}: {body}")
        return jsonify({'ok': False, 'error': f'HTTP {e.code}: {body}'}), 502
    except Exception as e:
        log.error(f"Thaibulksms error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 502


# ── Local dev entry point ─────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    log.info(f"Running on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
