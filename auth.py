"""
auth.py — FilmVision Authentication & Saved Results
Provides: /auth/register, /auth/login, /auth/logout, /auth/me,
          /auth/save_result, /auth/saved_results, /auth/delete_result,
          /auth/forgot_password, /auth/reset_password, /auth/verify_reset_token

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

── FORGOT PASSWORD ──────────────────────────────────────────────────────
Flow: /auth/forgot_password (POST, {email}) generates a single-use, expiring
token, stores only its SHA-256 hash in password_reset_tokens (never the raw
token — same reason passwords are hashed, not stored plain: a DB read/leak
shouldn't hand out live credentials), and emails a link containing the raw
token. /auth/reset_password (POST, {token, password}) looks the raw token up
by its hash, checks it's unused and unexpired, then updates the password.
Email delivery is via plain SMTP (SMTP_HOST/PORT/USER/PASSWORD/FROM env vars)
— if SMTP_HOST isn't set, this degrades to printing the reset link to the
console instead of raising, the same graceful-degradation pattern app.py uses
for its optional ML dependencies, so local dev works without a real mailbox.
"""

from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import os, json, secrets, hashlib, threading, requests
from datetime import datetime, timedelta

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

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# ── Password reset config ────────────────────────────────────────────────
# SMTP_HOST unset => reset links are printed to the console instead of emailed
# (see _send_reset_email) — fine for local dev, but set these on Render for
# real delivery. FRONTEND_URL only needs setting if the Vue app is deployed
# somewhere other than this same Flask origin (see app.py's same-origin note);
# otherwise the reset link falls back to the request's own host.
BREVO_API_KEY      = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")   # must be a sender verified in Brevo
BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME", "FilmVision")
FRONTEND_URL       = os.getenv("FRONTEND_URL", "").rstrip("/")
RESET_TOKEN_TTL_MINUTES = 30


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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT    NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            used       BOOLEAN NOT NULL DEFAULT FALSE,
            created    TIMESTAMP DEFAULT NOW()
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


# ── Forgot password: helpers ─────────────────────────────────────────────
def _frontend_base_url():
    """Where to point the emailed reset link. Prefers an explicit FRONTEND_URL env
    var (needed whenever the Vue frontend isn't served same-origin from this Flask
    app — e.g. a separate static-host deploy) and otherwise falls back to the
    request's own origin, which is correct for the same-origin deploy layout
    app.py documents (frontend/dist served directly by this Flask app)."""
    if FRONTEND_URL:
        return FRONTEND_URL
    return request.host_url.rstrip("/")


def _send_reset_email_blocking(to_email, username, reset_link):
    subject = "Reset your FilmVision password"
    body = (
        f"Hi {username},\n\n"
        f"We received a request to reset your FilmVision password. Click the link "
        f"below to choose a new one. This link expires in {RESET_TOKEN_TTL_MINUTES} "
        f"minutes:\n\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email. Your "
        f"password will not be changed.\n\n- FilmVision"
    )

    if not (BREVO_API_KEY and BREVO_SENDER_EMAIL):
        print(f"[Auth] Brevo not configured - reset link for {to_email}: {reset_link}")
        return

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={
                "sender":      {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
                "to":          [{"email": to_email, "name": username}],
                "subject":     subject,
                "textContent": body,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print(f"[Auth] Reset email accepted by Brevo for {to_email}: {resp.text[:120]}")
        else:
            print(f"[Auth] Brevo rejected reset email for {to_email}: "
                  f"HTTP {resp.status_code} {resp.text[:300]} - link: {reset_link}")
    except Exception as e:
        print(f"[Auth] Failed to send reset email to {to_email}: "
              f"{type(e).__name__}: {e} - link: {reset_link}")


def _send_reset_email(to_email, username, reset_link):
    """Sends in a background thread so the response time is the same whether or
    not the email exists (otherwise a slow send would reveal registered emails)."""
    threading.Thread(
        target=_send_reset_email_blocking,
        args=(to_email, username, reset_link),
        daemon=True,
    ).start()


@auth_bp.route("/forgot_password", methods=["POST"])
def forgot_password():
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required."}), 400

    # Same response whether or not the email exists — an endpoint that answers
    # differently for "no such account" vs "email sent" lets anyone probe which
    # emails are registered. Build it once and return it on every path below.
    generic_ok = jsonify({
        "ok": True,
        "message": "If an account exists for that email, we've sent password reset instructions. If you don't see it within a few minutes, please check your spam or junk folder."
    })

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id, username FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row:
        cur.close(); con.close()
        return generic_ok

    token      = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)

    cur.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (row["id"], token_hash, expires_at)
    )
    con.commit()
    cur.close(); con.close()

    reset_link = f"{_frontend_base_url()}/?reset_token={token}"
    _send_reset_email(email, row["username"], reset_link)

    return generic_ok


@auth_bp.route("/verify_reset_token", methods=["GET"])
def verify_reset_token():
    """Lets the frontend check a token's validity BEFORE showing the "set new
    password" form, so a user who clicks an old/used link finds out immediately
    rather than filling in a new password first and only then being told it
    failed."""
    token = (request.args.get("token") or "").strip()
    if not token:
        return jsonify({"valid": False})

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT expires_at, used FROM password_reset_tokens WHERE token_hash = %s",
        (token_hash,)
    )
    row = cur.fetchone()
    cur.close(); con.close()

    if not row or row["used"] or row["expires_at"] < datetime.utcnow():
        return jsonify({"valid": False})
    return jsonify({"valid": True})


@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    data     = request.json or {}
    token    = (data.get("token")    or "").strip()
    password = (data.get("password") or "").strip()

    if not token or not password:
        return jsonify({"error": "Token and new password are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = %s AND used = FALSE",
        (token_hash,)
    )
    row = cur.fetchone()
    if not row or row["expires_at"] < datetime.utcnow():
        cur.close(); con.close()
        return jsonify({"error": "This reset link is invalid or has expired. Please request a new one."}), 400

    hashed = generate_password_hash(password)
    cur.execute("UPDATE users SET password = %s WHERE id = %s", (hashed, row["user_id"]))
    cur.execute("UPDATE password_reset_tokens SET used = TRUE WHERE id = %s", (row["id"],))
    # A successful reset also retires any OTHER still-outstanding tokens for this
    # user — an old, forgotten reset email from a previous request shouldn't
    # remain live once the password has actually been changed.
    cur.execute(
        "UPDATE password_reset_tokens SET used = TRUE WHERE user_id = %s AND id != %s",
        (row["user_id"], row["id"])
    )
    con.commit()
    cur.close(); con.close()
    return jsonify({"ok": True, "message": "Password updated. You can now log in with your new password."})


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