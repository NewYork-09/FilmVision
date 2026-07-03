"""
auth.py — FilmVision Authentication & Saved Results
Provides: /auth/register, /auth/login, /auth/logout, /auth/me,
          /auth/save_result, /auth/saved_results, /auth/delete_result
Uses SQLite (filmvision_users.db) — no extra dependencies beyond what Flask already uses.
Password hashing via werkzeug.security (bundled with Flask).
"""

from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, json

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# ── DB path — sits next to app.py by default. Override with the DB_PATH env var
# once deployed, if your host provides a persistent volume/disk mounted somewhere
# else (e.g. Render/Railway/Fly.io persistent disks). This matters because on
# hosts WITHOUT persistent storage, anything written to the local filesystem —
# including this file — gets wiped on every restart or redeploy, silently
# deleting every registered account and saved result. Check your host's docs for
# whether its filesystem is persistent before relying on this as-is in production.
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "filmvision_users.db"))


# ── Schema init ────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    UNIQUE NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            created  TEXT    DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            pitch       TEXT,
            genre       TEXT,
            tone        TEXT,
            result_json TEXT    NOT NULL,
            saved_at    TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    con.commit()
    con.close()

init_db()


# ── Helper ─────────────────────────────────────────────────────────────
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── Routes ─────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data     = request.json or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not username or not email or not password:
        return jsonify({"error": "All fields are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    hashed = generate_password_hash(password)
    try:
        con = get_db()
        con.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (username, email, hashed)
        )
        con.commit()
        row = con.execute("SELECT id, username, email FROM users WHERE email = ?", (email,)).fetchone()
        session["user_id"]  = row["id"]
        session["username"] = row["username"]
        con.close()
        return jsonify({"ok": True, "user": {"id": row["id"], "username": row["username"], "email": row["email"]}})
    except sqlite3.IntegrityError as e:
        err_str = str(e)
        if "username" in err_str:
            return jsonify({"error": "Username already taken."}), 409
        if "email" in err_str:
            return jsonify({"error": "Email already registered."}), 409
        return jsonify({"error": "Registration failed."}), 409


@auth_bp.route("/login", methods=["POST"])
def login():
    data     = request.json or {}
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    con = get_db()
    row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    con.close()

    if not row or not check_password_hash(row["password"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_id"]  = row["id"]
    session["username"] = row["username"]
    return jsonify({"ok": True, "user": {"id": row["id"], "username": row["username"], "email": row["email"]}})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"user": None})
    con = get_db()
    row = con.execute("SELECT id, username, email FROM users WHERE id = ?", (uid,)).fetchone()
    con.close()
    if not row:
        session.clear()
        return jsonify({"user": None})
    return jsonify({"user": {"id": row["id"], "username": row["username"], "email": row["email"]}})


@auth_bp.route("/save_result", methods=["POST"])
def save_result():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    data        = request.json or {}
    title       = (data.get("title")  or "Untitled").strip()[:120]
    pitch       = (data.get("pitch")  or "").strip()[:300]
    genre       = (data.get("genre")  or "").strip()[:120]
    tone        = (data.get("tone")   or "").strip()[:120]
    result_json = json.dumps(data.get("result") or {})

    con = get_db()
    cur = con.execute(
        "INSERT INTO saved_results (user_id, title, pitch, genre, tone, result_json) VALUES (?,?,?,?,?,?)",
        (uid, title, pitch, genre, tone, result_json)
    )
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return jsonify({"ok": True, "id": new_id})


@auth_bp.route("/saved_results", methods=["GET"])
def saved_results():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    con  = get_db()
    rows = con.execute(
        "SELECT id, title, pitch, genre, tone, saved_at FROM saved_results WHERE user_id = ? ORDER BY saved_at DESC",
        (uid,)
    ).fetchall()
    con.close()
    return jsonify({"results": [dict(r) for r in rows]})


@auth_bp.route("/saved_result/<int:rid>", methods=["GET"])
def get_saved_result(rid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    con = get_db()
    row = con.execute(
        "SELECT * FROM saved_results WHERE id = ? AND user_id = ?", (rid, uid)
    ).fetchone()
    con.close()
    if not row:
        return jsonify({"error": "Not found."}), 404

    r = dict(row)
    r["result"] = json.loads(r.get("result_json") or "{}")
    del r["result_json"]
    return jsonify(r)


@auth_bp.route("/delete_result/<int:rid>", methods=["DELETE"])
def delete_result(rid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    con = get_db()
    con.execute("DELETE FROM saved_results WHERE id = ? AND user_id = ?", (rid, uid))
    con.commit()
    con.close()
    return jsonify({"ok": True})