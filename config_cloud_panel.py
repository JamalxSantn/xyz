# Config Cloud Panel — Cheat-Sync + Admin Panel mit eigenen Logins
#
# Erweiterung von discord_key_bot.py (modulare Montage, wie chat_party.py).
#
#   Cheat-API (unverändert zum config-cloud Node-Server):
#     POST /cloud/export  { hwid, pcName, windowsUser, config }
#     GET  /cloud/import?hwid=XXX
#
#   Panel (eigene Accounts, Login = Username + Passwort):
#     GET  /cloud/panel                -> Admin-Panel (templates/config_panel.html)
#     POST /admin/login { username, password } -> { success, token }
#     GET  /admin/configs              (x-admin-token)
#     GET  /admin/configs/<hwid>
#     DELETE /admin/configs/<hwid>
#     POST /admin/configs/<hwid>/reset
#     GET  /health
#
# Accounts/Sessions liegen in keys.db (Gist-gesichert => überlebt Render-Deploys).
# Configs liegen in cloud.db.
#
# Accounts werden im Discord-Bot erstellt:
#   !panelcreate <username> <passwort>   (nur im Config-Panel-Channel, nur Whitelist)

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import jsonify, render_template, request


# ---- Config ----

HWID_RE = re.compile(r"^[A-Z0-9_-]{3,64}$")
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
MAX_CONFIG_BYTES = 1 * 1024 * 1024
SESSION_HOURS = 12
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 15 * 60

_keys_db_path = None
_cloud_db_path = None

_login_fails = {}
_login_lock = threading.Lock()

_sync_fn = None


def set_panel_sync(fn):
    """Registriert den Gist-Sync (keys.db wird bei jedem Start aus Gist wiederhergestellt)."""
    global _sync_fn
    _sync_fn = fn


def sync_accounts_to_gist():
    """Sichert Accounts/Sessions sofort (keys.db = Gist-gesichert)."""
    if _sync_fn:
        try:
            _sync_fn()
        except Exception as e:
            print(f"[CONFIG-CLOUD] Gist-Sync fehlgeschlagen: {e}")


# ---- DB ----

def _connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlite3.Row
    return conn


def init_config_cloud(keys_db_path, cloud_db_path):
    """Legt alle Tabellen an. keys.db = Accounts/Sessions, cloud.db = Configs."""
    global _keys_db_path, _cloud_db_path
    _keys_db_path = keys_db_path
    _cloud_db_path = cloud_db_path

    conn = _connect(_keys_db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS panel_accounts (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT,
        last_login TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS panel_sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at TEXT,
        expires_at TEXT
    )""")
    conn.commit()
    conn.close()

    conn = _connect(_cloud_db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS panel_configs (
        hwid TEXT PRIMARY KEY,
        pc_name TEXT,
        windows_user TEXT,
        ip TEXT,
        user_agent TEXT,
        config TEXT NOT NULL,
        config_size INTEGER,
        created_at TEXT,
        updated_at TEXT,
        last_seen TEXT,
        reset_at TEXT
    )""")
    conn.commit()
    conn.close()


# ---- Accounts ----

def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 200000)
    return salt, digest.hex()


def panel_account_count():
    conn = _connect(_keys_db_path)
    n = conn.execute("SELECT COUNT(*) FROM panel_accounts").fetchone()[0]
    conn.close()
    return n


