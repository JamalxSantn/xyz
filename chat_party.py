# =================================
# Chat + Party API for the cheat menu (rayx bot, Flask)
# =================================
#
# Live data source for the in-menu Party/Chat page:
#   - online users (+ roles OWNER / CO-OWNER / DEVELOPER)
#   - global chat + per-party chat (real send/receive, polling)
#   - party create / join with 4-digit code
#
# Identity chain: license key + discord_id + hwid, verified against the
# keys table (same checks as cloud_auth). Discord name/avatar/roles come
# from the Discord REST API (Bot token), so this works from Flask threads.
#
# Mounted from discord_key_bot.py:
#   from chat_party import register_chat_party
#   register_chat_party(app)
#
# Chat + party logs go to CHAT_LOG_CHANNEL_ID.

import json
import os
import random
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

from flask import jsonify, request

GUILD_ID = "1537561860163768412"
MASTER_ID = "1027571297514967140"
CHAT_LOG_CHANNEL_ID = "1553044064491012176"

ROLE_OWNER = "OWNER"
ROLE_CO_OWNER = "CO-OWNER"
ROLE_DEVELOPER = "DEVELOPER"

HEARTBEAT_TTL = 60
IDENTITY_CACHE_TTL = 5 * 60
PARTY_MEMBER_TTL = 3 * 60
MAX_TEXT_LEN = 500
MAX_MESSAGES = 100
SEND_DEDUP_MS = 2000
CREATE_DEDUP_MS = 5000

# discord id / username -> role override (checked before guild roles)
CHAT_USERS = {
    "1027571297514967140": "OWNER",
    "jamal": "OWNER",
    "snoweody": "DEVELOPER",
}


def _db_path():
    return os.environ.get(
        "DATABASE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.db"),
    )


def _token():
    return os.environ.get("DISCORD_TOKEN", "")


