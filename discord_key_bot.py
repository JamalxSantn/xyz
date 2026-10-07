import discord
from discord.ext import commands
import uuid
from datetime import datetime, timedelta
import json
import os
import sys
import subprocess
import asyncio
import threading
import tempfile
import urllib.request
import base64
import sqlite3
from flask import Flask, jsonify, request, render_template


# Konsole sofort schreiben (Render puffert sonst print()-Ausgaben -> Fehler sind unsichtbar)
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Windows: "Markieren"-Modus (QuickEdit) in der Konsole ausschalten.
# Sonst friert der KOMPLETTE Bot ein, sobald man ins schwarze Fenster klickt
# (print() blockiert) -> keine Logs, keine Updates mehr, bis man Enter drückt.
if os.name == "nt":
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32
        _h = _k32.GetStdHandle(-10)            # STD_INPUT_HANDLE
        _mode = ctypes.c_uint32()
        if _k32.GetConsoleMode(_h, ctypes.byref(_mode)):
            # QuickEdit (0x40) aus, Extended Flags (0x80) an
            _k32.SetConsoleMode(_h, (_mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  RAYX Bot – Config
# ══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members = True          # NEU: für Join/Leave/Nickname/Timeout-Logs (Server Members Intent im Dev-Portal aktivieren!)
intents.guilds = True           # NEU: Rollen-/Channel-Events
intents.moderation = True       # NEU: Ban/Unban-Events
bot = commands.Bot(command_prefix="!", intents=intents)

# — Channel IDs —
PURGE_CHANNEL_ID       = 1537561862361849989
WHITELIST_CHANNEL_ID   = 1538336311365214218
LOG_CHANNEL_ID         = 1553042285762056294
BOT_LOG_CHANNEL_ID     = 1538307572908556442
LOADER_LOG_CHANNEL_ID  = 1553042285762056294
KEY_LOG_CHANNEL_ID     = 1539797066924957809
INJECT_LOG_CHANNEL_ID  = 1553042236034519079
USER_CHECK_CHANNEL_ID  = 1539925997766578267
KEYS_OVERVIEW_CHANNEL_ID = 1543799035327156284
BOT_STATUS_CHANNEL_ID  = 1539243946373550111
CHECK_CHANNEL_ID       = 1553042285762056294

# — General —
BOT_START_TIME = datetime.now()
GUILD_ID   = 1537561860163768412
MASTER_ID  = "1027571297514967140"

# — Ticket System —
TICKET_GUILD_ID      = 1472228342118879370
TICKET_CHANNEL_ID    = 1472321913828147421
TICKET_LOG_CHANNEL_ID = 1487068508935426238
ADVANCED_CATEGORY_ID = 1472321807603335208
SUPPORT_CATEGORY_ID  = 1487794310022959205
CLOSED_CATEGORY_ID   = 1472321805174706238
TICKET_STAFF_ROLE_ID = 1472321748358660259

# — Branding —
BRAND_COLOR   = 0x000000
ACCENT_GREEN  = 0x00ff00
ACCENT_RED    = 0xff0000
ACCENT_BLUE   = 0x3498db
ACCENT_YELLOW = 0xf39c12
LOGO_URL      = "https://cdn.discordapp.com/attachments/1538307572908556442/1543804149487902750/n69nxdk.png?ex=6a963327&is=6a94e1a7&hm=3b23036d46b75e2a0ab04cdd5ccae65917ebe088bf96cf9dfadd463ba04d5ef5&"
BYPASS_LOGO   = "https://cdn.discordapp.com/attachments/1475174657488322582/1492708596839088180/bypass_logo.png"
TICKET_LOGO_URL = BYPASS_LOGO
BANNER_URL    = "https://cdn.discordapp.com/attachments/1542513641646202982/1543835735784816783/3vjf40w.png?ex=6a965092&is=6a94ff12&hm=fb85743a7fd072a4142b288b55e5cf06584a44fc7d4e2b5e0cab8bf3fe98352f&"
FOOTER_TEXT   = "F I STEINKE C++ MEISTER"

# — Loader / Cheat —
LOAD_URL  = os.environ.get("LOAD_URL", "http://192.168.178.72:5000")
CHEAT_EXE = os.environ.get("CHEAT_EXE", "")

# — Gist / Database —
GIST_ID        = os.environ.get("GIST_ID", "1d00ee128d1f4d294ec95e3e160ec195")
GIST_TOKEN     = os.environ.get("GIST_TOKEN", "")
DATABASE       = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.db"))
CLOUD_DATABASE = os.environ.get("CLOUD_DATABASE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud.db"))
CLOUD_TABLES   = ("cloud_users", "cloud_friendships", "cloud_configs", "cloud_shares")

# — Ticket Runtime —
ticket_channels = {}
ticket_messages = {}
TICKET_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticket_data.json")


# ══════════════════════════════════════════════════════════════
#  Embed Helpers  –  einheitliches Design für alle Embeds
# ══════════════════════════════════════════════════════════════

def make_embed(title, description=None, *, color=BRAND_COLOR, thumbnail=True, footer=True):
    """Erstellt ein Embed im einheitlichen RAYX-Design."""
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now())
    if thumbnail:
        embed.set_thumbnail(url=LOGO_URL)
    if footer:
        embed.set_footer(text=FOOTER_TEXT)
    return embed


def success_embed(title, description=None):
    return make_embed(f"✅  {title}", description, color=ACCENT_GREEN, thumbnail=False)


def error_embed(title, description=None):
    return make_embed(f"❌  {title}", description, color=ACCENT_RED, thumbnail=False)


def info_embed(title, description=None):
    return make_embed(title, description, color=ACCENT_BLUE, thumbnail=False)


# ══════════════════════════════════════════════════════════════
#  Logging Helpers  –  saubere Log-Embeds
# ══════════════════════════════════════════════════════════════

async def send_log(action, user, details, color=ACCENT_BLUE):
    """Sendet ein Log-Embed in den Log-Channel."""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(title=action, color=color, timestamp=datetime.now())
        embed.add_field(name="User", value=f"{user.mention}  (`{user.id}`)", inline=True)
        embed.add_field(name="Details", value=details, inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG] Fehler: {e}")