def create_panel_account(username, password, created_by=None):
    """Legt einen Panel-Account an. Gibt (ok, meldung) zurück."""
    username = (username or "").strip().lower()
    password = password or ""
    if not USERNAME_RE.match(username):
        return False, "Username muss 3-32 Zeichen aus a-z, 0-9, _ . - sein."
    if len(password) < 8:
        return False, "Passwort muss mindestens 8 Zeichen lang sein."
    if len(password) > 128:
        return False, "Passwort ist zu lang (max. 128)."

    salt, pw_hash = _hash_password(password)
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(_keys_db_path)
    try:
        conn.execute(
            "INSERT INTO panel_accounts (username, password_hash, password_salt, created_by, created_at) VALUES (?,?,?,?,?)",
            (username, pw_hash, salt, created_by, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"Account `{username}` existiert bereits."
    conn.close()
    return True, f"Account `{username}` wurde erstellt."


def set_panel_password(username, password):
    username = (username or "").strip().lower()
    if len(password or "") < 8:
        return False, "Passwort muss mindestens 8 Zeichen lang sein."
    salt, pw_hash = _hash_password(password)
    conn = _connect(_keys_db_path)
    cur = conn.execute(
        "UPDATE panel_accounts SET password_hash = ?, password_salt = ? WHERE username = ?",
        (pw_hash, salt, username),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return (bool(changed), f"Passwort für `{username}` geändert." if changed else f"Account `{username}` existiert nicht.")


def delete_panel_account(username):
    username = (username or "").strip().lower()
    conn = _connect(_keys_db_path)
    conn.execute("DELETE FROM panel_sessions WHERE username = ?", (username,))
    cur = conn.execute("DELETE FROM panel_accounts WHERE username = ?", (username,))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return (bool(changed), f"Account `{username}` gelöscht." if changed else f"Account `{username}` existiert nicht.")


def list_panel_accounts():
    conn = _connect(_keys_db_path)
    rows = conn.execute(
        "SELECT username, created_by, created_at, last_login FROM panel_accounts ORDER BY username"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Sessions ----

def _create_session(username):
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(hours=SESSION_HOURS)
    conn = _connect(_keys_db_path)
    conn.execute(
        "INSERT INTO panel_sessions (token, username, created_at, expires_at) VALUES (?,?,?,?)",
        (token, username, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
    )
    conn.execute("DELETE FROM panel_sessions WHERE expires_at < ?", (now.isoformat(timespec="seconds"),))
    conn.commit()
    conn.close()
    return token


def _session_username(token):
    if not token:
        return None
    conn = _connect(_keys_db_path)
    row = conn.execute("SELECT username, expires_at FROM panel_sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            conn = _connect(_keys_db_path)
            conn.execute("DELETE FROM panel_sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
            return None
    except ValueError:
        return None
    return row["username"]


def panel_authenticate(username, password):
    username = (username or "").strip().lower()
    conn = _connect(_keys_db_path)
    row = conn.execute(
        "SELECT password_hash, password_salt FROM panel_accounts WHERE username = ?", (username,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    salt, pw_hash = _hash_password(password or "", row["password_salt"])
    ok = secrets.compare_digest(pw_hash, row["password_hash"])
    if ok:
        conn.execute(
            "UPDATE panel_accounts SET last_login = ? WHERE username = ?",
            (datetime.now().isoformat(timespec="seconds"), username),
        )
        conn.commit()
    conn.close()
    return ok


def panel_auth_from_request():
    token = request.headers.get("x-admin-token") or ""
    if not token:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return _session_username(token)


# ---- Login-Rate-Limit ----

def _login_blocked(login_key):
    now = time.time()
    with _login_lock:
        entry = _login_fails.get(login_key)
        if not entry:
            return False
        first_ts, count = entry
        if now - first_ts > LOGIN_WINDOW_S:
            del _login_fails[login_key]
            return False
        return count >= LOGIN_MAX_FAILS


def _login_fail(login_key):
    now = time.time()
    with _login_lock:
        first_ts, count = _login_fails.get(login_key, (now, 0))
        if now - first_ts > LOGIN_WINDOW_S:
            first_ts, count = now, 0
        _login_fails[login_key] = (first_ts, count + 1)


def _login_ok(login_key):
    with _login_lock:
        _login_fails.pop(login_key, None)


# ---- Helfer ----

def _safe_hwid(value):
    if not isinstance(value, str):
        return ""
    value = value.strip().upper()
    return value if HWID_RE.match(value) else ""


def _clean_str(value, limit=128):
    if not isinstance(value, str):
        return ""
    return value[:limit].replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def _client_ip():
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def _require_auth():
    if panel_auth_from_request() is None:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return None


# ---- Flask-Routen ----

def register_config_cloud(app):
    @app.route("/cloud/export", methods=["POST", "OPTIONS"])
    def cloud_export():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "invalid json"}), 400

        hwid = _safe_hwid(data.get("hwid"))
        if not hwid:
            return jsonify({"success": False, "error": "missing hwid"}), 400
        if data.get("config") is None:
            return jsonify({"success": False, "error": "missing config"}), 400

        config = data.get("config")
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                return jsonify({"success": False, "error": "config not valid json"}), 400
        if not isinstance(config, dict):
            return jsonify({"success": False, "error": "config must be object"}), 400
        if len(json.dumps(config)) > MAX_CONFIG_BYTES:
            return jsonify({"success": False, "error": "config too large"}), 413

        pc_name = _clean_str(data.get("pcName") or data.get("pc_name") or data.get("computerName") or "")
        windows_user = _clean_str(data.get("windowsUser") or data.get("windows_user") or data.get("username") or "")
        ip = _clean_str(_client_ip(), 64)
        user_agent = _clean_str(request.headers.get("user-agent", ""), 256)
        now = datetime.now().isoformat(timespec="seconds")

        conn = _connect(_cloud_db_path)
        existing = conn.execute("SELECT created_at FROM panel_configs WHERE hwid = ?", (hwid,)).fetchone()
        conn.execute(
            """INSERT INTO panel_configs
               (hwid, pc_name, windows_user, ip, user_agent, config, config_size, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(hwid) DO UPDATE SET
                 pc_name=excluded.pc_name, windows_user=excluded.windows_user, ip=excluded.ip,
                 user_agent=excluded.user_agent, config=excluded.config,
                 config_size=excluded.config_size, updated_at=excluded.updated_at""",
            (hwid, pc_name, windows_user, ip, user_agent, json.dumps(config), len(json.dumps(config)),
             existing["created_at"] if existing else now, now),
        )
        conn.commit()
        conn.close()
        print(f"[CONFIG-CLOUD] EXPORT {hwid} pc={pc_name} user={windows_user} {'(update)' if existing else '(NEU)'}")
        return jsonify({"success": True})

    @app.route("/cloud/import", methods=["GET", "OPTIONS"])
    def cloud_import():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        hwid = _safe_hwid(request.args.get("hwid", ""))
        if not hwid:
            return jsonify({"success": False, "error": "missing hwid"}), 400

        conn = _connect(_cloud_db_path)
        row = conn.execute("SELECT config FROM panel_configs WHERE hwid = ?", (hwid,)).fetchone()
        now = datetime.now().isoformat(timespec="seconds")
        if row:
            conn.execute(
                "UPDATE panel_configs SET last_seen = ?, ip = COALESCE(?, ip) WHERE hwid = ?",
                (now, _clean_str(_client_ip(), 64) or None, hwid),
            )
            conn.commit()
        conn.close()

        if not row:
            return jsonify({"success": False, "error": "no config"})
        try:
            config = json.loads(row["config"])
        except ValueError:
            return jsonify({"success": False, "error": "no config"})
        if not config:
            return jsonify({"success": False, "error": "no config"})
        return jsonify({"success": True, "config": config})

    @app.route("/cloud/panel", methods=["GET"])
    @app.route("/panel", methods=["GET"])
    def cloud_panel():
        return render_template("config_panel.html")

    @app.route("/admin/login", methods=["POST", "OPTIONS"])
    def admin_login():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""

        login_key = f"{_client_ip()}|{username}"
        if _login_blocked(login_key):
            return jsonify({"success": False, "error": "too many attempts, try again later"}), 429

        if panel_account_count() == 0:
            return jsonify({"success": False, "error": "no accounts yet - create one with !panelcreate"}), 401

        if not panel_authenticate(username, password):
            _login_fail(login_key)
            return jsonify({"success": False, "error": "wrong username or password"}), 401

        _login_ok(login_key)
        token = _create_session(username)
        print(f"[CONFIG-CLOUD] LOGIN {username} ip={_client_ip()}")
        return jsonify({"success": True, "token": token, "username": username})

    @app.route("/admin/configs", methods=["GET", "OPTIONS"])
    def admin_configs():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        denied = _require_auth()
        if denied:
            return denied

        conn = _connect(_cloud_db_path)
        rows = conn.execute(
            """SELECT hwid, pc_name, windows_user, ip, config_size, created_at, updated_at, last_seen
               FROM panel_configs ORDER BY updated_at DESC"""
        ).fetchall()
        conn.close()

        now_ms = time.time() * 1000
        configs = []
        for r in rows:
            created = r["created_at"] or ""
            is_new = False
            try:
                is_new = (now_ms - datetime.fromisoformat(created).timestamp() * 1000) < 10 * 60 * 1000
            except ValueError:
                pass
            configs.append({
                "hwid": r["hwid"],
                "pcName": r["pc_name"] or "",
                "windowsUser": r["windows_user"] or "",
                "ip": r["ip"] or "",
                "configSize": r["config_size"] or 0,
                "createdAt": created,
                "updatedAt": r["updated_at"] or "",
                "lastSeen": r["last_seen"] or "",
                "isNew": is_new,
            })
        return jsonify({"success": True, "count": len(configs), "configs": configs})

    @app.route("/admin/configs/<path:hwid>", methods=["GET", "DELETE", "OPTIONS"])
    @app.route("/admin/configs/<path:hwid>/reset", methods=["POST", "OPTIONS"])
    def admin_config_detail(hwid):
        if request.method == "OPTIONS":
            return jsonify({}), 200
        denied = _require_auth()
        if denied:
            return denied

        hwid = _safe_hwid(hwid.rstrip("/"))
        if not hwid:
            return jsonify({"success": False, "error": "invalid hwid"}), 400
        is_reset = request.path.endswith("/reset")

        conn = _connect(_cloud_db_path)
        if is_reset:
            if request.method != "POST":
                conn.close()
                return jsonify({"success": False, "error": "method not allowed"}), 405
            cur = conn.execute(
                "UPDATE panel_configs SET config = '{}', config_size = 2, updated_at = ?, reset_at = ? WHERE hwid = ?",
                (datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), hwid),
            )
            conn.commit()
            conn.close()
            if not cur.rowcount:
                return jsonify({"success": False, "error": "not found"}), 404
            print(f"[CONFIG-CLOUD] RESET {hwid}")
            return jsonify({"success": True})

        row = conn.execute("SELECT * FROM panel_configs WHERE hwid = ?", (hwid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "error": "not found"}), 404

        if request.method == "DELETE":
            conn.execute("DELETE FROM panel_configs WHERE hwid = ?", (hwid,))
            conn.commit()
            conn.close()
            print(f"[CONFIG-CLOUD] DELETE {hwid}")
            return jsonify({"success": True})

        if request.method != "GET":
            conn.close()
            return jsonify({"success": False, "error": "method not allowed"}), 405

        try:
            config = json.loads(row["config"])
        except ValueError:
            config = {}
        conn.close()
        return jsonify({"success": True, "entry": {
            "hwid": row["hwid"],
            "pcName": row["pc_name"] or "",
            "windowsUser": row["windows_user"] or "",
            "ip": row["ip"] or "",
            "userAgent": row["user_agent"] or "",
            "config": config,
            "configSize": row["config_size"] or 0,
            "createdAt": row["created_at"] or "",
            "updatedAt": row["updated_at"] or "",
            "lastSeen": row["last_seen"] or "",
            "resetAt": row["reset_at"] or "",
        }})

    @app.route("/health", methods=["GET"])
    def health():
        conn = _connect(_cloud_db_path)
        n = conn.execute("SELECT COUNT(*) FROM panel_configs").fetchone()[0]
        conn.close()
        return jsonify({"success": True, "count": n})