def _discord_get(path, timeout=6):
    token = _token()
    if not token:
        return None
    try:
        req = urllib.request.Request(
            "https://discord.com/api/v10" + path,
            headers={"Authorization": "Bot " + token, "User-Agent": "RayXBot/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _discord_post_channel(channel_id, payload, timeout=6):
    token = _token()
    if not token:
        return False
    try:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://discord.com/api/v10/channels/%s/messages" % channel_id,
            data=body,
            headers={
                "Authorization": "Bot " + token,
                "Content-Type": "application/json",
                "User-Agent": "RayXBot/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception as e:
        print("[CHAT-LOG] Fehler: %s" % e)
        return False


def _role_rank(role):
    if role == ROLE_OWNER:
        return 0
    if role == ROLE_CO_OWNER:
        return 1
    if role == ROLE_DEVELOPER:
        return 2
    return 3


def _norm_role_label(value):
    s = "".join(str(value if value is not None else "").upper().split())
    s = s.replace("_", "").replace("-", "")
    if s == "OWNER":
        return "OWNER"
    if s == "COOWNER":
        return "CO-OWNER"
    if s in ("DEVELOPER", "DEV"):
        return "DEVELOPER"
    return ""


def _override_role(discord_id, username, display):
    cands = set()
    if discord_id:
        cands.add(str(discord_id))
    if username:
        cands.add(str(username).lower())
    if display:
        cands.add(str(display).lower())
    for key, role in CHAT_USERS.items():
        r = _norm_role_label(role)
        if not r:
            continue
        if str(key) in cands or str(key).lower() in cands:
            return r
    return ""


_guild_roles_cache = {"at": 0.0, "map": {}}


def _guild_role_names(role_ids):
    """Map guild role ids -> names (cached 10 min)."""
    now = time.time()
    if now - _guild_roles_cache["at"] > 600:
        data = _discord_get("/guilds/%s/roles" % GUILD_ID) or []
        mapping = {}
        try:
            for r in data:
                mapping[str(r.get("id"))] = str(r.get("name", ""))
        except Exception:
            mapping = {}
        _guild_roles_cache["map"] = mapping
        _guild_roles_cache["at"] = now
    mapping = _guild_roles_cache["map"]
    return [mapping.get(str(rid), "") for rid in (role_ids or [])]


def _resolve_role(discord_id, username, display):
    if str(discord_id or "") == MASTER_ID:
        return ROLE_OWNER
    role = _override_role(discord_id, username, display)
    if role:
        return role
    if not discord_id:
        return ""
    member = _discord_get("/guilds/%s/members/%s" % (GUILD_ID, discord_id))
    if not member:
        return ""
    try:
        names = [n.lower() for n in _guild_role_names(member.get("roles", []))]
    except Exception:
        return ""
    has_co = any("co-owner" in n or "co owner" in n or "coowner" in n for n in names)
    has_owner = any("owner" in n for n in names)
    has_dev = any("developer" in n or n == "dev" for n in names)
    if has_owner and not has_co:
        return ROLE_OWNER
    if has_co:
        return ROLE_CO_OWNER
    if has_dev:
        return ROLE_DEVELOPER
    return ""


def _clean_text(value):
    s = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return s[:MAX_TEXT_LEN]


def _expires_text(expires_at):
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo:
            exp = exp.replace(tzinfo=None)
        delta = exp - datetime.now()
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "Expired"
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        if days > 0:
            return "%dd %dh left" % (days, hours)
        if hours > 0:
            return "%dh %dm left" % (hours, mins)
        return "%dm left" % mins
    except Exception:
        return "Lifetime"


def _is_expired(expires_at):
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo:
            exp = exp.replace(tzinfo=None)
        return datetime.now() > exp
    except Exception:
        return True


def _avatar_url(discord_id, avatar_hash, discriminator=None, size=64):
    if avatar_hash:
        ext = "gif" if str(avatar_hash).startswith("a_") else "png"
        return "https://cdn.discordapp.com/avatars/%s/%s.%s?size=%d" % (discord_id, avatar_hash, ext, size)
    # no custom avatar -> Discord default avatar (always a valid picture)
    idx = 0
    try:
        if discriminator is not None and str(discriminator) != "0":
            idx = int(str(discriminator)) % 5
        else:
            idx = (int(str(discord_id)) >> 22) % 6
    except Exception:
        idx = 0
    return "https://cdn.discordapp.com/embed/avatars/%d.png" % idx


def register_chat_party(app, db_path=None):
    db_file = db_path or _db_path()

    heartbeats = {}      # hwid-or-discord key -> { last_seen, identity }
    identity_cache = {}  # key -> { at, identity }
    global_messages = []
    next_global_id = [1]
    parties = {}         # code -> { code, created, next_id, messages, members: {key: last_seen} }
    member_party = {}    # key -> code
    send_dedup = {}      # key -> { text, ts, message }
    lock = threading.Lock()
    state_loaded = [False]
    chat_dirty = [False]
    last_chat_push = [0.0]

    def _chat_db():
        conn = sqlite3.connect(db_file, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _ensure_chat_tables():
        try:
            conn = _chat_db()
            conn.execute("CREATE TABLE IF NOT EXISTS chat_global(id INTEGER PRIMARY KEY, name TEXT, handle TEXT, role TEXT, text TEXT, ts INTEGER)")
            conn.execute("CREATE TABLE IF NOT EXISTS chat_party(code TEXT, id INTEGER, name TEXT, handle TEXT, role TEXT, text TEXT, ts INTEGER, PRIMARY KEY (code, id))")
            conn.execute("CREATE TABLE IF NOT EXISTS chat_party_members(code TEXT, hwid TEXT, last_seen REAL, PRIMARY KEY (code, hwid))")
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _load_chat_state():
        # lazy: runs on first request, i.e. AFTER init_db's gist restore
        _ensure_chat_tables()
        try:
            conn = _chat_db()
            for mid, name, handle, role, text, ts in conn.execute(
                    "SELECT id, name, handle, role, text, ts FROM chat_global ORDER BY id"):
                global_messages.append({"id": mid, "name": name, "handle": handle,
                                        "role": role or "", "text": text, "ts": ts})
            if global_messages:
                next_global_id[0] = max(m["id"] for m in global_messages) + 1
            for code, in conn.execute("SELECT DISTINCT code FROM chat_party"):
                parties[code] = {"code": code, "created": time.time(), "next_id": 1,
                                 "messages": [], "members": {}}
            for code, mid, name, handle, role, text, ts in conn.execute(
                    "SELECT code, id, name, handle, role, text, ts FROM chat_party ORDER BY code, id"):
                party = parties.get(code)
                if party is None:
                    continue
                party["messages"].append({"id": mid, "name": name, "handle": handle,
                                         "role": role or "", "text": text, "ts": ts})
                if mid >= party["next_id"]:
                    party["next_id"] = mid + 1
            for code, hwid, last_seen in conn.execute(
                    "SELECT code, hwid, last_seen FROM chat_party_members"):
                party = parties.get(code)
                if party is None:
                    continue
                party["members"][hwid] = last_seen
                member_party[hwid] = code
            conn.close()
        except Exception:
            pass

    def _ensure_chat_ready():
        if not state_loaded[0]:
            state_loaded[0] = True
            _load_chat_state()

    def _mark_chat_dirty():
        chat_dirty[0] = True

    def _save_global_msg(msg):
        try:
            conn = _chat_db()
            conn.execute("INSERT OR REPLACE INTO chat_global(id,name,handle,role,text,ts) VALUES (?,?,?,?,?,?)",
                         (msg["id"], msg["name"], msg["handle"], msg.get("role", ""),
                          msg["text"], msg["ts"]))
            conn.execute("DELETE FROM chat_global WHERE id <= (SELECT MAX(id)-100 FROM chat_global)")
            conn.commit()
            conn.close()
            _mark_chat_dirty()
        except Exception:
            pass

    def _save_party_msg(code, msg):
        try:
            conn = _chat_db()
            conn.execute("INSERT OR REPLACE INTO chat_party(code,id,name,handle,role,text,ts) VALUES (?,?,?,?,?,?,?)",
                         (code, msg["id"], msg["name"], msg["handle"], msg.get("role", ""),
                          msg["text"], msg["ts"]))
            conn.execute("DELETE FROM chat_party WHERE code = ? AND id <= (SELECT MAX(id)-100 FROM chat_party WHERE code = ?)",
                         (code, code))
            conn.commit()
            conn.close()
            _mark_chat_dirty()
        except Exception:
            pass

    def _save_party_members(code):
        try:
            party = parties.get(code)
            conn = _chat_db()
            if party is None:
                conn.execute("DELETE FROM chat_party_members WHERE code = ?", (code,))
                conn.execute("DELETE FROM chat_party WHERE code = ?", (code,))
            else:
                for hwid, ts in list(party["members"].items()):
                    conn.execute("INSERT OR REPLACE INTO chat_party_members(code,hwid,last_seen) VALUES (?,?,?)",
                                 (code, hwid, ts))
                if party["members"]:
                    placeholders = ",".join("?" for _ in party["members"])
                    conn.execute("DELETE FROM chat_party_members WHERE code = ? AND hwid NOT IN (%s)" % placeholders,
                                 tuple([code] + list(party["members"].keys())))
                else:
                    conn.execute("DELETE FROM chat_party_members WHERE code = ?", (code,))
                    conn.execute("DELETE FROM chat_party WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            _mark_chat_dirty()
        except Exception:
            pass

    def _log_embed(title, color, fields):
        _discord_post_channel(CHAT_LOG_CHANNEL_ID, {
            "embeds": [{
                "title": title,
                "color": color,
                "fields": [{"name": n, "value": v, "inline": False} for n, v in fields],
                "footer": {"text": "RAYX"},
                "timestamp": datetime.utcnow().isoformat(),
            }],
        })

    def _user_field(ident):
        mention = "<@%s>" % ident["discord_id"] if ident.get("discord_id") else None
        who = "%s (%s)%s" % (ident["name"], ident["handle"], (" [%s]" % ident["role"]) if ident.get("role") else "")
        return ("%s\n> %s" % (mention, who)) if mention else ("> %s" % who)

    def _key_field(license_key):
        return "||%s||" % license_key if license_key else "Unknown (no linked license)"

    def _time_field(ts_ms):
        return "<t:%d:F>" % int((ts_ms or int(time.time() * 1000)) / 1000)

    def _lookup_row(discord_id=None, hwid=None, license_key=None):
        try:
            conn = sqlite3.connect(db_file, timeout=10)
            conn.execute("PRAGMA busy_timeout = 10000")
            row = None
            if license_key:
                row = conn.execute(
                    "SELECT key, hwid, discord_id, expires_at, duration_type FROM keys WHERE key = ?",
                    (license_key,),
                ).fetchone()
            if row is None and discord_id:
                row = conn.execute(
                    "SELECT key, hwid, discord_id, expires_at, duration_type FROM keys "
                    "WHERE discord_id = ? ORDER BY expires_at DESC LIMIT 1",
                    (discord_id,),
                ).fetchone()
            if row is None and hwid:
                row = conn.execute(
                    "SELECT key, hwid, discord_id, expires_at, duration_type FROM keys "
                    "WHERE hwid = ? ORDER BY expires_at DESC LIMIT 1",
                    (hwid,),
                ).fetchone()
            conn.close()
            return row
        except Exception:
            return None

    def _resolve_identity(hwid, discord_id, license_key, display_name):
        key = discord_id or hwid or license_key or ""
        now = time.time()
        cached = identity_cache.get(key)
        if cached and now - cached["at"] < IDENTITY_CACHE_TTL:
            return cached["identity"]
        ident = {"name": "Unknown", "handle": "@unknown", "role": "",
                 "plan": "", "discord_id": None, "license_key": None,
                 "avatar": "", "expires_text": ""}
        try:
            row = _lookup_row(discord_id or None, hwid or None, license_key or None)
            if row:
                lic, stored_hwid, stored_discord, expires_at, duration_type = row
                ok = True
                if discord_id and stored_discord and str(discord_id) != str(stored_discord):
                    ok = False
                if hwid and stored_hwid and str(hwid) != str(stored_hwid):
                    ok = False
                if _is_expired(expires_at):
                    ok = False
                if ok:
                    did = str(stored_discord or discord_id or "")
                    user = _discord_get("/users/%s" % did) if did else None
                    username = (user or {}).get("username", "Unknown")
                    display = (user or {}).get("global_name") or username
                    if display_name:
                        display = str(display_name)[:32]
                    role = _resolve_role(did, username, display)
                    ident = {
                        "name": display or username,
                        "handle": "@" + str(username or "unknown").lower(),
                        "role": role,
                        "plan": str(duration_type or "lifetime").lower(),
                        "discord_id": did or None,
                        "license_key": lic,
                        "avatar": _avatar_url(did, (user or {}).get("avatar", ""), (user or {}).get("discriminator")),
                        "expires_text": _expires_text(expires_at),
                    }
        except Exception:
            pass
        identity_cache[key] = {"at": now, "identity": ident}
        return ident

    def _touch(hwid, discord_id, license_key, display_name):
        ident = _resolve_identity(hwid, discord_id, license_key, display_name)
        key = discord_id or hwid or license_key or ""
        with lock:
            if ident.get("discord_id"):
                heartbeats[key] = {"last_seen": time.time(), "identity": ident}
            else:
                heartbeats.pop(key, None)
        return ident

    def _online_users():
        with lock:
            items = [(k, dict(v)) for k, v in heartbeats.items()]
        now = time.time()
        seen = {}
        for key, hb in items:
            if now - hb["last_seen"] > HEARTBEAT_TTL:
                continue
            ident = hb["identity"]
            ukey = ("discord:" + str(ident["discord_id"])) if ident.get("discord_id") else ("key:" + str(key))
            if ukey in seen:
                continue
            seen[ukey] = {"name": ident["name"], "handle": ident["handle"],
                          "role": ident["role"], "online": True, "avatar": ident.get("avatar", "")}
        users = list(seen.values())
        users.sort(key=lambda u: (_role_rank(u["role"]), str(u["name"]).lower()))
        return users

    def _party_members(party):
        now = time.time()
        with lock:
            members = list(party["members"].items())
        out = []
        for key in [k for k, _ in members]:
            with lock:
                hb = heartbeats.get(key)
            if hb and now - hb["last_seen"] <= HEARTBEAT_TTL:
                ident = hb["identity"]
                online = True
            else:
                ident = (identity_cache.get(key) or {}).get("identity") or \
                    {"name": "Unknown", "handle": "@unknown", "role": ""}
                online = False
            out.append({"name": ident["name"], "handle": ident["handle"],
                        "role": ident["role"], "online": online})
        out.sort(key=lambda u: (_role_rank(u["role"]), str(u["name"]).lower()))
        return out

    def _leave_party(key, log_it=False):
        with lock:
            code = member_party.get(key)
            party = parties.get(code) if code else None
            if party and key in party["members"]:
                del party["members"][key]
                if not party["members"]:
                    parties.pop(code, None)
            member_party.pop(key, None)
        if code:
            _save_party_members(code)
        if log_it and code:
            ident = (identity_cache.get(key) or {}).get("identity") or \
                {"name": "Unknown", "handle": "@unknown", "role": "",
                 "discord_id": None, "license_key": None}
            _log_embed("⬅️ Party Leave", 0xE67E22, [
                ("User", _user_field(ident)),
                ("License Key", _key_field(ident.get("license_key"))),
                ("Party Code", "> `%s`" % code),
                ("Time", "> %s" % _time_field(None)),
            ])

    def _prune_loop():
        while True:
            time.sleep(30)
            try:
                now = time.time()
                dead_codes = []
                with lock:
                    for k in [k for k, hb in heartbeats.items() if now - hb["last_seen"] > HEARTBEAT_TTL]:
                        heartbeats.pop(k, None)
                    for code in list(parties.keys()):
                        party = parties.get(code)
                        if not party:
                            continue
                        for k in [k for k, ts in party["members"].items() if now - ts > PARTY_MEMBER_TTL]:
                            party["members"].pop(k, None)
                            if member_party.get(k) == code:
                                member_party.pop(k, None)
                        if not party["members"]:
                            parties.pop(code, None)
                            dead_codes.append(code)
                for code in dead_codes:
                    _save_party_members(code)
                # persist chat history to gist (survives restarts) - at most every 3 min
                if chat_dirty[0] and now - last_chat_push[0] > 180:
                    try:
                        import __main__ as _mainmod
                        push = getattr(_mainmod, "sync_db_to_gist", None)
                        if callable(push):
                            push()
                            last_chat_push[0] = now
                            chat_dirty[0] = False
                    except Exception:
                        pass
            except Exception:
                pass

    threading.Thread(target=_prune_loop, daemon=True).start()

    def _req_identity(data):
        hwid = str(data.get("hwid") or "").strip()
        discord_id = str(data.get("discord_id") or data.get("username") or "").strip()
        if discord_id and not discord_id.isdigit():
            discord_id = ""
        license_key = str(data.get("license") or data.get("key") or data.get("password") or "").strip()
        display_name = str(data.get("display_name") or "").strip()[:32]
        return hwid, discord_id, license_key, display_name

    @app.route("/api/client/presence", methods=["POST", "OPTIONS"])
    def chat_presence():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        _ensure_chat_ready()
        try:
            ident = _touch(hwid, discord_id, license_key, display_name)
            users = _online_users()
            return jsonify({"ok": True, "server_time": int(time.time() * 1000),
                            "self": ident, "users": users})
        except Exception as e:
            print("[CHAT] presence error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    @app.route("/api/client/chat/send", methods=["POST", "OPTIONS"])
    def chat_send():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        clean = _clean_text(data.get("text"))
        if not clean:
            return jsonify({"ok": False, "error": "empty_text"}), 400
        _ensure_chat_ready()
        try:
            ident = _touch(hwid, discord_id, license_key, display_name)
            if not ident.get("discord_id"):
                return jsonify({"ok": False, "error": "unknown_user"}), 403
            key = discord_id or hwid or license_key
            ts = int(time.time() * 1000)
            is_party = (data.get("scope") == "party")
            with lock:
                scope_code = str(data.get("party_code") or member_party.get(key) or "")
            dedup_key = "%s|%s" % (key, ("party:" + scope_code) if is_party else "global")
            with lock:
                prev = send_dedup.get(dedup_key)
            if prev and prev["text"] == clean and ts - prev["ts"] < SEND_DEDUP_MS:
                return jsonify({"ok": True, "message": prev["message"], "duplicate": True})
            if is_party:
                with lock:
                    party = parties.get(scope_code)
                    member = party and key in party["members"]
                if not party or not member:
                    return jsonify({"ok": False, "error": "not_in_party"}), 403
                with lock:
                    party["members"][key] = time.time()
                    msg = {"id": party["next_id"], "name": ident["name"], "handle": ident["handle"],
                           "role": ident["role"], "text": clean, "ts": ts}
                    party["next_id"] += 1
                    party["messages"].append(msg)
                    while len(party["messages"]) > MAX_MESSAGES:
                        party["messages"].pop(0)
                    send_dedup[dedup_key] = {"text": clean, "ts": ts, "message": msg}
                _save_party_msg(scope_code, msg)
                _log_embed("💬 Party Chat Message", 0x3498DB, [
                    ("User", _user_field(ident)),
                    ("License Key", _key_field(ident.get("license_key"))),
                    ("Party Code", "> `%s`" % scope_code),
                    ("Message", "> %s" % clean[:1000]),
                    ("Time", "> %s" % _time_field(ts)),
                ])
                return jsonify({"ok": True, "message": msg})
            with lock:
                msg = {"id": next_global_id[0], "name": ident["name"], "handle": ident["handle"],
                       "role": ident["role"], "text": clean, "ts": ts}
                next_global_id[0] += 1
                global_messages.append(msg)
                while len(global_messages) > MAX_MESSAGES:
                    global_messages.pop(0)
                send_dedup[dedup_key] = {"text": clean, "ts": ts, "message": msg}
            _save_global_msg(msg)
            _log_embed("💬 Global Chat Message", 0x2ECC71, [
                ("User", _user_field(ident)),
                ("License Key", _key_field(ident.get("license_key"))),
                ("Message", "> %s" % clean[:1000]),
                ("Time", "> %s" % _time_field(ts)),
            ])
            return jsonify({"ok": True, "message": msg})
        except Exception as e:
            print("[CHAT] send error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    @app.route("/api/client/chat/poll", methods=["POST", "OPTIONS"])
    def chat_poll():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        _ensure_chat_ready()
        try:
            _touch(hwid, discord_id, license_key, display_name)
            key = discord_id or hwid or license_key
            since = int(data.get("since_id") or 0)
            if data.get("scope") == "party":
                with lock:
                    code = str(data.get("party_code") or member_party.get(key) or "")
                    party = parties.get(code)
                    member = party and key in party["members"]
                    if member:
                        party["members"][key] = time.time()
                        msgs = [m for m in party["messages"] if m["id"] > since]
                    else:
                        msgs = []
                        party = None
                if not party:
                    return jsonify({"ok": True, "messages": [], "party": None})
                return jsonify({"ok": True, "messages": msgs,
                                "party": {"code": code, "members": _party_members(party)}})
            with lock:
                msgs = [m for m in global_messages if m["id"] > since]
            return jsonify({"ok": True, "messages": msgs, "party": None})
        except Exception as e:
            print("[CHAT] poll error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    def _make_code():
        with lock:
            for _ in range(50):
                code = str(random.randint(1000, 9999))
                if code not in parties:
                    return code
            return str(random.randint(1000, 9999))

    @app.route("/api/client/party/create", methods=["POST", "OPTIONS"])
    def party_create():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        _ensure_chat_ready()
        try:
            ident = _touch(hwid, discord_id, license_key, display_name)
            if not ident.get("discord_id"):
                return jsonify({"ok": False, "error": "unknown_user"}), 403
            key = discord_id or hwid or license_key
            now = time.time()
            with lock:
                existing_code = member_party.get(key)
                existing = parties.get(existing_code) if existing_code else None
                if existing and now - existing["created"] < (CREATE_DEDUP_MS / 1000.0):
                    code = existing_code
                    members = list(existing["members"].keys())
                    dup = True
                else:
                    dup = False
                    code = None
            if dup:
                return jsonify({"ok": True, "code": code,
                                "members": _party_members(existing), "duplicate": True})
            _leave_party(key)
            code = _make_code()
            with lock:
                parties[code] = {"code": code, "created": now, "next_id": 1,
                                 "messages": [], "members": {key: now}}
                member_party[key] = code
                party = parties[code]
            _save_party_members(code)
            _log_embed("🎉 Party Created", 0x9B59B6, [
                ("User", _user_field(ident)),
                ("License Key", _key_field(ident.get("license_key"))),
                ("Party Code", "> `%s`" % code),
                ("Time", "> %s" % _time_field(None)),
            ])
            return jsonify({"ok": True, "code": code, "members": _party_members(party)})
        except Exception as e:
            print("[CHAT] party/create error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    @app.route("/api/client/party/join", methods=["POST", "OPTIONS"])
    def party_join():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        _ensure_chat_ready()
        clean_code = "".join(c for c in str(data.get("code") or "") if c.isdigit())[:4]
        with lock:
            party = parties.get(clean_code)
        if not party:
            return jsonify({"ok": False, "error": "invalid_code"}), 404
        try:
            ident = _touch(hwid, discord_id, license_key, display_name)
            if not ident.get("discord_id"):
                return jsonify({"ok": False, "error": "unknown_user"}), 403
            key = discord_id or hwid or license_key
            with lock:
                old_code = member_party.get(key)
            _leave_party(key)
            if old_code:
                _save_party_members(old_code)
            with lock:
                party["members"][key] = time.time()
                member_party[key] = clean_code
            _save_party_members(clean_code)
            _log_embed("➡️ Party Join", 0x2ECC71, [
                ("User", _user_field(ident)),
                ("License Key", _key_field(ident.get("license_key"))),
                ("Party Code", "> `%s`" % clean_code),
                ("Time", "> %s" % _time_field(None)),
            ])
            return jsonify({"ok": True, "code": clean_code, "members": _party_members(party)})
        except Exception as e:
            print("[CHAT] party/join error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    @app.route("/api/client/party/leave", methods=["POST", "OPTIONS"])
    def party_leave():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(silent=True) or {}
        hwid, discord_id, license_key, display_name = _req_identity(data)
        if not (hwid or discord_id or license_key):
            return jsonify({"ok": False, "error": "missing_identity"}), 400
        _ensure_chat_ready()
        try:
            _touch(hwid, discord_id, license_key, display_name)
            _leave_party(discord_id or hwid or license_key, log_it=True)
            return jsonify({"ok": True})
        except Exception as e:
            print("[CHAT] party/leave error: %s" % e)
            return jsonify({"ok": False, "error": "internal"}), 500

    print("Chat + Party API mounted (/api/client/presence, /api/client/chat/*, /api/client/party/*)")