async def send_bot_log(action, details, color=BRAND_COLOR):
    """Sendet ein Bot-System-Log."""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(BOT_LOG_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(title=action, color=color, timestamp=datetime.now())
        embed.add_field(name="Details", value=details, inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[BOT-LOG] Fehler: {e}")


def send_key_log_sync(action, details, color=ACCENT_GREEN):
    """Synchrones Key-Log an den Key-Log-Channel (Flask-Kontext)."""
    try:
        token = os.environ.get("DISCORD_TOKEN", "")

        lines = []
        for raw in details.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if ":" in line:
                label, value = line.split(":", 1)
                value = value.strip()
                if label.strip() == "Key":
                    inner = value.strip("`")
                    value = f"||{inner}||"
                lines.append(f"> **{label.strip()}:** {value}")
            else:
                lines.append(f"> {line}")

        body = json.dumps({
            "embeds": [{
                "title": action,
                "description": "\n".join(lines),
                "color": color,
                "footer": {"text": FOOTER_TEXT},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }).encode()
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{KEY_LOG_CHANNEL_ID}/messages",
            data=body,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "RayXBot/1.0"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[KEY-LOG] Fehler: {e}")


def send_inject_log_sync(discord_id, key):
    """Synchrones Inject-Log in den Inject-Log-Channel (Flask-Kontext)."""
    try:
        token = os.environ.get("DISCORD_TOKEN", "")
        user_str = f"<@{discord_id}>" if discord_id and discord_id.isdigit() else (discord_id or "N/A")
        lines = "\n".join([
            f"> **User:** {user_str}",
            f"> **Key:** ||{key}||",
            f"> **Zeit:** <t:{int(datetime.utcnow().timestamp())}:F>",
        ])
        body = json.dumps({
            "embeds": [{
                "title": "💉 Inject erfolgreich",
                "description": lines,
                "color": ACCENT_GREEN,
                "thumbnail": {"url": LOGO_URL},
                "footer": {"text": FOOTER_TEXT},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }).encode()
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{INJECT_LOG_CHANNEL_ID}/messages",
            data=body,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "RayXBot/1.0"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[INJECT-LOG] Fehler: {e}")


async def send_ticket_log(message):
    """Log für das Ticket-System."""
    try:
        guild = bot.get_guild(TICKET_GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(description=message, color=BRAND_COLOR, timestamp=datetime.now())
        embed.set_footer(text=f"{FOOTER_TEXT} Logs")
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[TICKET-LOG] Fehler: {e}")


# ══════════════════════════════════════════════════════════════
#  Ticket Data Persistence
# ══════════════════════════════════════════════════════════════

def load_ticket_data():
    global ticket_channels
    try:
        if os.path.exists(TICKET_DATA_FILE):
            with open(TICKET_DATA_FILE, "r") as f:
                data = json.load(f)
            for k, v in data.items():
                ticket_channels[int(k)] = v
            print(f"[TICKETS] {len(ticket_channels)} Tickets geladen")
    except Exception as e:
        print(f"[TICKETS] Laden fehlgeschlagen: {e}")


def save_ticket_data():
    try:
        data = {str(k): v for k, v in ticket_channels.items()}
        with open(TICKET_DATA_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[TICKETS] Speichern fehlgeschlagen: {e}")


# ══════════════════════════════════════════════════════════════
#  Database  –  Keys & Cloud
# ══════════════════════════════════════════════════════════════

def gist_database_payload():
    temp_path = None
    source = target = filtered = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name
        source = sqlite3.connect(DATABASE, timeout=10)
        target = sqlite3.connect(temp_path, timeout=10)
        source.backup(target)
        target.close(); target = None
        source.close(); source = None
        filtered = sqlite3.connect(temp_path, timeout=10)
        for table in CLOUD_TABLES:
            filtered.execute(f"DROP TABLE IF EXISTS {table}")
        filtered.commit()
        filtered.close(); filtered = None
        with open(temp_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    finally:
        for conn in (filtered, target, source):
            if conn:
                conn.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def sync_db_from_gist():
    if not GIST_ID or not GIST_TOKEN:
        print("[DB] Gist-Sync deaktiviert (keine Credentials)")
        return
    try:
        req = urllib.request.Request(f"https://api.github.com/gists/{GIST_ID}")
        req.add_header("Authorization", f"token {GIST_TOKEN}")
        req.add_header("User-Agent", "RayXBot")
        resp = urllib.request.urlopen(req, timeout=10)
        gist = json.loads(resp.read().decode())
        content = gist["files"]["bot_data.json"]["content"].strip()
        if content:
            with open(DATABASE, "wb") as f:
                f.write(base64.b64decode(content))
            print("[DB] Von Gist geladen")
        else:
            print("[DB] Gist leer – starte mit frischer DB")
    except Exception as e:
        print(f"[DB] Gist-Download fehlgeschlagen: {e}")


_gist_lock = threading.Lock()
_gist_pending = threading.Event()


def sync_db_to_gist():
    """Startet den Gist-Upload im Hintergrund (blockiert den Bot nicht mehr).
    Mehrere Aufrufe kurz hintereinander werden zu einem Upload zusammengefasst."""
    if not GIST_ID or not GIST_TOKEN:
        return
    _gist_pending.set()
    if _gist_lock.locked():
        return

    def _worker():
        with _gist_lock:
            while _gist_pending.is_set():
                _gist_pending.clear()
                _sync_db_to_gist_blocking()

    threading.Thread(target=_worker, daemon=True).start()


def _sync_db_to_gist_blocking():
    try:
        encoded = gist_database_payload()
        body = json.dumps({"files": {"bot_data.json": {"content": encoded}}}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            data=body,
            headers={
                "Authorization": f"token {GIST_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "RayXBot"
            },
            method="PATCH"
        )
        urllib.request.urlopen(req, timeout=10)
        print("[DB] Zu Gist gesynct")
    except Exception as e:
        print(f"[DB] Gist-Upload fehlgeschlagen: {e}")


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DATABASE)), exist_ok=True)
    sync_db_from_gist()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY, hwid TEXT, discord_id TEXT,
        created_at TEXT, expires_at TEXT, duration_type TEXT,
        duration_value INTEGER, used INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS whitelist (
        discord_id TEXT PRIMARY KEY, added_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        discord_id TEXT PRIMARY KEY, added_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS key_meta (
        key TEXT PRIMARY KEY, created_by TEXT,
        login_count INTEGER DEFAULT 0, last_login TEXT
    )""")
    c.execute("SELECT name FROM pragma_table_info('key_meta') WHERE name = 'frozen_at'")
    if not c.fetchone():
        c.execute("ALTER TABLE key_meta ADD COLUMN frozen_at TEXT")
    now = datetime.now().isoformat()
    c.execute("SELECT COUNT(*) FROM whitelist")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO whitelist (discord_id, added_at) VALUES (?, ?)", (MASTER_ID, now))
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (discord_id, added_at) VALUES (?, ?)", (MASTER_ID, now))
    conn.commit()
    conn.close()
    sync_db_to_gist()


def init_cloud_db():
    os.makedirs(os.path.dirname(os.path.abspath(CLOUD_DATABASE)), exist_ok=True)
    conn = sqlite3.connect(CLOUD_DATABASE, timeout=10)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS cloud_users (
        discord_id TEXT PRIMARY KEY, display_name TEXT, last_seen TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cloud_friendships (
        owner_id TEXT NOT NULL, friend_id TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (owner_id, friend_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cloud_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id TEXT NOT NULL, code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL, config TEXT NOT NULL,
        created_at TEXT NOT NULL, use_count INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cloud_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
        name TEXT NOT NULL, config TEXT NOT NULL,
        created_at TEXT NOT NULL, claimed_at TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cf_friend ON cloud_friendships(friend_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cc_owner ON cloud_configs(owner_id, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cs_recip ON cloud_shares(recipient_id, claimed_at)")
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════
#  Utility Functions
# ══════════════════════════════════════════════════════════════

def is_master(discord_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM masters WHERE discord_id = ?", (str(discord_id),))
    result = c.fetchone()
    conn.close()
    return result is not None


def is_whitelisted(discord_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM whitelist WHERE discord_id = ?", (str(discord_id),))
    result = c.fetchone()
    conn.close()
    return result is not None


def get_expiry(duration_type, duration_value, created_at=None):
    if created_at is None:
        created_at = datetime.now()
    elif isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    durations = {
        "minute": timedelta(minutes=duration_value),
        "hour":   timedelta(hours=duration_value),
        "day":    timedelta(days=duration_value),
        "week":   timedelta(weeks=duration_value),
        "month":  timedelta(days=duration_value * 30),
        "year":   timedelta(days=duration_value * 365),
    }
    return (created_at + durations.get(duration_type, timedelta(days=duration_value))).isoformat()


def time_remaining(expires_at):
    remaining = datetime.fromisoformat(expires_at) - datetime.now()
    if remaining.total_seconds() <= 0:
        return "Abgelaufen"
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes = remainder // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "< 1m"


def format_uptime(start_time):
    seconds = int((datetime.now() - start_time).total_seconds())
    d, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    return f"{d}d {h}h {m}m {s}s"


def format_date(iso_str):
    """Formatiert ein ISO-Datum leserlich."""
    try:
        return datetime.fromisoformat(iso_str).strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        return iso_str or "—"


def get_frozen_at(key):
    """Liest frozen_at aus key_meta (None wenn nicht eingefroren)."""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT frozen_at FROM key_meta WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception as e:
        print(f"[FREEZE] Read-Fehler: {e}")
        return None


def is_frozen(key):
    """True wenn der Key aktuell eingefroren ist."""
    frozen = get_frozen_at(key)
    return bool(frozen) and frozen not in ("", "0")


def effective_expiry(expires_at, frozen_at=None):
    """Effektives Ablaufdatum: laufende Zeit minus eingefrorene Zeit."""
    base = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else expires_at
    if frozen_at:
        frozen = datetime.fromisoformat(frozen_at) if isinstance(frozen_at, str) else frozen_at
        base = base + (datetime.now() - frozen)
    return base


def time_remaining_effective(expires_at, frozen_at=None):
    """time_remaining unter Berücksichtigung von eingefrorener Zeit."""
    return time_remaining(effective_expiry(expires_at, frozen_at).isoformat())


def freeze_key(key):
    """Friert einen Key ein (Ablaufzeit pausiert)."""
    if is_frozen(key):
        return False, "schon eingefroren"
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
    if not c.fetchone():
        conn.close()
        return False, "nicht gefunden"
    c.execute("INSERT OR IGNORE INTO key_meta (key) VALUES (?)", (key,))
    c.execute("UPDATE key_meta SET frozen_at = ? WHERE key = ?", (datetime.now().isoformat(), key))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    return True, None


def unfreeze_key(key):
    """Taucht einen Key auf und schreibt die eingefrorene Zeit ans Expiry gut."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "nicht gefunden"
    frozen = get_frozen_at(key)
    if not frozen:
        conn.close()
        return False, "nicht eingefroren"
    expires_dt = datetime.fromisoformat(row[0])
    frozen_dt = datetime.fromisoformat(frozen)
    added = datetime.now() - frozen_dt
    expires_dt = expires_dt + added
    c.execute("UPDATE keys SET expires_at = ? WHERE key = ?", (expires_dt.isoformat(), key))
    c.execute("UPDATE key_meta SET frozen_at = NULL WHERE key = ?", (key,))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    return True, f"+{format_duration(added)} gutgeschrieben"


def format_duration(td):
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def check_api_status():
    try:
        import time
        start = time.time()
        req = urllib.request.Request("http://127.0.0.1:5000/", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        ms = int((time.time() - start) * 1000)
        return f"Online · {resp.status} · {ms}ms"
    except urllib.error.HTTPError as e:
        return f"Online · HTTP {e.code}"
    except Exception:
        return "Offline"


# ══════════════════════════════════════════════════════════════
#  Init
# ══════════════════════════════════════════════════════════════

init_db()
init_cloud_db()


# ══════════════════════════════════════════════════════════════
#  Flask API Server
# ══════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder='templates')
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024


@app.route('/')
def index():
    return render_template('index.html')


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/auth', methods=['POST', 'OPTIONS'])
def api_auth():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    hwid = data.get('hwid', '').strip()

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (password,))
    result = c.fetchone()

    if not result:
        conn.close()
        send_key_log_sync("Login fehlgeschlagen", f"Key: `{password}`\nHWID: `{hwid}`\nDiscord: `{username}`\nGrund: Ungültiger Key", ACCENT_RED)
        return jsonify({'success': False, 'error': 'Invalid key'}), 401

    _, stored_hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = result
    frozen_at = get_frozen_at(password)

    if datetime.now() > effective_expiry(expires_at, frozen_at):
        conn.close()
        send_key_log_sync("Login fehlgeschlagen", f"Key: `{password}`\nHWID: `{hwid}`\nDiscord: `{username}`\nGrund: Abgelaufen", ACCENT_RED)
        return jsonify({'success': False, 'error': 'Key expired'}), 403

    if used:
        if stored_hwid and stored_hwid != hwid:
            conn.close()
            send_key_log_sync("Login fehlgeschlagen", f"Key: `{password}`\nHWID: `{hwid}` (erwartet: `{stored_hwid}`)\nDiscord: `{username}`\nGrund: HWID Mismatch", ACCENT_RED)
            return jsonify({'success': False, 'error': 'HWID mismatch'}), 403
        send_key_log_sync("Login", f"Key: `{password}`\nHWID: `{hwid}`\nDiscord: `{username}`", ACCENT_BLUE)
    else:
        if username and username.isdigit():
            c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?", (hwid, username, password))
        else:
            c.execute("UPDATE keys SET used = 1, hwid = ? WHERE key = ?", (hwid, password))
        conn.commit()
        sync_db_to_gist()
        send_key_log_sync("Key eingelöst (Loader)", f"Key: `{password}`\nHWID: `{hwid}`\nDiscord: `{username}`", ACCENT_GREEN)

    c.execute("INSERT OR IGNORE INTO key_meta (key) VALUES (?)", (password,))
    c.execute("UPDATE key_meta SET login_count = login_count + 1, last_login = ? WHERE key = ?",
              (datetime.now().isoformat(), password))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'products': [{
            'id': 1, 'game': 'FiveM', 'version': duration_type,
            'status_id': 0, 'expiry': time_remaining_effective(expires_at, frozen_at)
        }]
    }), 200


@app.route('/api/inject-log', methods=['POST', 'OPTIONS'])
def api_inject_log():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    discord_id = (data.get('discord_id') or '').strip()
    key = (data.get('key') or '').strip()
    send_inject_log_sync(discord_id, key)
    return jsonify({'success': True}), 200


@app.route('/api/validate-subscription', methods=['POST', 'OPTIONS'])
def validate_subscription():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json()
    username = data.get('username', '').strip()

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE discord_id = ?", (username,))
    results = c.fetchall()
    conn.close()

    for (expires_at,) in results:
        if datetime.now() <= datetime.fromisoformat(expires_at):
            return jsonify({'success': True, 'valid': True}), 200
    return jsonify({'success': False, 'valid': False}), 403


@app.route('/api/verify', methods=['POST'])
def verify_key():
    data = request.get_json()
    key = data.get('key', '').strip()
    hwid = data.get('hwid', '')

    if not key:
        return jsonify({'success': False, 'error': 'No key provided'}), 400

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()

    if not result:
        return jsonify({'success': False, 'error': 'Key not found'}), 404

    _, stored_hwid, _, _, expires_at, _, _, used = result

    if datetime.now() > datetime.fromisoformat(expires_at):
        return jsonify({'success': False, 'error': 'Key expired'}), 403
    if used and stored_hwid and stored_hwid != hwid:
        return jsonify({'success': False, 'error': 'Key already used on different HWID'}), 403

    return jsonify({
        'success': True, 'key': key,
        'expires_at': expires_at,
        'time_remaining': time_remaining(expires_at)
    }), 200


@app.route('/api/user-info', methods=['POST', 'OPTIONS'])
def api_user_info():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json()
    discord_id = data.get('discord_id', '').strip()
    if not discord_id:
        return jsonify({'success': False, 'error': 'Missing discord_id'}), 400

    try:
        token = os.environ.get("DISCORD_TOKEN", "")
        if not token:
            return jsonify({'success': False, 'error': 'Bot token not configured'}), 500

        req = urllib.request.Request(f"https://discord.com/api/v10/users/{discord_id}")
        req.add_header("Authorization", f"Bot {token}")
        req.add_header("User-Agent", "RayXBot")
        resp = urllib.request.urlopen(req, timeout=5)
        user_data = json.loads(resp.read().decode())

        username = user_data.get("global_name") or user_data.get("username", "Unknown")
        avatar_hash = user_data.get("avatar", "")
        avatar_url = ""
        if avatar_hash:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}"

        return jsonify({'success': True, 'username': username, 'avatar_url': avatar_url})
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return jsonify({'success': False, 'error': 'Rate limited'}), 429
        return jsonify({'success': False, 'error': f'Discord API error {e.code}'}), 500
    except Exception as e:
        print(f"[API] user-info Fehler: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/register', methods=['POST'])
def register_hwid():
    data = request.get_json()
    key = data.get('key', '').strip()
    hwid = data.get('hwid', '')
    discord_id = data.get('discord_id', 'Unknown')

    if not key or not hwid:
        return jsonify({'success': False, 'error': 'Missing key or hwid'}), 400

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()

    if not result:
        conn.close()
        return jsonify({'success': False, 'error': 'Key not found'}), 404

    _, stored_hwid, _, _, expires_at, _, _, used = result

    if used:
        if stored_hwid and stored_hwid != hwid:
            conn.close()
            return jsonify({'success': False, 'error': 'Key already used on different HWID'}), 403
        conn.close()
        return jsonify({'success': True, 'message': 'Key already registered'}), 200

    if datetime.now() > datetime.fromisoformat(expires_at):
        conn.close()
        return jsonify({'success': False, 'error': 'Key expired'}), 403

    if discord_id and discord_id.isdigit():
        c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?", (hwid, discord_id, key))
    else:
        c.execute("UPDATE keys SET used = 1, hwid = ? WHERE key = ?", (hwid, key))
    conn.commit()
    sync_db_to_gist()
    conn.close()

    send_key_log_sync("Key eingelöst (Loader)", f"Key: `{key}`\nHWID: `{hwid}`\nDiscord: `{discord_id}`", ACCENT_GREEN)
    return jsonify({'success': True, 'message': 'Key registered successfully'}), 200


# ── Cloud API ────────────────────────────────────────────────

def cloud_db():
    conn = sqlite3.connect(CLOUD_DATABASE, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn

def cloud_value(value):
    return value.strip() if isinstance(value, str) else ""

def cloud_label(value, limit=64):
    value = cloud_value(value)
    return "".join(c for c in value if c.isprintable())[:limit].strip()

def cloud_code(value):
    return "".join(c for c in cloud_value(value).upper() if c.isalnum())[:32]

def cloud_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)

def cloud_expired(value):
    try:
        exp = datetime.fromisoformat(value)
        if exp.tzinfo:
            exp = exp.replace(tzinfo=None)
        return datetime.now() > exp
    except (TypeError, ValueError):
        return True

def cloud_online(value):
    if not value:
        return False
    try:
        last = datetime.fromisoformat(value)
        if last.tzinfo:
            last = last.replace(tzinfo=None)
        return (datetime.now() - last).total_seconds() < 300
    except (TypeError, ValueError):
        return False

def cloud_error(message, status=400):
    return jsonify({'success': False, 'error': message}), status

def cloud_auth(data):
    if not isinstance(data, dict):
        return None, cloud_error('Invalid request')
    discord_id = cloud_value(data.get('discord_id', data.get('username')))
    license_key = cloud_value(data.get('license', data.get('key', data.get('password'))))
    hwid = cloud_value(data.get('hwid'))
    if not discord_id.isdigit() or not 5 <= len(discord_id) <= 22:
        return None, cloud_error('Invalid Discord ID')
    if not license_key or not hwid:
        return None, cloud_error('Missing license or HWID')

    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    row = conn.execute('SELECT hwid, discord_id, expires_at, used FROM keys WHERE key = ?', (license_key,)).fetchone()
    conn.close()
    if not row:
        return None, cloud_error('Invalid license', 401)
    if not row[0] or not row[1] or not row[3]:
        return None, cloud_error('License is not bound to this session', 403)
    if cloud_expired(row[2]):
        return None, cloud_error('License expired', 403)
    if row[0] != hwid:
        return None, cloud_error('HWID mismatch', 403)
    if row[1] != discord_id:
        return None, cloud_error('Discord ID mismatch', 403)

    display_name = cloud_label(data.get('display_name'))
    now = datetime.now().isoformat()
    conn = cloud_db()
    conn.execute('INSERT OR IGNORE INTO cloud_users(discord_id, display_name, last_seen) VALUES (?, ?, ?)',
                 (discord_id, display_name, now))
    conn.execute('UPDATE cloud_users SET display_name = ?, last_seen = ? WHERE discord_id = ?',
                 (display_name, now, discord_id))
    conn.commit()
    conn.close()
    return {'id': discord_id, 'name': display_name}, None

def cloud_friend_entry(identifier, name, last_seen):
    return {'id': str(identifier), 'name': name or str(identifier), 'online': cloud_online(last_seen)}

def cloud_friends_sync(identity):
    discord_id = identity['id']
    conn = cloud_db()
    try:
        friends = [cloud_friend_entry(*row) for row in conn.execute(
            '''SELECT f.friend_id, u.display_name, u.last_seen
               FROM cloud_friendships f LEFT JOIN cloud_users u ON u.discord_id = f.friend_id
               WHERE f.owner_id = ? AND f.status = 'accepted' ORDER BY f.updated_at DESC''',
            (discord_id,)).fetchall()]
        incoming = [cloud_friend_entry(*row) for row in conn.execute(
            '''SELECT f.owner_id, u.display_name, u.last_seen
               FROM cloud_friendships f LEFT JOIN cloud_users u ON u.discord_id = f.owner_id
               WHERE f.friend_id = ? AND f.status = 'pending' ORDER BY f.created_at DESC''',
            (discord_id,)).fetchall()]
        outgoing = [cloud_friend_entry(*row) for row in conn.execute(
            '''SELECT f.friend_id, u.display_name, u.last_seen
               FROM cloud_friendships f LEFT JOIN cloud_users u ON u.discord_id = f.friend_id
               WHERE f.owner_id = ? AND f.status = 'pending' ORDER BY f.created_at DESC''',
            (discord_id,)).fetchall()]
        shares = [{
            'id': row[0], 'from_id': str(row[1]),
            'from_name': row[2] or str(row[1]),
            'name': row[3] or 'config', 'code': ''
        } for row in conn.execute(
            '''SELECT s.id, s.sender_id, u.display_name, s.name
               FROM cloud_shares s LEFT JOIN cloud_users u ON u.discord_id = s.sender_id
               WHERE s.recipient_id = ? AND s.claimed_at IS NULL ORDER BY s.id DESC''',
            (discord_id,)).fetchall()]
    finally:
        conn.close()
    return {
        'success': True, 'me': identity['name'] or discord_id,
        'friends': friends, 'incoming': incoming,
        'outgoing': outgoing, 'shares': shares
    }


@app.route('/api/friends/sync', methods=['POST', 'OPTIONS'])
def friends_sync():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    identity, error = cloud_auth(request.get_json(silent=True) or {})
    if error:
        return error
    return jsonify(cloud_friends_sync(identity))


@app.route('/api/friends/request', methods=['POST', 'OPTIONS'])
def friends_request():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    target_id = cloud_value(data.get('target_id'))
    if not target_id.isdigit() or not 5 <= len(target_id) <= 22:
        return cloud_error('Invalid Discord ID')
    if target_id == identity['id']:
        return cloud_error('Cannot add yourself')

    now = datetime.now().isoformat()
    conn = cloud_db()
    existing = conn.execute('SELECT status FROM cloud_friendships WHERE owner_id = ? AND friend_id = ?',
                            (identity['id'], target_id)).fetchone()
    reverse = conn.execute('SELECT status FROM cloud_friendships WHERE owner_id = ? AND friend_id = ?',
                           (target_id, identity['id'])).fetchone()
    if (existing and existing[0] == 'accepted') or (reverse and reverse[0] == 'accepted'):
        conn.close()
        return jsonify({'success': True, 'message': 'Already friends'}), 200
    if existing and existing[0] == 'pending':
        conn.close()
        return jsonify({'success': True, 'message': 'Request already pending'}), 200
    if reverse and reverse[0] == 'pending':
        conn.close()
        return cloud_error('The other user already has a pending request', 409)

    conn.execute('''INSERT OR IGNORE INTO cloud_friendships(owner_id, friend_id, status, created_at, updated_at)
                    VALUES (?, ?, 'pending', ?, ?)''', (identity['id'], target_id, now, now))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Friend request sent'}), 200


@app.route('/api/friends/respond', methods=['POST', 'OPTIONS'])
def friends_respond():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    from_id = cloud_value(data.get('from_id'))
    if not from_id.isdigit() or not 5 <= len(from_id) <= 22:
        return cloud_error('Invalid Discord ID')

    accept = cloud_bool(data.get('accept'))
    now = datetime.now().isoformat()
    conn = cloud_db()
    req_row = conn.execute(
        "SELECT 1 FROM cloud_friendships WHERE owner_id = ? AND friend_id = ? AND status = 'pending'",
        (from_id, identity['id'])).fetchone()
    if not req_row:
        conn.close()
        return cloud_error('Friend request not found', 404)

    if accept:
        conn.execute("UPDATE cloud_friendships SET status = 'accepted', updated_at = ? WHERE owner_id = ? AND friend_id = ? AND status = 'pending'",
                     (now, from_id, identity['id']))
        conn.execute("INSERT OR IGNORE INTO cloud_friendships(owner_id, friend_id, status, created_at, updated_at) VALUES (?, ?, 'accepted', ?, ?)",
                     (identity['id'], from_id, now, now))
        conn.execute("UPDATE cloud_friendships SET status = 'accepted', updated_at = ? WHERE owner_id = ? AND friend_id = ?",
                     (now, identity['id'], from_id))
    else:
        conn.execute("DELETE FROM cloud_friendships WHERE owner_id = ? AND friend_id = ? AND status = 'pending'",
                     (from_id, identity['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'accepted': accept}), 200


@app.route('/api/friends/remove', methods=['POST', 'OPTIONS'])
def friends_remove():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    friend_id = cloud_value(data.get('friend_id'))
    if not friend_id.isdigit() or not 5 <= len(friend_id) <= 22:
        return cloud_error('Invalid Discord ID')

    conn = cloud_db()
    result = conn.execute(
        'DELETE FROM cloud_friendships WHERE (owner_id = ? AND friend_id = ?) OR (owner_id = ? AND friend_id = ?)',
        (identity['id'], friend_id, friend_id, identity['id']))
    removed = result.rowcount
    conn.commit()
    conn.close()
    if not removed:
        return cloud_error('Friend not found', 404)
    return jsonify({'success': True, 'message': 'Friend removed'}), 200


@app.route('/api/friends/share', methods=['POST', 'OPTIONS'])
def friends_share():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    friend_id = cloud_value(data.get('friend_id'))
    if not friend_id.isdigit() or not 5 <= len(friend_id) <= 22:
        return cloud_error('Invalid Discord ID')
    config = data.get('config')
    if isinstance(config, (dict, list)):
        config = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
    elif not isinstance(config, str):
        config = ''
    if not config:
        return cloud_error('Empty config')
    if len(config.encode('utf-8')) > 2 * 1024 * 1024:
        return cloud_error('Config too large', 413)
    name = cloud_label(data.get('name')) or 'config'

    conn = cloud_db()
    friend_row = conn.execute(
        "SELECT 1 FROM cloud_friendships WHERE status = 'accepted' AND ((owner_id = ? AND friend_id = ?) OR (owner_id = ? AND friend_id = ?))",
        (identity['id'], friend_id, friend_id, identity['id'])).fetchone()
    if not friend_row:
        conn.close()
        return cloud_error('You are not friends', 403)

    cursor = conn.execute('INSERT INTO cloud_shares(sender_id, recipient_id, name, config, created_at) VALUES (?, ?, ?, ?, ?)',
                          (identity['id'], friend_id, name, config, datetime.now().isoformat()))
    share_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'share_id': share_id}), 200


@app.route('/api/friends/claim', methods=['POST', 'OPTIONS'])
def friends_claim():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    try:
        share_id = int(data.get('share_id'))
    except (TypeError, ValueError):
        return cloud_error('Invalid share')
    if share_id <= 0:
        return cloud_error('Invalid share')

    conn = cloud_db()
    row = conn.execute('SELECT sender_id, name, config, claimed_at FROM cloud_shares WHERE id = ? AND recipient_id = ?',
                       (share_id, identity['id'])).fetchone()
    if not row:
        conn.close()
        return cloud_error('Share not found', 404)
    if row[3]:
        conn.close()
        return cloud_error('Share already claimed', 409)

    if cloud_bool(data.get('apply')):
        result = conn.execute('UPDATE cloud_shares SET claimed_at = ? WHERE id = ? AND recipient_id = ? AND claimed_at IS NULL',
                              (datetime.now().isoformat(), share_id, identity['id']))
        conn.commit()
        conn.close()
        if not result.rowcount:
            return cloud_error('Share already claimed', 409)
        return jsonify({'success': True, 'name': row[1], 'config': row[2]}), 200
    conn.close()
    return jsonify({'success': True, 'name': row[1]}), 200


@app.route('/api/config/save', methods=['POST', 'OPTIONS'])
def cloud_config_save():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    name = cloud_label(data.get('name')) or 'config'
    config = data.get('config')
    if isinstance(config, (dict, list)):
        config = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
    elif not isinstance(config, str):
        config = ''
    if not config:
        return cloud_error('Empty config')
    if len(config.encode('utf-8')) > 2 * 1024 * 1024:
        return cloud_error('Config too large', 413)

    conn = cloud_db()
    code = None
    for _ in range(10):
        candidate = uuid.uuid4().hex[:8].upper()
        try:
            conn.execute('INSERT INTO cloud_configs(owner_id, code, name, config, created_at) VALUES (?, ?, ?, ?, ?)',
                         (identity['id'], candidate, name, config, datetime.now().isoformat()))
            code = candidate
            break
        except sqlite3.IntegrityError:
            continue
    if code is None:
        conn.close()
        return cloud_error('Could not allocate share code', 503)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'code': code}), 200


@app.route('/api/config/load', methods=['POST', 'OPTIONS'])
def cloud_config_load():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    code = cloud_code(data.get('code'))
    if len(code) != 8:
        return cloud_error('Invalid code')
    conn = cloud_db()
    row = conn.execute('SELECT name, config, created_at, use_count FROM cloud_configs WHERE code = ?', (code,)).fetchone()
    if not row:
        conn.close()
        return cloud_error('Config not found', 404)
    use_count = (row[3] or 0) + 1
    conn.execute('UPDATE cloud_configs SET use_count = ? WHERE code = ?', (use_count, code))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'name': row[0], 'config': row[1], 'created_at': row[2], 'use_count': use_count}), 200


@app.route('/api/config/mine', methods=['POST', 'OPTIONS'])
def cloud_config_mine():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    identity, error = cloud_auth(request.get_json(silent=True) or {})
    if error:
        return error
    conn = cloud_db()
    rows = conn.execute('SELECT code, name, created_at, use_count FROM cloud_configs WHERE owner_id = ? ORDER BY id DESC',
                        (identity['id'],)).fetchall()
    conn.close()
    return jsonify({
        'success': True,
        'configs': [{'code': r[0], 'name': r[1], 'created_at': r[2], 'use_count': r[3]} for r in rows]
    }), 200


@app.route('/api/config/delete', methods=['POST', 'OPTIONS'])
def cloud_config_delete():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    identity, error = cloud_auth(data)
    if error:
        return error
    code = cloud_code(data.get('code'))
    if len(code) != 8:
        return cloud_error('Invalid code')
    conn = cloud_db()
    result = conn.execute('DELETE FROM cloud_configs WHERE owner_id = ? AND code = ?', (identity['id'], code))
    deleted = result.rowcount
    conn.commit()
    conn.close()
    if not deleted:
        return cloud_error('Config not found', 404)
    return jsonify({'success': True}), 200


def run_flask():
    # threaded: multiple cheats poll/login concurrently (chat presence every 10s per client)
    # PORT env: hosting platforms (Render) assign the port dynamically
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

def start_api_server():
    threading.Thread(target=run_flask, daemon=True).start()


# ---- Chat + Party API (menu) ----
try:
    from chat_party import register_chat_party
    register_chat_party(app)
except Exception as _chat_err:
    print(f"[CHAT] mount failed: {_chat_err}")


# ══════════════════════════════════════════════════════════════
#  Discord Bot  –  Commands
# ══════════════════════════════════════════════════════════════

VALID_DURATIONS = ["minute", "hour", "day", "week", "month", "year"]


@bot.command()
@commands.has_permissions(administrator=True)
async def createkey(ctx, duration_value: int, duration_type: str):
    """Erstellt einen neuen Key: !createkey 30 day"""
    if duration_type.lower() not in VALID_DURATIONS:
        await ctx.send(embed=error_embed("Ungültiger Zeittyp", f"Gültig: {', '.join(VALID_DURATIONS)}"))
        return

    key = f"PRT-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now().isoformat()
    expires_at = get_expiry(duration_type.lower(), duration_value)

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT INTO keys (key, created_at, expires_at, duration_type, duration_value) VALUES (?, ?, ?, ?, ?)",
              (key, now, expires_at, duration_type.lower(), duration_value))
    c.execute("INSERT INTO key_meta (key, created_by) VALUES (?, ?)", (key, str(ctx.author.id)))
    conn.commit()
    sync_db_to_gist()
    conn.close()

    embed = success_embed("Key erstellt",
        "\n".join([
            f"> **Key:** `{key}`",
            f"> **Laufzeit:** {duration_value} {duration_type}",
            f"> **Verbleibend:** {time_remaining(expires_at)}",
        ]))
    await ctx.send(embed=embed)
    await send_log("Key erstellt", ctx.author, f"Key: `{key}` · {duration_value} {duration_type}", ACCENT_GREEN)


@bot.command()
@commands.has_permissions(administrator=True)
async def deletekey(ctx, *, key: str):
    """Löscht einen Key: !deletekey XXXX"""
    key = key.strip().upper()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if key == "ALL":
        c.execute("SELECT COUNT(*) FROM keys")
        count = c.fetchone()[0]
        if count == 0:
            await ctx.send(embed=info_embed("Keine Keys vorhanden"))
            conn.close()
            return
        c.execute("DELETE FROM keys")
        c.execute("DELETE FROM key_meta")
        conn.commit()
        sync_db_to_gist()
        conn.close()
        await ctx.send(embed=success_embed("Alle Keys gelöscht", f"{count} Keys wurden entfernt."))
        await send_log("Alle Keys gelöscht", ctx.author, f"{count} Keys entfernt", ACCENT_RED)
        return

    c.execute("SELECT hwid FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    if not result:
        await ctx.send(embed=error_embed("Key nicht gefunden"))
        conn.close()
        return

    c.execute("DELETE FROM keys WHERE key = ?", (key,))
    c.execute("DELETE FROM key_meta WHERE key = ?", (key,))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    await ctx.send(embed=success_embed("Key gelöscht", f"`{key}` wurde entfernt."))
    await send_log("Key gelöscht", ctx.author, f"Key: `{key}`", ACCENT_RED)


@bot.command()
@commands.has_permissions(administrator=True)
async def listkeys(ctx):
    """Listet alle Keys auf"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT key, discord_id, expires_at, used FROM keys ORDER BY created_at DESC")
    results = c.fetchall()
    conn.close()

    if not results:
        await ctx.send(embed=info_embed("Keine Keys vorhanden"))
        return

    embed = make_embed("Key-Liste")
    for key, discord_id, expires_at, used in results:
        status = "Aktiv" if used else "Frei"
        frozen = get_frozen_at(key)
        if frozen:
            status = "Eingefroren ❄️"
        user_str = f"<@{discord_id}>" if discord_id and discord_id.isdigit() else "—"
        embed.add_field(name=f"`{key}`  ·  {status}", value=f"Verbleibend: {time_remaining_effective(expires_at, frozen)}\nDiscord: {user_str}", inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def check(ctx, discord_id: str = None):
    """Zeigt Key-Infos zu einer Discord ID"""
    if not discord_id:
        await ctx.send(embed=error_embed("Nutzung", "`!check <discord_id>`"))
        return

    channel = bot.get_channel(CHECK_CHANNEL_ID)
    if not channel:
        await ctx.send(embed=error_embed("Check-Channel nicht gefunden"))
        return

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE discord_id = ?", (discord_id.strip(),))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await channel.send(embed=info_embed("Keine Keys gefunden", f"Discord ID: `{discord_id}`"))
        return

    try:
        user = await bot.fetch_user(int(discord_id))
        name = str(user)
    except Exception:
        name = "Unbekannt"

    for key, hwid, _, created_at, expires_at, _, _, used in rows:
        embed = make_embed("User-Info")
        embed.add_field(name="Discord", value=name, inline=True)
        embed.add_field(name="ID", value=f"`{discord_id}`", inline=True)
        embed.add_field(name="Key", value=f"`{key}`", inline=False)
        embed.add_field(name="Erstellt", value=format_date(created_at), inline=True)
        embed.add_field(name="HWID", value=f"`{hwid or '—'}`", inline=True)
        embed.add_field(name="Status", value="Eingelöst" if used else "Frei", inline=True)
        await channel.send(embed=embed)


@bot.command()
async def addtime(ctx, key: str, amount: int, time_type: str):
    """Fügt Zeit zu einem Key hinzu"""
    key = key.strip()
    if time_type.lower() not in VALID_DURATIONS:
        await ctx.send(embed=error_embed("Ungültiger Zeittyp", f"Gültig: {', '.join(VALID_DURATIONS)}"))
        return

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    if not result:
        await ctx.send(embed=error_embed("Key nicht gefunden"))
        conn.close()
        return

    new_expiry = get_expiry(time_type.lower(), amount, result[0])
    c.execute("UPDATE keys SET expires_at = ? WHERE key = ?", (new_expiry, key))
    conn.commit()
    sync_db_to_gist()
    conn.close()

    await ctx.send(embed=success_embed("Zeit hinzugefügt", f"`{key}` → +{amount} {time_type}\nNeu: {time_remaining(new_expiry)}"))
    await send_log("Zeit hinzugefügt", ctx.author, f"Key: `{key}` · +{amount} {time_type}", ACCENT_BLUE)


@bot.command(name="freeze")
async def freeze(ctx, key: str):
    """Friert einen Key ein (Ablauf pausiert): !freeze RAYX-XXXX"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), delete_after=5)
        return
    key = key.strip().upper()
    ok, err = freeze_key(key)
    if not ok:
        await ctx.send(embed=error_embed("Freeze fehlgeschlagen", err))
        return
    await ctx.send(embed=success_embed("Key eingefroren", f"`{key}` – Ablauf pausiert."))
    await send_log("Key eingefroren", ctx.author, f"Key: `{key}`", ACCENT_YELLOW)


@bot.command(name="unfreeze")
async def unfreeze(ctx, key: str):
    """Taucht einen Key auf (Zeit wird gutgeschrieben): !unfreeze RAYX-XXXX"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), delete_after=5)
        return
    key = key.strip().upper()
    ok, info = unfreeze_key(key)
    if not ok:
        await ctx.send(embed=error_embed("Unfreeze fehlgeschlagen", info))
        return
    await ctx.send(embed=success_embed("Key aufgetaut", f"`{key}` · {info}"))
    await send_log("Key aufgetaut", ctx.author, f"Key: `{key}` · {info}", ACCENT_GREEN)


@bot.command()
@commands.has_permissions(administrator=True)
async def restart(ctx):
    """Startet den Bot neu"""
    await ctx.send(embed=info_embed("Neustart", "Bot wird neu gestartet..."))
    subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    await bot.close()


@bot.command()
@commands.has_permissions(administrator=True)
async def clear(ctx):
    """Löscht alle Nachrichten und sperrt den Channel"""
    await ctx.channel.purge(limit=None)
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False, add_reactions=False)
    await ctx.send("Channel bereinigt.", delete_after=5)


@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    """Entsperrt den Channel"""
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None, add_reactions=None)
    await ctx.send(embed=success_embed("Channel entsperrt"), delete_after=5)


@bot.command()
async def hwidreset(ctx, *, key: str):
    """Setzt die HWID eines Keys zurück"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), ephemeral=True)
        return
    key = key.strip()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM keys WHERE key = ?", (key,))
    if not c.fetchone():
        await ctx.send(embed=error_embed("Key nicht gefunden"), ephemeral=True)
        conn.close()
        return
    c.execute("UPDATE keys SET hwid = NULL, used = 0, discord_id = NULL WHERE key = ?", (key,))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    await ctx.send(embed=success_embed("HWID zurückgesetzt", f"`{key}` kann erneut eingelöst werden."), ephemeral=True)
    await send_log("HWID Reset", ctx.author, f"Key: `{key}`", ACCENT_YELLOW)


@bot.command()
async def addwhitelist(ctx, member: discord.Member):
    """Fügt einen User zur Whitelist hinzu"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), ephemeral=True)
        return
    if is_whitelisted(member.id):
        await ctx.send(embed=error_embed("Bereits in Whitelist"), ephemeral=True)
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT INTO whitelist (discord_id, added_at) VALUES (?, ?)", (str(member.id), datetime.now().isoformat()))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    await ctx.send(embed=success_embed("Whitelist", f"{member.mention} hinzugefügt."), ephemeral=True)
    await send_log("Whitelist +", ctx.author, f"{member} ({member.id})", ACCENT_GREEN)


@bot.command()
async def removewhitelist(ctx, member: discord.Member):
    """Entfernt einen User aus der Whitelist"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), ephemeral=True)
        return
    if str(member.id) == MASTER_ID:
        await ctx.send(embed=error_embed("Master kann nicht entfernt werden"), ephemeral=True)
        return
    if not is_whitelisted(member.id):
        await ctx.send(embed=error_embed("Nicht in Whitelist"), ephemeral=True)
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM whitelist WHERE discord_id = ?", (str(member.id),))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    await ctx.send(embed=success_embed("Whitelist", f"{member.mention} entfernt."), ephemeral=True)
    await send_log("Whitelist −", ctx.author, f"{member} ({member.id})", ACCENT_RED)


@bot.command()
async def listwhitelist(ctx):
    """Listet die Whitelist"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff"), ephemeral=True)
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT discord_id, added_at FROM whitelist ORDER BY added_at DESC")
    results = c.fetchall()
    conn.close()

    embed = make_embed("Whitelist")
    for user_id, added_at in results:
        try:
            user = await bot.fetch_user(int(user_id))
            name = user.name
        except Exception:
            name = "Unbekannt"
        embed.add_field(name=name, value=f"`{user_id}` · seit {added_at[:10]}", inline=False)
    await ctx.send(embed=embed, ephemeral=True)


@bot.command()
async def load(ctx):
    """Öffnet das Cheat-Menü"""
    try:
        if os.path.exists(CHEAT_EXE):
            os.system(f'cmd /c start "" "{CHEAT_EXE}"')
        await ctx.message.delete()
        embed = make_embed("Cheat-Menü", "Klicke auf den Button um das Menü zu öffnen.", thumbnail=False)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Menü öffnen", url=LOAD_URL, style=discord.ButtonStyle.link))
        await ctx.send(embed=embed, view=view, delete_after=15)
    except Exception as e:
        print(f"[LOAD] Fehler: {e}")


@bot.command()
async def menu(ctx):
    """Zeigt das Key-Verwaltungsmenü"""
    await ctx.message.delete()
    if not is_whitelisted(ctx.author.id):
        await ctx.send(embed=error_embed("Kein Zugriff", "Du bist nicht in der Whitelist."), ephemeral=True)
        return

    if ctx.author.guild_permissions.administrator:
        embed = build_admin_menu_embed()
        await ctx.send(embed=embed, view=AdminMenuView())
    else:
        embed = discord.Embed(title="Key Verwaltung", color=BRAND_COLOR, timestamp=datetime.now())
        embed.set_thumbnail(url=TICKET_LOGO_URL)
        embed.add_field(name="Key einlösen", value="> Löse einen Key ein", inline=True)
        embed.add_field(name="Key prüfen", value="> Prüfe einen Key", inline=True)
        embed.set_footer(text=FOOTER_TEXT)
        await ctx.send(embed=embed, view=UserMenuView())


# ══════════════════════════════════════════════════════════════
#  Embed Builders  –  wiederverwendbar für start + loop
# ══════════════════════════════════════════════════════════════

def build_admin_menu_embed():
    """Admin Key-Verwaltung Embed (einmal definiert, überall genutzt)."""
    embed = discord.Embed(title="Key Verwaltung", color=BRAND_COLOR, timestamp=datetime.now())
    embed.set_thumbnail(url=TICKET_LOGO_URL)
    embed.add_field(name="Erstellen", value="> Erstelle einen neuen Key", inline=True)
    embed.add_field(name="Prüfen", value="> Prüfe einen Key", inline=True)
    embed.add_field(name="Löschen", value="> Lösche einen Key", inline=True)
    embed.add_field(name="Zeit+", value="> Füge Zeit hinzu", inline=True)
    embed.add_field(name="Freeze", value="> Friere Key ein", inline=True)
    embed.add_field(name="Unfreeze", value="> Taue Key auf", inline=True)
    embed.add_field(name="Keys", value="> Zeige alle Keys", inline=True)
    embed.add_field(name="HWID", value="> Setzt HWID zurück", inline=True)
    embed.add_field(name="Restart", value="> Bot neu starten", inline=True)
    embed.add_field(name="Unlock", value="> Entsperrt Channel", inline=True)
    embed.add_field(name="Support", value="> RAYX Support", inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_whitelist_menu_embed():
    """Whitelist-Verwaltung Embed."""
    embed = discord.Embed(title="📋 Whitelist Verwaltung", color=BRAND_COLOR, timestamp=datetime.now())
    embed.set_thumbnail(url=BYPASS_LOGO)
    embed.add_field(name="👑 Add Master", value="> Füge einen Master hinzu", inline=True)
    embed.add_field(name="➕ Add Whitelist", value="> Füge einen User hinzu", inline=True)
    embed.add_field(name="➖ Remove Whitelist", value="> Entferne einen User", inline=True)
    embed.add_field(name="📋 Whitelist", value="> Zeige alle Whitelist Users", inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_user_check_embed():
    """User-Prüfen Embed."""
    embed = discord.Embed(title="🔍 User Prüfen", color=BRAND_COLOR, timestamp=datetime.now())
    embed.set_thumbnail(url=BYPASS_LOGO)
    embed.add_field(name="Was du sehen kannst", value="> Gib eine Discord ID ein und erhalte:\n> Key, HWID, Erstellt von/wann, Ablauf, Logins im Loader", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_keys_overview_embeds():
    """Key-Übersicht Embeds (kann mehrere sein bei >25 Keys)."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()

    embed = discord.Embed(title="📋 Key Übersicht", color=BRAND_COLOR, timestamp=datetime.now())
    embed.set_thumbnail(url=BYPASS_LOGO)
    if not rows:
        embed.description = "> Keine Keys vorhanden."
        embed.set_footer(text=FOOTER_TEXT)
        return [embed]

    used_count = sum(1 for r in rows if r[7])
    free_count = len(rows) - used_count
    embed.description = f"> **Gesamt:** {len(rows)}\n> **Benutzt:** {used_count}\n> **Frei:** {free_count}"

    embeds = [embed]
    count = 0
    for row in rows:
        key, hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = row
        status = "🟢 Benutzt" if used else "⚪ Unbenutzt"
        frozen = get_frozen_at(key)
        if frozen:
            status = "❄️ Eingefroren"
        time_left = time_remaining_effective(expires_at, frozen)
        user_str = f"<@{discord_id}>" if discord_id and discord_id.isdigit() else "N/A"
        value = f"**Status:** {status}\n**Zeit:** {time_left}\n**Discord:** {user_str}"
        if count >= 25:
            embeds.append(discord.Embed(title="📋 Key Übersicht", color=BRAND_COLOR))
            count = 0
        embeds[-1].add_field(name=f"`{key}`", value=value, inline=False)
        count += 1

    for i, e in enumerate(embeds):
        e.set_footer(text=FOOTER_TEXT)
        if i > 0:
            e.set_thumbnail(url=BYPASS_LOGO)
    return embeds


def build_bot_status_embed():
    """Bot-Status Embed."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM keys")
    total_keys = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys WHERE used = 1")
    used_keys = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT hwid) FROM keys WHERE hwid IS NOT NULL AND hwid != ''")
    hwids = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM whitelist")
    wl_count = c.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="RAYX Status", color=BRAND_COLOR, timestamp=datetime.now())
    embed.set_thumbnail(url=BYPASS_LOGO)
    embed.add_field(name="Bot", value=f"Online als {bot.user}", inline=False)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Guilds", value=f"{len(bot.guilds)}", inline=True)
    embed.add_field(name="Uptime", value=format_uptime(BOT_START_TIME), inline=True)
    embed.add_field(name="API", value=check_api_status(), inline=False)
    embed.add_field(name="Statistiken",
                    value=f"Keys gesamt: {total_keys}\nVerwendet: {used_keys}\nRegistrierte HWIDs: {hwids}\nWhitelist: {wl_count}",
                    inline=False)
    embed.set_footer(text="F I STEINKE C++ MEISTER · aktualisiert alle 10 Minuten")
    return embed


# ══════════════════════════════════════════════════════════════
#  Modals & Views
# ══════════════════════════════════════════════════════════════

class KeyModal(discord.ui.Modal):
    def __init__(self, action):
        super().__init__(title=action)
        self.action = action

        if action == "Key erstellen":
            self.duration_type = discord.ui.TextInput(label="Zeittyp", placeholder="day / month / lifetime")
            self.duration_value = discord.ui.TextInput(label="Anzahl", placeholder="z.B. 30")
            self.add_item(self.duration_type)
            self.add_item(self.duration_value)
        elif action in ("Key einlösen", "Key prüfen", "Key löschen", "Zeit hinzufügen", "HWID Reset", "Key einfrieren", "Key auftauen"):
            self.key_input = discord.ui.TextInput(label="Key", placeholder="RAYX-XXXXXXXX")
            self.add_item(self.key_input)
            if action == "Zeit hinzufügen":
                self.amount = discord.ui.TextInput(label="Anzahl", placeholder="z.B. 7")
                self.time_type = discord.ui.TextInput(label="Zeittyp", placeholder="day / month")
                self.add_item(self.amount)
                self.add_item(self.time_type)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()

        try:
            if self.action == "Key erstellen":
                await self._create_key(interaction, c, conn)
            elif self.action == "Key einlösen":
                await self._redeem_key(interaction, c, conn)
            elif self.action == "Key prüfen":
                await self._check_key(interaction, c, conn)
            elif self.action == "Key löschen":
                await self._delete_key(interaction, c, conn)
            elif self.action == "Zeit hinzufügen":
                await self._add_time(interaction, c, conn)
            elif self.action == "HWID Reset":
                await self._hwid_reset(interaction, c, conn)
            elif self.action == "Key einfrieren":
                await self._freeze(interaction, c, conn)
            elif self.action == "Key auftauen":
                await self._unfreeze(interaction, c, conn)
        finally:
            conn.close()

    async def _freeze(self, interaction, c, conn):
        key = self.key_input.value.strip().upper()
        c.execute("SELECT 1 FROM keys WHERE key = ?", (key,))
        if not c.fetchone():
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        ok, err = freeze_key(key)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Freeze fehlgeschlagen", err), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Key eingefroren", f"`{key}` – Ablauf pausiert."), ephemeral=True)
        await send_log("Key eingefroren", interaction.user, f"Key: `{key}`", ACCENT_YELLOW)

    async def _unfreeze(self, interaction, c, conn):
        key = self.key_input.value.strip().upper()
        c.execute("SELECT 1 FROM keys WHERE key = ?", (key,))
        if not c.fetchone():
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        ok, info = unfreeze_key(key)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Unfreeze fehlgeschlagen", info), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Key aufgetaut", f"`{key}` · {info}"), ephemeral=True)
        await send_log("Key aufgetaut", interaction.user, f"Key: `{key}` · {info}", ACCENT_GREEN)

    async def _create_key(self, interaction, c, conn):
        try:
            amount = int(self.duration_value.value)
            dtype = self.duration_type.value.lower()
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Ungültige Zahl"), ephemeral=True)
            return

        valid = ["day", "month", "lifetime"]
        if dtype not in valid:
            await interaction.response.send_message(embed=error_embed("Ungültiger Zeittyp", f"Gültig: {', '.join(valid)}"), ephemeral=True)
            return

        key = f"RAYX-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now().isoformat()
        expires_at = "9999-12-31T23:59:59" if dtype == "lifetime" else get_expiry(dtype, amount)

        c.execute("INSERT INTO keys (key, created_at, expires_at, duration_type, duration_value) VALUES (?, ?, ?, ?, ?)",
                  (key, now, expires_at, dtype, amount))
        c.execute("INSERT INTO key_meta (key, created_by) VALUES (?, ?)", (key, str(interaction.user.id)))
        conn.commit()
        sync_db_to_gist()

        embed = success_embed("Key erstellt",
            "\n".join([
                f"> **Key:** `{key}`",
                f"> **Laufzeit:** {amount} {dtype}" if dtype != "lifetime" else f"> **Laufzeit:** Lifetime",
            ]))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log("Key erstellt", interaction.user, f"Key: `{key}` · {amount} {dtype}", ACCENT_GREEN)

    async def _redeem_key(self, interaction, c, conn):
        key = self.key_input.value.strip()
        c.execute("SELECT * FROM keys WHERE key = ?", (key,))
        result = c.fetchone()
        if not result:
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        _, _, _, _, expires_at, _, _, used = result
        if used:
            await interaction.response.send_message(embed=error_embed("Key bereits eingelöst"), ephemeral=True)
            return
        if datetime.now() > datetime.fromisoformat(expires_at):
            await interaction.response.send_message(embed=error_embed("Key abgelaufen"), ephemeral=True)
            return

        c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?",
                  (str(interaction.user.id), str(interaction.user.id), key))
        conn.commit()
        sync_db_to_gist()

        embed = success_embed("Key eingelöst")
        embed.add_field(name="Discord", value=f"{interaction.user.mention}", inline=True)
        embed.add_field(name="Verbleibend", value=time_remaining(expires_at), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log("Key eingelöst", interaction.user, f"Key: `{key}`", ACCENT_GREEN)

    async def _check_key(self, interaction, c, conn):
        key = self.key_input.value.strip()
        c.execute("SELECT discord_id, expires_at, used FROM keys WHERE key = ?", (key,))
        result = c.fetchone()
        if not result:
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        discord_id, expires_at, used = result
        frozen = get_frozen_at(key)
        embed = info_embed("Key-Info")
        embed.add_field(name="Key", value=f"`{key}`", inline=False)
        embed.add_field(name="Status", value=("Eingefroren ❄️" if frozen else ("Eingelöst" if used else "Frei")), inline=True)
        embed.add_field(name="Verbleibend", value=time_remaining_effective(expires_at, frozen), inline=True)
        if discord_id:
            embed.add_field(name="Discord", value=f"<@{discord_id}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _delete_key(self, interaction, c, conn):
        key = self.key_input.value.strip().upper()
        c.execute("SELECT 1 FROM keys WHERE key = ?", (key,))
        if not c.fetchone():
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        c.execute("DELETE FROM keys WHERE key = ?", (key,))
        c.execute("DELETE FROM key_meta WHERE key = ?", (key,))
        conn.commit()
        sync_db_to_gist()
        await interaction.response.send_message(embed=success_embed("Key gelöscht", f"`{key}` entfernt."), ephemeral=True)
        await send_log("Key gelöscht", interaction.user, f"Key: `{key}`", ACCENT_RED)

    async def _add_time(self, interaction, c, conn):
        key = self.key_input.value.strip()
        try:
            amount = int(self.amount.value)
            dtype = self.time_type.value.lower()
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Ungültige Zahl"), ephemeral=True)
            return
        if dtype not in VALID_DURATIONS:
            await interaction.response.send_message(embed=error_embed("Ungültiger Zeittyp"), ephemeral=True)
            return
        c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
        result = c.fetchone()
        if not result:
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        new_expiry = get_expiry(dtype, amount, result[0])
        c.execute("UPDATE keys SET expires_at = ? WHERE key = ?", (new_expiry, key))
        conn.commit()
        sync_db_to_gist()
        await interaction.response.send_message(embed=success_embed("Zeit hinzugefügt", f"`{key}` → +{amount} {dtype}\nNeu: {time_remaining(new_expiry)}"), ephemeral=True)
        await send_log("Zeit hinzugefügt", interaction.user, f"Key: `{key}` · +{amount} {dtype}", ACCENT_BLUE)

    async def _hwid_reset(self, interaction, c, conn):
        key = self.key_input.value.strip()
        c.execute("SELECT 1 FROM keys WHERE key = ?", (key,))
        if not c.fetchone():
            await interaction.response.send_message(embed=error_embed("Key nicht gefunden"), ephemeral=True)
            return
        c.execute("UPDATE keys SET hwid = NULL, used = 0, discord_id = NULL WHERE key = ?", (key,))
        conn.commit()
        sync_db_to_gist()
        await interaction.response.send_message(embed=success_embed("HWID zurückgesetzt", f"`{key}` kann erneut eingelöst werden."), ephemeral=True)
        await send_log("HWID Reset", interaction.user, f"Key: `{key}`", ACCENT_YELLOW)


class AdminMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Erstellen", style=discord.ButtonStyle.secondary, custom_id="admin_create", emoji="📦")
    async def create_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key erstellen"))

    @discord.ui.button(label="Prüfen", style=discord.ButtonStyle.secondary, custom_id="admin_check", emoji="🔍")
    async def check_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key prüfen"))

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.secondary, custom_id="admin_delete", emoji="🗑️")
    async def delete_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key löschen"))

    @discord.ui.button(label="Zeit+", style=discord.ButtonStyle.secondary, custom_id="admin_addtime", emoji="⏰")
    async def add_time_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Zeit hinzufügen"))

    @discord.ui.button(label="Freeze", style=discord.ButtonStyle.secondary, custom_id="admin_freeze", emoji="❄️")
    async def freeze_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key einfrieren"))

    @discord.ui.button(label="Unfreeze", style=discord.ButtonStyle.secondary, custom_id="admin_unfreeze", emoji="🔥")
    async def unfreeze_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key auftauen"))

    @discord.ui.button(label="HWID", style=discord.ButtonStyle.secondary, custom_id="admin_hwidreset", emoji="🔄")
    async def hwid_reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("HWID Reset"))

    @discord.ui.button(label="Keys", style=discord.ButtonStyle.secondary, custom_id="admin_list", emoji="📋")
    async def list_keys_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT key, discord_id, expires_at, used FROM keys ORDER BY created_at DESC")
        results = c.fetchall()
        conn.close()

        if not results:
            await interaction.response.send_message(embed=info_embed("Keine Keys vorhanden"), ephemeral=True)
            return

        embed = make_embed("Key-Liste", thumbnail=False)
        for key, discord_id, expires_at, used in results:
            status = "Aktiv" if used else "Frei"
            frozen = get_frozen_at(key)
            if frozen:
                status = "Eingefroren ❄️"
            user_str = f"<@{discord_id}>" if discord_id and discord_id.isdigit() else "—"
            embed.add_field(name=f"`{key}`  ·  {status}", value=f"Verbleibend: {time_remaining_effective(expires_at, frozen)}\nDiscord: {user_str}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.secondary, custom_id="admin_restart", emoji="🔁")
    async def restart_bot_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=info_embed("Neustart..."), ephemeral=True)
        await send_bot_log("Bot-Neustart", f"Ausgelöst von {interaction.user}")
        subprocess.Popen([sys.executable, os.path.abspath(__file__)])
        await bot.close()

    @discord.ui.button(label="Unlock", style=discord.ButtonStyle.secondary, custom_id="admin_unlock", emoji="🔓")
    async def unlock_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, add_reactions=None)
        await interaction.response.send_message(embed=success_embed("Channel entsperrt"), delete_after=5, ephemeral=True)
        await send_bot_log("Channel entsperrt", f"Von {interaction.user} in #{interaction.channel.name}")


class UserMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Einlösen", style=discord.ButtonStyle.secondary, custom_id="user_redeem", emoji="🎫")
    async def redeem_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key einlösen"))

    @discord.ui.button(label="Prüfen", style=discord.ButtonStyle.secondary, custom_id="user_check", emoji="🔍")
    async def check_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key prüfen"))


class UserCheckModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="User Prüfen")
        self.user_id_input = discord.ui.TextInput(label="Discord ID", placeholder="z.B. 1027571297514967140")
        self.add_item(self.user_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return

        uid = self.user_id_input.value.strip()
        try:
            user = await bot.fetch_user(int(uid))
            username = user.name
        except Exception:
            username = "Unbekannt"

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT key, hwid, created_at, expires_at, used FROM keys WHERE discord_id = ?", (uid,))
        rows = c.fetchall()
        if not rows:
            conn.close()
            await interaction.response.send_message(embed=info_embed("Keine Keys gefunden", f"Discord ID: `{uid}`"), ephemeral=True)
            return

        embed = discord.Embed(title=f"User Prüfen - {username}", color=BRAND_COLOR)
        embed.add_field(name="Discord ID", value=f"`{uid}`", inline=True)

        for key, hwid, created_at, expires_at, used in rows:
            c.execute("SELECT created_by, login_count, last_login FROM key_meta WHERE key = ?", (key,))
            meta = c.fetchone()
            created_by = meta[0] if meta and meta[0] else "Unbekannt"
            login_count = meta[1] if meta else 0
            last_login = meta[2] if meta and meta[2] else "Nie"

            try:
                cb_user = await bot.fetch_user(int(created_by))
                created_by = cb_user.name
            except Exception:
                pass

            created_dt = datetime.fromisoformat(created_at)
            created_str = created_dt.strftime("%d.%m.%Y, %H:%M Uhr")

            expires_dt = datetime.fromisoformat(expires_at)
            exp_str = "Lifetime" if expires_dt.year == 9999 else expires_dt.strftime("%d.%m.%Y, %H:%M Uhr")

            status = "Eingelöst" if used else "Unbenutzt"
            hwid_str = hwid if hwid else "Nicht gesetzt"

            embed.add_field(
                name=f"Key: {key}",
                value=(
                    f"**Status:** {status}\n"
                    f"**HWID:** `{hwid_str}`\n"
                    f"**Erstellt:** {created_str}\n"
                    f"**Erstellt von:** {created_by}\n"
                    f"**Ablauf:** {exp_str}\n"
                    f"**Logins im Loader:** {login_count}\n"
                    f"**Letzter Login:** {last_login}"
                ),
                inline=False
            )
        conn.close()
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UserCheckView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="User Prüfen", style=discord.ButtonStyle.grey, custom_id="user_check_open", emoji="🔍")
    async def open_check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        await interaction.response.send_modal(UserCheckModal())


class WhitelistModal(discord.ui.Modal):
    def __init__(self, action):
        super().__init__(title=action)
        self.action = action
        self.discord_id = discord.ui.TextInput(label="Discord ID", placeholder="z.B. 123456789012345678")
        self.add_item(self.discord_id)

    async def on_submit(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        did = self.discord_id.value.strip()

        try:
            if self.action == "Add Whitelist":
                c.execute("INSERT OR IGNORE INTO whitelist (discord_id, added_at) VALUES (?, ?)", (did, datetime.now().isoformat()))
                conn.commit()
                sync_db_to_gist()
                await interaction.response.send_message(embed=success_embed("Whitelist", f"`{did}` hinzugefügt."), ephemeral=True)
                await send_log("Whitelist +", interaction.user, f"User: `{did}`", ACCENT_GREEN)

            elif self.action == "Remove Whitelist":
                c.execute("DELETE FROM whitelist WHERE discord_id = ?", (did,))
                conn.commit()
                sync_db_to_gist()
                await interaction.response.send_message(embed=success_embed("Whitelist", f"`{did}` entfernt."), ephemeral=True)
                await send_log("Whitelist −", interaction.user, f"User: `{did}`", ACCENT_RED)

            elif self.action == "Add Master":
                c.execute("INSERT OR IGNORE INTO masters (discord_id, added_at) VALUES (?, ?)", (did, datetime.now().isoformat()))
                c.execute("INSERT OR IGNORE INTO whitelist (discord_id, added_at) VALUES (?, ?)", (did, datetime.now().isoformat()))
                conn.commit()
                sync_db_to_gist()
                await interaction.response.send_message(embed=success_embed("Master", f"`{did}` hinzugefügt."), ephemeral=True)
                await send_log("Master +", interaction.user, f"User: `{did}`", ACCENT_GREEN)
        except Exception as e:
            await interaction.response.send_message(embed=error_embed("Fehler", str(e)), ephemeral=True)
        finally:
            conn.close()


class WhitelistMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Master+", style=discord.ButtonStyle.secondary, custom_id="wl_add_master", emoji="👑")
    async def add_master_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Nur Master"), ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Add Master"))

    @discord.ui.button(label="Add", style=discord.ButtonStyle.secondary, custom_id="wl_add", emoji="➕")
    async def add_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Nur Master"), ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Add Whitelist"))

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.secondary, custom_id="wl_remove", emoji="➖")
    async def remove_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Nur Master"), ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Remove Whitelist"))

    @discord.ui.button(label="List", style=discord.ButtonStyle.secondary, custom_id="wl_list", emoji="📋")
    async def list_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message(embed=error_embed("Kein Zugriff"), ephemeral=True)
            return
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT discord_id, added_at FROM whitelist ORDER BY added_at DESC")
        results = c.fetchall()
        conn.close()

        if not results:
            await interaction.response.send_message(embed=info_embed("Whitelist leer"), ephemeral=True)
            return

        embed = make_embed("Whitelist", thumbnail=False)
        for did, added_at in results:
            try:
                user = await bot.fetch_user(int(did))
                name = user.name
            except Exception:
                name = "Unbekannt"
            embed.add_field(name=name, value=f"`{did}` · seit {added_at[:10]}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  Ticket System
# ══════════════════════════════════════════════════════════════

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Kernel", description="Buy the Kernel plan", value="advanced_phone"),
            discord.SelectOption(label="Support", description="Help with setup errors or bugs", value="support"),
        ]
        super().__init__(placeholder="Choose an option", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        type_name = "Kernel" if self.values[0] == "advanced_phone" else "Support"
        member = interaction.user
        guild = interaction.guild

        existing = discord.utils.get(guild.text_channels, name=f"ticket-{member.name.lower()}")
        if existing:
            await interaction.response.send_message(embed=error_embed("Ticket existiert bereits", f"{existing.mention}"), ephemeral=True)
            return

        staff_role = guild.get_role(TICKET_STAFF_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)

        category_id = ADVANCED_CATEGORY_ID if self.values[0] == "advanced_phone" else SUPPORT_CATEGORY_ID
        category = guild.get_channel(category_id)

        ticket_channel = await guild.create_text_channel(name=f"ticket-{member.name.lower()}", overwrites=overwrites, category=category)

        ticket_channels[ticket_channel.id] = {"user_id": member.id, "type": type_name, "created_at": datetime.now().isoformat()}
        save_ticket_data()
        ticket_messages[ticket_channel.id] = []

        embed = make_embed(f"Ticket · {type_name}",
                           f"Welcome {member.mention}.\n\nPlease describe your issue and a staff member will assist you shortly.",
                           thumbnail=True)
        embed.set_footer(text=f"{member} · {FOOTER_TEXT} Support")
        await ticket_channel.send(content=member.mention, embed=embed, view=TicketButtons())
        await interaction.response.defer()
        await send_ticket_log(f"**New Ticket**\n> By: {member}\n> Type: {type_name}\n> Channel: {ticket_channel.mention}")


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ── Ticket-Panel im Help-Center-Stil (Banner oben, Text, Kategorien, Auswahl) ──
TICKET_BANNER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticket_banner.png")
TICKET_PANEL_TITLE = "Rayx Support"
TICKET_PANEL_INTRO = (
    "**English**\n"
    "Need help or want to buy a plan? Open a ticket below and our staff will get back to you.\n\n"
    "**Deutsch**\n"
    "Brauchst du Hilfe oder möchtest du einen Plan kaufen? Eröffne unten ein Ticket und unser Team meldet sich bei dir."
)
TICKET_PANEL_CATEGORIES = (
    ("Kernel", "Buy the Kernel plan\nKernel Plan kaufen"),
    ("Support", "Help with setup errors or bugs\nHilfe bei Setup Fehlern oder Bugs"),
)
TICKET_PANEL_FOOTER = "Rayx Support © 2026"

HAS_COMPONENTS_V2 = hasattr(discord.ui, "LayoutView") and hasattr(discord.ui, "Container")

if HAS_COMPONENTS_V2:
    class TicketPanel(discord.ui.LayoutView):
        """Neues Panel (discord.py 2.6+): alles in einem Block wie beim Help Center."""
        def __init__(self):
            super().__init__(timeout=None)
            container = discord.ui.Container(accent_colour=discord.Colour(0xFFFFFF))
            if os.path.isfile(TICKET_BANNER_FILE):
                container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://ticket_banner.png")))
            container.add_item(discord.ui.TextDisplay(f"## {TICKET_PANEL_TITLE}"))
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(TICKET_PANEL_INTRO))
            categories = "\n\n".join(
                f"**{name}**\n" + "\n".join(f"> -# {line}" for line in text.split("\n"))
                for name, text in TICKET_PANEL_CATEGORIES
            )
            container.add_item(discord.ui.TextDisplay(categories))
            row = discord.ui.ActionRow()
            row.add_item(TicketSelect())
            container.add_item(row)
            container.add_item(discord.ui.TextDisplay(f"-# {TICKET_PANEL_FOOTER}"))
            self.add_item(container)


def build_ticket_panel_embed():
    """Fallback für ältere discord.py-Versionen (klassisches Embed)."""
    embed = discord.Embed(title=TICKET_PANEL_TITLE, description=TICKET_PANEL_INTRO, color=0xFFFFFF)
    for name, text in TICKET_PANEL_CATEGORIES:
        embed.add_field(name=name, value="\n".join(f"> {line}" for line in text.split("\n")), inline=False)
    if os.path.isfile(TICKET_BANNER_FILE):
        embed.set_image(url="attachment://ticket_banner.png")
    embed.set_footer(text=TICKET_PANEL_FOOTER)
    return embed


class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        ticket_data = ticket_channels.get(channel.id)
        guild = interaction.guild

        if not ticket_data:
            if not channel.name.startswith("ticket-") or "-closed" in channel.name:
                await interaction.response.send_message(embed=error_embed("Kein Ticket"), ephemeral=True)
                return
            user = None
            for target, ov in channel.overwrites.items():
                if isinstance(target, discord.Member) and ov.view_channel:
                    user = target
                    break
            ticket_data = {
                "user_id": user.id if user else None,
                "type": "Kernel" if channel.category and channel.category.id == ADVANCED_CATEGORY_ID else "Support",
                "created_at": datetime.now().isoformat(),
            }
            if not user:
                await interaction.response.send_message(embed=error_embed("Ticket-Owner nicht gefunden"), ephemeral=True)
                return

        user = await bot.fetch_user(ticket_data["user_id"]) if ticket_data.get("user_id") else None

        await channel.edit(name=f"{channel.name}-closed")
        closed_category = guild.get_channel(CLOSED_CATEGORY_ID)
        if closed_category:
            await channel.edit(category=closed_category)

        overwrite = channel.overwrites_for(guild.default_role)
        overwrite.view_channel = False
        await channel.set_permissions(guild.default_role, overwrite=overwrite)
        if user:
            await channel.set_permissions(user, view_channel=False)

        ticket_channels.pop(channel.id, None)
        save_ticket_data()

        embed = make_embed("Ticket geschlossen", color=ACCENT_RED, thumbnail=False)
        embed.add_field(name="Geschlossen von", value=str(interaction.user), inline=True)
        embed.add_field(name="Erstellt von", value=str(user or "Unbekannt"), inline=True)
        embed.add_field(name="Typ", value=ticket_data["type"], inline=True)
        embed.set_footer(text=f"{FOOTER_TEXT} Support")
        await channel.send(embed=embed)
        await send_ticket_log(f"**Ticket closed**\n> By: {interaction.user}\n> Channel: {channel.mention}\n> Type: {ticket_data['type']}")

        delete_view = discord.ui.View(timeout=None)
        delete_view.add_item(discord.ui.Button(label="Delete Ticket", style=discord.ButtonStyle.danger, custom_id="delete_ticket_closed"))
        await channel.send(view=delete_view)


class DeleteTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.danger, custom_id="delete_ticket_closed")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_ticket_log(f"**Ticket deleted**\n> By: {interaction.user}\n> Channel: {interaction.channel.name}")
        try:
            await interaction.channel.delete()
        except Exception:
            pass


@bot.command()
@commands.has_permissions(administrator=True)
async def ticket(ctx):
    if ctx.channel.id != TICKET_CHANNEL_ID:
        await ctx.send(embed=error_embed("Falscher Channel"), delete_after=5)
        return
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    banner = discord.File(TICKET_BANNER_FILE, filename="ticket_banner.png") if os.path.isfile(TICKET_BANNER_FILE) else None
    kwargs = {"file": banner} if banner else {}
    if HAS_COMPONENTS_V2:
        await ctx.send(view=TicketPanel(), **kwargs)
    else:
        await ctx.send(embed=build_ticket_panel_embed(), view=TicketView(), **kwargs)


# ══════════════════════════════════════════════════════════════
#  Periodic Embed Posts  –  DRY start + loop
# ══════════════════════════════════════════════════════════════

async def _post_embed(channel_id, guild_id, title_filter, build_fn, view=None):
    """Generische Funktion: altes Embed löschen, neues posten."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    # Embed im Hintergrund bauen (DB + API-Check blockieren sonst den ganzen Bot)
    result = await asyncio.to_thread(build_fn)
    await channel.purge(check=lambda m: m.embeds and m.embeds[0].title and title_filter in m.embeds[0].title, limit=5)
    if isinstance(result, list):
        for e in result:
            await channel.send(embed=e)
    else:
        kwargs = {"embed": result}
        if view:
            kwargs["view"] = view
        await channel.send(**kwargs)


async def _embed_loop(channel_id, guild_id, title_filter, build_fn, view=None, interval=600):
    """Generische Loop: alle `interval` Sekunden Embed aktualisieren."""
    while True:
        await asyncio.sleep(interval)
        try:
            await _post_embed(channel_id, guild_id, title_filter, build_fn, view)
        except asyncio.CancelledError:
            raise
        except BaseException as e:      # Loop darf nie sterben
            print(f"[LOOP] {title_filter}: {type(e).__name__}: {e}")
            await asyncio.sleep(10)


_started = False


# ══════════════════════════════════════════════════════════════
#  Bot Events
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global _started
    print(f"[BOT] Online als {bot.user} in {len(bot.guilds)} Guild(s)")

    # on_ready kommt nach jedem Reconnect erneut -> Setup nur EINMAL,
    # sonst doppelte Loops + API-Server-Neustart auf belegtem Port
    if _started:
        print("[BOT] Reconnect – Loops laufen weiter")
        return
    _started = True

    await send_bot_log("Bot gestartet", f"Online als `{bot.user}`")

    load_ticket_data()

    # Persistent Views registrieren
    for view_cls in (AdminMenuView, UserMenuView, UserCheckView, WhitelistMenuView, TicketView, TicketButtons, DeleteTicketView):
        bot.add_view(view_cls())
    if HAS_COMPONENTS_V2:
        bot.add_view(TicketPanel())

    start_api_server()
    print("[API] Server gestartet auf Port 5000")

    # Initiale Embeds posten – ein Fehler stoppt nicht mehr den Rest (vorher starteten dann keine Loops)
    for args in (
        (PURGE_CHANNEL_ID, GUILD_ID, "Key Verwaltung", build_admin_menu_embed, AdminMenuView()),
        (WHITELIST_CHANNEL_ID, GUILD_ID, "Whitelist Verwaltung", build_whitelist_menu_embed, WhitelistMenuView()),
        (USER_CHECK_CHANNEL_ID, GUILD_ID, "User Prüfen", build_user_check_embed, UserCheckView()),
        (KEYS_OVERVIEW_CHANNEL_ID, GUILD_ID, "Key Übersicht", build_keys_overview_embeds),
        (BOT_STATUS_CHANNEL_ID, GUILD_ID, "RAYX Status", build_bot_status_embed),
    ):
        try:
            await _post_embed(*args)
        except Exception as e:
            print(f"[START] {args[2]}: {type(e).__name__}: {e}")

    # Periodische Loops starten
    bot.loop.create_task(_embed_loop(PURGE_CHANNEL_ID, GUILD_ID, "Key Verwaltung", build_admin_menu_embed, AdminMenuView()))
    bot.loop.create_task(_embed_loop(WHITELIST_CHANNEL_ID, GUILD_ID, "Whitelist Verwaltung", build_whitelist_menu_embed, WhitelistMenuView()))
    bot.loop.create_task(_embed_loop(KEYS_OVERVIEW_CHANNEL_ID, GUILD_ID, "Key Übersicht", build_keys_overview_embeds))
    bot.loop.create_task(_embed_loop(BOT_STATUS_CHANNEL_ID, GUILD_ID, "RAYX Status", build_bot_status_embed))

    # Auto-Purge
    async def purge_loop():
        while True:
            await asyncio.sleep(600)
            try:
                guild = bot.get_guild(GUILD_ID)
                if guild:
                    ch = guild.get_channel(PURGE_CHANNEL_ID)
                    if ch:
                        deleted = await ch.purge(limit=100)
                        if deleted:
                            print(f"[PURGE] {len(deleted)} Nachrichten gelöscht")
            except Exception as e:
                print(f"[PURGE] Fehler: {e}")

    bot.loop.create_task(purge_loop())


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id in ticket_messages:
        ticket_messages[message.channel.id].append({
            "user": message.author.name,
            "content": message.content,
            "timestamp": datetime.now()
        })
    await bot.process_commands(message)


# ══════════════════════════════════════════════════════════════
#  NEU: Server-Features (Server-Logging, Ankündigungs-System, /send)
#  → komplett in server_features.py, bestehender Code bleibt unverändert
# ══════════════════════════════════════════════════════════════

try:
    from server_features import install_server_features
    install_server_features(bot)
except Exception as _sf_err:
    print(f"[SERVER-FEATURES] konnte nicht geladen werden: {_sf_err}")


# ══════════════════════════════════════════════════════════════
#  Start
# ══════════════════════════════════════════════════════════════

_TOKEN = (os.environ.get("DISCORD_TOKEN") or "").strip()

if not _TOKEN:
    print("=" * 50)
    print("FEHLER: Kein DISCORD_TOKEN gesetzt.")
    print("Starte den Bot über start.bat.")
    print("=" * 50)
    sys.exit(1)

if not (50 <= len(_TOKEN) <= 100) or _TOKEN.count(".") < 2:
    print("=" * 50)
    print(f"FEHLER: DISCORD_TOKEN ungültig (Länge {len(_TOKEN)}).")
    print("Lösche .discord_token und starte start.bat erneut.")
    print("=" * 50)
    sys.exit(1)

bot.run(_TOKEN)
