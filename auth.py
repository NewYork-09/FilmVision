"""
auth.py — FilmVision Authentication & Saved Results
Provides: /auth/register, /auth/login, /auth/logout, /auth/me,
          /auth/save_result, /auth/saved_results, /auth/delete_result

Uses PostgreSQL (via DATABASE_URL, e.g. a free Neon database) instead of local
SQLite. This matters specifically because Render's free tier has no persistent
disk — every time the free instance spins down from inactivity and spins back
up, it starts with a completely fresh, empty local filesystem. A SQLite file
sitting next to app.py would get silently wiped on every such cycle, which is
exactly what was happening (accounts vanishing, "Invalid email or password"
after idle). Postgres on Neon lives on its own persistent infrastructure,
totally decoupled from Render's ephemeral compute, so it survives regardless
of how often the app instance sleeps/wakes/redeploys.

Password hashing via werkzeug.security (bundled with Flask), unchanged.
"""

from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import os, json

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# ── DB connection — set DATABASE_URL on Render to your Neon connection string.
# For local development, set the same DATABASE_URL in your local .env file
# (Neon's free tier works fine for local dev too — no need for a separate local
# database).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it to your Neon (or other Postgres) "
        "connection string as an environment variable — auth.py cannot start "
        "without it."
    )


# ── Helper ─────────────────────────────────────────────────────────────
def get_db():
    con = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return con


# ── Schema init ────────────────────────────────────────────────────────
def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       SERIAL PRIMARY KEY,
            username TEXT   UNIQUE NOT NULL,
            email    TEXT   UNIQUE NOT NULL,
            password TEXT   NOT NULL,
            created  TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_results (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT    NOT NULL,
            pitch       TEXT,
            genre       TEXT,
            tone        TEXT,
            result_json TEXT    NOT NULL,
            saved_at    TIMESTAMP DEFAULT NOW()
        )
    """)
    con.commit()
    cur.close()
    con.close()

init_db()


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

    con = get_db()
    cur = con.cursor()

    # Pre-check for existing username/email rather than relying on parsing the
    # text of a Postgres IntegrityError (its message format differs from
    # SQLite's and isn't something to depend on for user-facing error text).
    cur.execute("SELECT username, email FROM users WHERE username = %s OR email = %s",
                (username, email))
    existing = cur.fetchone()
    if existing:
        cur.close(); con.close()
        if existing["username"] == username:
            return jsonify({"error": "Username already taken."}), 409
        return jsonify({"error": "Email already registered."}), 409

    hashed = generate_password_hash(password)
    try:
        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s) RETURNING id, username, email",
            (username, email, hashed)
        )
        row = cur.fetchone()
        con.commit()
        session["user_id"]  = row["id"]
        session["username"] = row["username"]
        return jsonify({"ok": True, "user": {"id": row["id"], "username": row["username"], "email": row["email"]}})
    except psycopg2.Error:
        con.rollback()
        return jsonify({"error": "Registration failed."}), 409
    finally:
        cur.close(); con.close()


@auth_bp.route("/login", methods=["POST"])
def login():
    data     = request.json or {}
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close(); con.close()

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
    cur = con.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    cur.close(); con.close()
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
    cur = con.cursor()
    cur.execute(
        "INSERT INTO saved_results (user_id, title, pitch, genre, tone, result_json) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (uid, title, pitch, genre, tone, result_json)
    )
    new_id = cur.fetchone()["id"]
    con.commit()
    cur.close(); con.close()
    return jsonify({"ok": True, "id": new_id})


@auth_bp.route("/saved_results", methods=["GET"])
def saved_results():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, title, pitch, genre, tone, saved_at FROM saved_results WHERE user_id = %s ORDER BY saved_at DESC",
        (uid,)
    )
    rows = cur.fetchall()
    cur.close(); con.close()
    return jsonify({"results": [dict(r) for r in rows]})


@auth_bp.route("/saved_result/<int:rid>", methods=["GET"])
def get_saved_result(rid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in."}), 401

    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM saved_results WHERE id = %s AND user_id = %s", (rid, uid)
    )
    row = cur.fetchone()
    cur.close(); con.close()
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
    cur = con.cursor()
    cur.execute("DELETE FROM saved_results WHERE id = %s AND user_id = %s", (rid, uid))
    con.commit()
    cur.close(); con.close()
    return jsonify({"ok": True})