import discord
from discord.ext import commands
import uuid
from datetime import datetime, timedelta
import json
import os
import sys
import subprocess
import ctypes
import asyncio
import threading
import urllib.request
import base64
import sqlite3
from flask import Flask, jsonify, request, render_template

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

PURGE_CHANNEL_ID = 1537561862361849989
WHITELIST_CHANNEL_ID = 1538336311365214218
LOG_CHANNEL_ID = 1538307572908556442
BOT_LOG_CHANNEL_ID = 1538307572908556442
LOADER_LOG_CHANNEL_ID = 1538307572908556442
GUILD_ID = 1537561860163768412
MASTER_ID = "1027571297514967140"

# === TICKET SYSTEM CONFIG ===
TICKET_GUILD_ID = 1472228342118879370
TICKET_CHANNEL_ID = 1472321913828147421
TICKET_LOG_CHANNEL_ID = 1487068508935426238
TICKET_EMBED_COLOR = 0x00d4ff
TICKET_LOGO_URL = "https://media.discordapp.net/attachments/1492346393933906024/1538718605712035910/85018bcb-4d6d-41f2-bd97-5d6586fe4397.png?ex=6a83b2df&is=6a82615f&hm=72fb199f0783755049d47aa62330ccb848c431e10e031919ad4be23d7d2ac63e&=&format=webp&quality=lossless&width=512&height=205"
ADVANCED_CATEGORY_ID = 1472321807603335208
SUPPORT_CATEGORY_ID = 1487794310022959205
ticket_channels = {}
ticket_messages = {}

GIST_ID = "1d00ee128d1f4d294ec95e3e160ec195"
GIST_TOKEN = "gho_" + "WUVZeTTwvNTiSZ0FhYR9dEhGoYzjpc3qj0Um"
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.db")

def check_self_update():
    try:
        url = "https://raw.githubusercontent.com/JamalxSantn/xyz/master/discord_key_bot.py"
        req = urllib.request.Request(url, headers={"User-Agent": "PeroxideBot"})
        new_code = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        current_file = os.path.abspath(__file__)
        with open(current_file, "r", encoding="utf-8", newline="") as f:
            current = f.read()
        if new_code.replace("\r\n", "\n") == current.replace("\r\n", "\n"):
            print("Self-Update: Kein Update gefunden.")
            return
        compile(new_code, current_file, "exec")
        with open(current_file, "w", encoding="utf-8", newline="") as f:
            f.write(new_code)
        print("Self-Update: Neue Version gefunden, Bot startet neu...")
        subprocess.Popen([sys.executable, current_file])
        sys.exit(0)
    except SyntaxError as e:
        print(f"Self-Update übersprungen (Syntaxfehler im Update): {e}")
    except Exception as e:
        print(f"Self-Update error: {e}")

check_self_update()

def sync_db_from_gist():
    try:
        token = GIST_TOKEN
        req = urllib.request.Request(f"https://api.github.com/gists/{GIST_ID}")
        req.add_header("Authorization", f"token {token}")
        req.add_header("User-Agent", "PeroxideBot")
        resp = urllib.request.urlopen(req, timeout=10)
        gist = json.loads(resp.read().decode())
        content = gist["files"]["bot_data.json"]["content"].strip()
        if content:
            with open(DATABASE, "wb") as f:
                f.write(base64.b64decode(content))
            print("DB from Gist geladen")
        else:
            print("Gist leer, starte mit frischer DB")
    except Exception as e:
        print(f"sync_db_from_gist error: {e}, starte mit frischer DB")

def sync_db_to_gist():
    try:
        token = GIST_TOKEN
        with open(DATABASE, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        body = json.dumps({"files": {"bot_data.json": {"content": encoded}}}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            data=body,
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "User-Agent": "PeroxideBot"
            },
            method="PATCH"
        )
        urllib.request.urlopen(req, timeout=10)
        print("DB to Gist gesynct")
    except Exception as e:
        print(f"sync_db_to_gist error: {e}")

def init_db():
    sync_db_from_gist()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        hwid TEXT,
        discord_id TEXT,
        created_at TEXT,
        expires_at TEXT,
        duration_type TEXT,
        duration_value INTEGER,
        used INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS whitelist (
        discord_id TEXT PRIMARY KEY,
        added_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS masters (
        discord_id TEXT PRIMARY KEY,
        added_at TEXT
    )""")
    c.execute("SELECT COUNT(*) FROM whitelist")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO whitelist (discord_id, added_at) VALUES (?, ?)", (MASTER_ID, datetime.now().isoformat()))
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (discord_id, added_at) VALUES (?, ?)", (MASTER_ID, datetime.now().isoformat()))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    sync_db_to_gist()

def is_master(discord_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM masters WHERE discord_id = ?", (str(discord_id),))
    result = c.fetchone()
    conn.close()
    return result is not None

def is_whitelisted(discord_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM whitelist WHERE discord_id = ?", (str(discord_id),))
    result = c.fetchone()
    conn.close()
    return result is not None

init_db()

app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    return render_template('index.html')

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
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
        send_key_log_sync("Key Login Fehlgeschlagen", f"Key: `{password}`\nHWID: {hwid}\nDiscord ID: {username}\nGrund: Ungültiger Key", 0xff0000)
        return jsonify({'success': False, 'error': 'Invalid key'}), 401
    
    _, stored_hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = result
    
    if datetime.now() > datetime.fromisoformat(expires_at):
        conn.close()
        send_key_log_sync("Key Login Fehlgeschlagen", f"Key: `{password}`\nHWID: {hwid}\nDiscord ID: {username}\nGrund: Abgelaufen", 0xff0000)
        return jsonify({'success': False, 'error': 'Key expired'}), 403
    
    if used:
        if stored_hwid and stored_hwid != hwid:
            conn.close()
            send_key_log_sync("Key Login Fehlgeschlagen", f"Key: `{password}`\nHWID: {hwid} (falsch)\nErwartete HWID: {stored_hwid}\nDiscord ID: {username}\nGrund: HWID Mismatch", 0xff0000)
            return jsonify({'success': False, 'error': 'HWID mismatch'}), 403
        send_key_log_sync("Key Login (Loader)", f"Key: `{password}`\nHWID: {hwid}\nDiscord ID: {username}", 0x00bfff)
    else:
        c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?",
                  (hwid, username, password))
        conn.commit()
        sync_db_to_gist()
        send_key_log_sync("Key Eingelöst (Loader)", f"Key: `{password}`\nHWID: {hwid}\nDiscord ID: {username}", 0x00ff00)
        sync_db_to_gist()
    
    conn.close()
    
    expiry_str = time_remaining(expires_at)
    
    return jsonify({
        'success': True,
        'products': [{
            'id': 1,
            'game': 'FiveM',
            'version': duration_type,
            'status_id': 0,
            'expiry': expiry_str
        }]
    }), 200

@app.route('/api/validate-subscription', methods=['POST', 'OPTIONS'])
def validate_subscription():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    data = request.get_json()
    username = data.get('username', '').strip()
    product_id = data.get('product_id', 1)
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE discord_id = ?", (username,))
    results = c.fetchall()
    conn.close()
    
    for result in results:
        _, _, _, _, expires_at, _, _, _ = result
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
    
    _, stored_hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = result
    
    if datetime.now() > datetime.fromisoformat(expires_at):
        return jsonify({'success': False, 'error': 'Key expired'}), 403
    
    if used and stored_hwid and stored_hwid != hwid:
        return jsonify({'success': False, 'error': 'Key already used on different HWID'}), 403
    
    return jsonify({
        'success': True,
        'key': key,
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
        req.add_header("User-Agent", "PeroxideBot")
        resp = urllib.request.urlopen(req, timeout=5)
        user_data = json.loads(resp.read().decode())
        
        username = user_data.get("global_name") or user_data.get("username", "Unknown")
        avatar_hash = user_data.get("avatar", "")
        
        avatar_url = ""
        if avatar_hash:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}"
        
        return jsonify({
            'success': True,
            'username': username,
            'avatar_url': avatar_url
        })
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return jsonify({'success': False, 'error': 'Rate limited'}), 429
        return jsonify({'success': False, 'error': f'Discord API error {e.code}'}), 500
    except Exception as e:
        print(f"api_user_info error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def send_key_log_sync(action, details, color=0x00ff00):
    try:
        token = os.environ.get("DISCORD_TOKEN", "")
        body = json.dumps({
            "embeds": [{
                "title": action,
                "description": details,
                "color": color,
                "timestamp": datetime.utcnow().isoformat()
            }]
        }).encode()
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{LOADER_LOG_CHANNEL_ID}/messages",
            data=body,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot/1.0"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"send_key_log_sync error: {e}")

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
    
    c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?",
              (hwid, discord_id, key))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    send_key_log_sync("Key Eingelost (Loader)", f"Key: `{key}`\nHWID: {hwid}\nDiscord ID: {discord_id}", 0x00ff00)
    
    return jsonify({'success': True, 'message': 'Key registered successfully'}), 200

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def start_api_server():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

def get_expiry(duration_type, duration_value, created_at=None):
    if created_at is None:
        created_at = datetime.now()
    elif isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    
    durations = {
        "minute": timedelta(minutes=duration_value),
        "hour": timedelta(hours=duration_value),
        "day": timedelta(days=duration_value),
        "week": timedelta(weeks=duration_value),
        "month": timedelta(days=duration_value * 30),
        "year": timedelta(days=duration_value * 365)
    }
    return (created_at + durations.get(duration_type, timedelta(days=duration_value))).isoformat()

def get_hwid_from_key(key):
    return key.split("-")[0] if "-" in key else key[:8]

def time_remaining(expires_at):
    expiry = datetime.fromisoformat(expires_at)
    remaining = expiry - datetime.now()
    if remaining.total_seconds() <= 0:
        return "Abgelaufen"
    
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes = remainder // 60
    
    parts = []
    if days > 0:
        parts.append(f"{days} Tag{'en' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} Stunde{'n' if hours != 1 else ''}")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} Minute{'n' if minutes != 1 else ''}")
    
    return ", ".join(parts) if parts else "Weniger als 1 Minute"

async def send_log(action, user, details, color=0x3498db):
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(title=f"{action}", color=color, timestamp=datetime.now())
                embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
                embed.add_field(name="Details", value=details, inline=False)
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Log error: {e}")

async def send_bot_log(action, details, color=0x000000):
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            bot_log_channel = guild.get_channel(BOT_LOG_CHANNEL_ID)
            if bot_log_channel:
                embed = discord.Embed(title=f"{action}", color=color, timestamp=datetime.now())
                embed.add_field(name="Details", value=details, inline=False)
                await bot_log_channel.send(embed=embed)
    except Exception as e:
        print(f"Bot Log error: {e}")

async def purge_channel_task():
    while True:
        await asyncio.sleep(600)
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                channel = guild.get_channel(PURGE_CHANNEL_ID)
                if channel:
                    deleted = await channel.purge(limit=100)
                    print(f"Auto-Purge: {len(deleted)} Nachrichten gelöscht")
        except Exception as e:
            print(f"Purge error: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def createkey(ctx, duration_value: int, duration_type: str):
    """Erstellt einen neuen Key: !createkey 30 day"""
    valid_types = ["minute", "hour", "day", "week", "month", "year"]
    if duration_type.lower() not in valid_types:
        await ctx.send(f"Ungültiger Zeittyp. Gültige Typen: {', '.join(valid_types)}")
        return
    
    key_id = str(uuid.uuid4())[:8].upper()
    key = f"PRT-{key_id}"
    created_at = datetime.now().isoformat()
    expires_at = get_expiry(duration_type.lower(), duration_value, datetime.now())
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""INSERT INTO keys (key, created_at, expires_at, duration_type, duration_value) 
                 VALUES (?, ?, ?, ?, ?)""",
              (key, created_at, expires_at, duration_type.lower(), duration_value))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    embed = discord.Embed(title="Key Erstellt", color=0x00ff00)
    embed.add_field(name="Key", value=f"`{key}`", inline=False)
    embed.add_field(name="Duration", value=f"{duration_value} {duration_type}(s)", inline=True)
    embed.add_field(name="Time", value=time_remaining(expires_at), inline=True)
    await ctx.send(embed=embed)
    await send_log("Key Erstellt", ctx.author, f"Key: `{key}`\nDuration: {duration_value} {duration_type}", 0x00ff00)

@bot.command()
@commands.has_permissions(administrator=True)
async def deletekey(ctx, *, key: str):
    """Löscht einen Key: !deletekey XXXX-XXXX-XXXX"""
    key = key.strip().upper()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    if key == "all":
        c.execute("SELECT COUNT(*) FROM keys")
        count = c.fetchone()[0]
        if count == 0:
            await ctx.send("Keine Keys zum Löschen vorhanden.")
            conn.close()
            return
        c.execute("DELETE FROM keys")
        conn.commit()
        sync_db_to_gist()
        conn.close()
        await ctx.send(f"✅ Alle {count} Keys wurden gelöscht!")
        await send_log("Alle Keys Gelöscht", ctx.author, f"{count} Keys wurden gelöscht!", 0xff0000)
        return
    
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!")
        conn.close()
        return
    
    _, hwid, discord_id, _, _, _, _, used = result
    hwid_info = f" HWID: {hwid}" if hwid else ""
    
    c.execute("DELETE FROM keys WHERE key = ?", (key,))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    await ctx.send(f"✅ Key `{key}` wurde gelöscht!")
    await send_log("Key Gelöscht", ctx.author, f"Key: `{key}`{hwid_info}", 0xff0000)

@bot.command()
@commands.has_permissions(administrator=True)
async def listkeys(ctx):
    """Listet alle Keys auf: !listkeys"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys ORDER BY created_at DESC")
    results = c.fetchall()
    conn.close()
    
    if not results:
        await ctx.send("Keine Keys vorhanden.")
        return
    
    embed = discord.Embed(title="Alle Keys", color=0x3498db)
    
    for row in results:
        key, hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = row
        status = "✅ Benutzt" if used else "⏳ Unbenutzt"
        remaining = time_remaining(expires_at)
        
        discord_info = f"<@{discord_id}> ({discord_id})" if discord_id else "N/A"
        
        embed.add_field(
            name=f"{key} [{status}]",
            value=f"Time: {remaining}\nDiscord: {discord_info}",
            inline=False
        )
    
    await ctx.send(embed=embed)

CHECK_CHANNEL_ID = 1538307572908556442

@bot.command()
async def check(ctx, discord_id: str = None):
    """Zeigt Key-Infos zu einer Discord ID: !check <discord_id>"""
    if not discord_id:
        await ctx.send("❌ Nutzung: `!check <discord_id>`")
        return
    channel = bot.get_channel(CHECK_CHANNEL_ID)
    if not channel:
        await ctx.send("❌ Check-Channel nicht gefunden")
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE discord_id = ?", (discord_id.strip(),))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await channel.send(f"❌ Keine Keys gefunden für Discord ID `{discord_id}`")
        return
    try:
        user = await bot.fetch_user(int(discord_id))
        discord_name = str(user)
    except:
        discord_name = "Unbekannt"
    for key, hwid, stored_discord_id, created_at, expires_at, duration_type, duration_value, used in rows:
        try:
            dt = datetime.fromisoformat(created_at)
            created_readable = dt.strftime("%d.%m.%Y um %H:%M:%S")
        except:
            created_readable = created_at
        embed = discord.Embed(title="User Informationen", color=0xffffff)
        embed.set_thumbnail(url="https://raw.githubusercontent.com/JamalxSantn/xyz/main/logo.png")
        embed.add_field(name="Discord User", value=discord_name, inline=False)
        embed.add_field(name="Discord ID", value=discord_id, inline=True)
        embed.add_field(name="Key", value=f"`{key}`", inline=True)
        embed.add_field(name="Erstellt am", value=created_readable, inline=False)
        embed.add_field(name="HWID", value=f"`{hwid or 'Keine'}`", inline=True)
        embed.add_field(name="Status", value="✅ Eingelöst" if used else "⏳ Unbenutzt", inline=True)
        await channel.send(embed=embed)

@bot.command()
async def addtime(ctx, key: str, amount: int, time_type: str):
    """Fügt Zeit zu einem Key hinzu: !addtime XXXX-XXXX-XXXX 30 day"""
    key = key.strip()
    valid_types = ["minute", "hour", "day", "week", "month", "year"]
    if time_type.lower() not in valid_types:
        await ctx.send(f"Ungültiger Zeittyp. Gültige Typen: {', '.join(valid_types)}")
        return
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!")
        conn.close()
        return
    
    current_expiry = datetime.fromisoformat(result[0])
    new_expiry = get_expiry(time_type.lower(), amount, current_expiry)
    
    c.execute("UPDATE keys SET expires_at = ? WHERE key = ?", (new_expiry, key))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    await ctx.send(f"✅ {amount} {time_type}(s) zu Key `{key}` hinzugefügt! Neues Ablaufdatum: {time_remaining(new_expiry)}")
    await send_log("Zeit Hinzugefügt", ctx.author, f"Key: `{key}`\n+{amount} {time_type}", 0x3498db)

@bot.command()
@commands.has_permissions(administrator=True)
async def restart(ctx):
    """Startet den Bot neu: !restart"""
    await ctx.send("🔄 Bot wird neu gestartet...")
    await ctx.send("Der Bot ist kurz offline. Bitte warte 5 Sekunden.")
    subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    await bot.close()

@bot.command()
@commands.has_permissions(administrator=True)
async def clear(ctx):
    """Löscht alle Nachrichten und macht Channel read-only für User"""
    await ctx.channel.purge(limit=None)
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False, add_reactions=False)
    await ctx.send("✅ Channel geleert! Nur noch der Bot kann schreiben.", delete_after=5)

@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    """Entsperrt den Channel wieder für alle User"""
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None, add_reactions=None)
    await ctx.send("✅ Channel entsperrt! Alle können wieder schreiben.", delete_after=5)

class KeyModal(discord.ui.Modal):
    def __init__(self, action):
        super().__init__(title=action)
        self.action = action
        if action == "Key erstellen":
            self.duration_type = discord.ui.TextInput(label="Zeittyp", placeholder="day/month/lifetime")
            self.duration_value = discord.ui.TextInput(label="Anzahl (Tage/Monate)", placeholder="z.B. 30 oder 1")
            self.add_item(self.duration_type)
            self.add_item(self.duration_value)
        elif action == "Key einlösen" or action == "Key prüfen" or action == "Key löschen" or action == "Zeit hinzufügen" or action == "HWID Reset":
            self.key_input = discord.ui.TextInput(label="Key", placeholder="XXXX-XXXX-XXXX")
            self.add_item(self.key_input)
            if action == "Zeit hinzufügen":
                self.amount = discord.ui.TextInput(label="Anzahl", placeholder="z.B. 7")
                self.time_type = discord.ui.TextInput(label="Zeittyp", placeholder="day/month")
                self.add_item(self.amount)
                self.add_item(self.time_type)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        if self.action == "Key erstellen":
            try:
                amount = int(self.duration_value.value)
                time_type = self.duration_type.value.lower()
                valid_types = ["day", "month", "lifetime"]
                if time_type not in valid_types:
                    await interaction.response.send_message(f"❌ Ungültiger Zeittyp. Gültige: {', '.join(valid_types)}", ephemeral=True)
                    conn.close()
                    return
                
                key_id = str(uuid.uuid4())[:8].upper()
                key = f"RAYX-{key_id}"
                created_at = datetime.now().isoformat()
                
                if time_type == "lifetime":
                    expires_at = "9999-12-31T23:59:59"
                else:
                    expires_at = get_expiry(time_type, amount, datetime.now())
                
                c.execute("""INSERT INTO keys (key, created_at, expires_at, duration_type, duration_value) VALUES (?, ?, ?, ?, ?)""",
                         (key, created_at, expires_at, time_type, amount))
                conn.commit()
                sync_db_to_gist()
                
                embed = discord.Embed(title="✅ Key Erstellt", color=0x000000)
                embed.add_field(name="Key", value=f"`{key}`", inline=False)
                embed.add_field(name="Zeit", value=f"{amount} {time_type}" if time_type != "lifetime" else "Lifetime", inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log("Key Erstellt", interaction.user, f"Key: `{key}`\nZeit: {amount} {time_type}" if time_type != "lifetime" else "Lifetime", 0x00ff00)
            except ValueError:
                await interaction.response.send_message("❌ Ungültige Zahl!", ephemeral=True)
        
        elif self.action == "Key einlösen":
            key = self.key_input.value.strip()
            c.execute("SELECT * FROM keys WHERE key = ?", (key,))
            result = c.fetchone()
            
            if not result:
                await interaction.response.send_message("❌ Key existiert nicht!", ephemeral=True)
                conn.close()
                return
            
            _, _, _, _, expires_at, _, _, used = result
            
            if used:
                await interaction.response.send_message("❌ Key wurde bereits eingelöst!", ephemeral=True)
                conn.close()
                return
            
            if datetime.now() > datetime.fromisoformat(expires_at):
                await interaction.response.send_message("❌ Key ist abgelaufen!", ephemeral=True)
                conn.close()
                return
            
            c.execute("UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?",
                     (str(interaction.user.id), str(interaction.user.id), key))
            conn.commit()
            sync_db_to_gist()
            
            embed = discord.Embed(title="✅ Key Eingelöst", color=0x00ff00)
            embed.add_field(name="Discord", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            embed.add_field(name="Time", value=time_remaining(expires_at), inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await send_log("Key Eingelöst", interaction.user, f"Key: `{key}`", 0x00ff00)
        
        elif self.action == "Key prüfen":
            key = self.key_input.value.strip()
            c.execute("SELECT * FROM keys WHERE key = ?", (key,))
            result = c.fetchone()
            conn.close()
            
            if not result:
                await interaction.response.send_message("❌ Key existiert nicht!", ephemeral=True)
                return
            
            _, _, discord_id, _, expires_at, _, _, used = result
            
            status = "✅ Eingelöst" if used else "⏳ Unbenutzt"
            
            embed = discord.Embed(title=f"Key Info", color=0x3498db)
            embed.add_field(name="Key", value=f"`{key}`", inline=False)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Time", value=time_remaining(expires_at), inline=True)
            if discord_id:
                embed.add_field(name="Discord", value=f"<@{discord_id}>", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        elif self.action == "Key löschen":
            key = self.key_input.value.strip().upper()
            c.execute("SELECT * FROM keys WHERE key = ?", (key,))
            result = c.fetchone()
            
            if not result:
                await interaction.response.send_message("❌ Key existiert nicht!", ephemeral=True)
                conn.close()
                return
            
            _, hwid, _, _, _, _, _, used = result
            hwid_info = f" HWID: {hwid}" if hwid else ""
            
            c.execute("DELETE FROM keys WHERE key = ?", (key,))
            conn.commit()
            sync_db_to_gist()
            conn.close()
            await interaction.response.send_message(f"✅ Key `{key}` wurde gelöscht!", ephemeral=True)
            await send_log("Key Gelöscht", interaction.user, f"Key: `{key}`", 0xff0000)
        
        elif self.action == "Zeit hinzufügen":
            key = self.key_input.value.strip()
            try:
                amount = int(self.amount.value)
                time_type = self.time_type.value.lower()
                valid_types = ["minute", "hour", "day", "week", "month", "year"]
                if time_type not in valid_types:
                    await interaction.response.send_message(f"❌ Ungültiger Zeittyp.", ephemeral=True)
                    conn.close()
                    return
                
                c.execute("SELECT expires_at FROM keys WHERE key = ?", (key,))
                result = c.fetchone()
                
                if not result:
                    await interaction.response.send_message("❌ Key existiert nicht!", ephemeral=True)
                    conn.close()
                    return
                
                current_expiry = datetime.fromisoformat(result[0])
                new_expiry = get_expiry(time_type, amount, current_expiry)
                
                c.execute("UPDATE keys SET expires_at = ? WHERE key = ?", (new_expiry, key))
                conn.commit()
                sync_db_to_gist()
                conn.close()
                
                await interaction.response.send_message(f"✅ {amount} {time_type} zu Key hinzugefügt! Neue Time: {time_remaining(new_expiry)}", ephemeral=True)
                await send_log("Zeit Hinzugefügt", interaction.user, f"Key: `{key}`\n+{amount} {time_type}", 0x3498db)
            except ValueError:
                await interaction.response.send_message("❌ Ungültige Zahl!", ephemeral=True)
        
        elif self.action == "HWID Reset":
            key = self.key_input.value.strip()
            c.execute("SELECT * FROM keys WHERE key = ?", (key,))
            result = c.fetchone()
            
            if not result:
                await interaction.response.send_message("❌ Key existiert nicht!", ephemeral=True)
                conn.close()
                return
            
            c.execute("UPDATE keys SET hwid = NULL, used = 0, discord_id = NULL WHERE key = ?", (key,))
            conn.commit()
            sync_db_to_gist()
            conn.close()
            
            await interaction.response.send_message(f"✅ HWID von Key `{key}` wurde zurückgesetzt! Er kann jetzt erneut eingelöst werden.", ephemeral=True)
            await send_log("HWID Reset", interaction.user, f"Key: `{key}`", 0xf39c12)
        
        conn.close()

class AdminMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Erstellen", style=discord.ButtonStyle.grey, custom_id="admin_create", emoji="📦")
    async def create_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key erstellen"))

    @discord.ui.button(label="Prüfen", style=discord.ButtonStyle.grey, custom_id="admin_check", emoji="🔍")
    async def check_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key prüfen"))

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.grey, custom_id="admin_delete", emoji="🗑️")
    async def delete_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key löschen"))

    @discord.ui.button(label="Zeit+", style=discord.ButtonStyle.grey, custom_id="admin_addtime", emoji="⏰")
    async def add_time_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Zeit hinzufügen"))

    @discord.ui.button(label="HWID", style=discord.ButtonStyle.grey, custom_id="admin_hwidreset", emoji="🔄")
    async def hwid_reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("HWID Reset"))

    @discord.ui.button(label="Keys", style=discord.ButtonStyle.grey, custom_id="admin_list", emoji="📋")
    async def list_keys_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT * FROM keys ORDER BY created_at DESC")
        results = c.fetchall()
        conn.close()
        
        if not results:
            await interaction.response.send_message("Keine Keys vorhanden.", ephemeral=True)
            return
        
        embed = discord.Embed(title="Alle Keys", color=0x000000)
        for row in results:
            key, _, discord_id, _, expires_at, _, _, used = row
            status = "Benutzt" if used else "Unbenutzt"
            discord_info = f"<@{discord_id}>" if discord_id else "N/A"
            embed.add_field(name=f"{key}", value=f"Status: {status}\nTime: {time_remaining(expires_at)}\nDiscord: {discord_info}", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.grey, custom_id="admin_restart", emoji="🔁")
    async def restart_bot_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Bot wird neu gestartet...", ephemeral=True)
        await send_bot_log("Bot Neustart", f"User: {interaction.user}\nBot wird neu gestartet")
        subprocess.Popen([sys.executable, os.path.abspath(__file__)])
        await bot.close()

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.grey, custom_id="admin_clear", emoji="🧹")
    async def clear_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.purge(limit=None)
        await interaction.response.send_message("Channel geleert!", delete_after=5, ephemeral=True)
        await send_bot_log("Channel Geleert", f"User: {interaction.user}\nChannel: {interaction.channel.name}")

    @discord.ui.button(label="Unlock", style=discord.ButtonStyle.grey, custom_id="admin_unlock", emoji="🔓")
    async def unlock_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, add_reactions=None)
        await interaction.response.send_message("Channel entsperrt!", delete_after=5, ephemeral=True)
        await send_bot_log("Channel Entsperrt", f"User: {interaction.user}\nChannel: {interaction.channel.name}")

class UserMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Einlösen", style=discord.ButtonStyle.grey, custom_id="user_redeem", emoji="🎫")
    async def redeem_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key einlösen"))

    @discord.ui.button(label="Prüfen", style=discord.ButtonStyle.grey, custom_id="user_check", emoji="🔍")
    async def check_key_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        await interaction.response.send_modal(KeyModal("Key prüfen"))

LOAD_CHANNEL_ID = 1538307572908556442
LOAD_URL = os.environ.get("LOAD_URL", "http://192.168.178.72:5000")
CHEAT_EXE = os.environ.get("CHEAT_EXE", "")

@bot.command()
async def load(ctx):
    """Öffnet das Cheat Menü"""
    try:
        print(f"Load command from {ctx.author} in channel: {ctx.channel.id}")
        print(f"URL: {LOAD_URL}")
        
        try:
            if os.path.exists(CHEAT_EXE):
                os.system(f'cmd /c start "" "{CHEAT_EXE}"')
                print(f"Cheat gestartet: {CHEAT_EXE}")
            else:
                print(f"FEHLER: Exe nicht gefunden: {CHEAT_EXE}")
        except Exception as exe_err:
            print(f"Fehler beim Starten der Exe: {exe_err}")
        
        await ctx.message.delete()
        
        embed = discord.Embed(
            title="📱 Cheat Menü",
            description="Klicke auf den Button unten um das Menü zu öffnen!",
            color=0xff0000
        )
        embed.add_field(name="🌐 Webseite", value=f"[Hier klicken]({LOAD_URL})", inline=False)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Menü öffnen", url=LOAD_URL, style=discord.ButtonStyle.link))
        
        await ctx.send(embed=embed, view=view, delete_after=15, ephemeral=True)
    except Exception as e:
        print(f"Error in load command: {e}")
        await ctx.send(f"Error: {e}", delete_after=10, ephemeral=True)

@bot.command()
async def menu(ctx):
    """Zeigt das Key-Verwaltungsmenü"""
    await ctx.message.delete()
    if not is_whitelisted(ctx.author.id):
        embed = discord.Embed(
            title="❌ Kein Zugriff",
            description="Du bist nicht in der Whitelist.",
            color=0xff0000
        )
        await ctx.send(embed=embed, ephemeral=True)
        return
    
    is_admin = ctx.author.guild_permissions.administrator
    
    if is_admin:
        embed = discord.Embed(
            title="🔐 Key Verwaltung",
            color=0x000000
        )
        embed.add_field(name="📦 Key erstellen", value="> Erstelle einen neuen Key", inline=True)
        embed.add_field(name="🎫 Key einlösen", value="> Löse einen Key ein", inline=True)
        embed.add_field(name="🔍 Key prüfen", value="> Prüfe einen Key", inline=True)
        embed.add_field(name="🗑️ Key löschen", value="> Lösche einen Key", inline=True)
        embed.add_field(name="⏰ Zeit hinzufügen", value="> Füge Zeit zu einem Key hinzu", inline=True)
        embed.add_field(name="📋 Alle Keys", value="> Zeige alle Keys", inline=True)
        embed.add_field(name="🔄 HWID Reset", value="> Setzt HWID zurück", inline=True)
        embed.add_field(name="🔁 Neustarten", value="> Bot neu starten", inline=True)
        embed.add_field(name="🧹 Clear Channel", value="> Löscht Nachrichten", inline=True)
        embed.add_field(name="🔓 Unlock Channel", value="> Entsperrt Channel", inline=True)
        embed.set_footer(text="F I STEINKE C++ MEISTER")
        await ctx.send(embed=embed, view=AdminMenuView())
    else:
        embed = discord.Embed(
            title="🔐 Key Verwaltung",
            color=0x000000
        )
        embed.add_field(name="🎫 Key einlösen", value="> Löse einen Key ein", inline=True)
        embed.add_field(name="🔍 Key prüfen", value="> Prüfe einen Key", inline=True)
        embed.set_footer(text="F I STEINKE C++ MEISTER")
        await ctx.send(embed=embed, view=UserMenuView())

@bot.command()
async def hwidreset(ctx, *, key: str):
    """Setzt die HWID eines Keys zurück"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send("❌ Du bist nicht in der Whitelist!", ephemeral=True)
        return
    
    key = key.strip()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!", ephemeral=True)
        conn.close()
        return
    
    c.execute("UPDATE keys SET hwid = NULL, used = 0, discord_id = NULL WHERE key = ?", (key,))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    embed = discord.Embed(
        title="✅ HWID Zurückgesetzt",
        description=f"Key `{key}` wurde zurückgesetzt. Er kann jetzt erneut eingelöst werden.",
        color=0x00ff00
    )
    await ctx.send(embed=embed, ephemeral=True)
    await send_log("HWID Reset", ctx.author, f"Key: `{key}`", 0xf39c12)

@bot.command()
async def addwhitelist(ctx, member: discord.Member):
    """Fügt einen User zur Whitelist hinzu"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send("❌ Du bist nicht in der Whitelist!", ephemeral=True)
        return
    
    if is_whitelisted(member.id):
        await ctx.send(f"❌ {member} ist bereits in der Whitelist!", ephemeral=True)
        return
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT INTO whitelist (discord_id, added_at) VALUES (?, ?)", (str(member.id), datetime.now().isoformat()))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    embed = discord.Embed(
        title="✅ Whitelist aktualisiert",
        description=f"{member.mention} wurde zur Whitelist hinzugefügt.",
        color=0x00ff00
    )
    await ctx.send(embed=embed, ephemeral=True)
    await send_log("Whitelist Hinzugefügt", ctx.author, f"{member} ({member.id}) wurde zur Whitelist hinzugefügt", 0x00ff00)

@bot.command()
async def removewhitelist(ctx, member: discord.Member):
    """Entfernt einen User aus der Whitelist"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send("❌ Du bist nicht in der Whitelist!", ephemeral=True)
        return
    
    if str(member.id) == "1027571297514967140":
        await ctx.send("❌ Du kannst dich nicht selbst entfernen!", ephemeral=True)
        return
    
    if not is_whitelisted(member.id):
        await ctx.send(f"❌ {member} ist nicht in der Whitelist!", ephemeral=True)
        return
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM whitelist WHERE discord_id = ?", (str(member.id),))
    conn.commit()
    sync_db_to_gist()
    conn.close()
    
    embed = discord.Embed(
        title="✅ Whitelist aktualisiert",
        description=f"{member.mention} wurde aus der Whitelist entfernt.",
        color=0xff0000
    )
    await ctx.send(embed=embed, ephemeral=True)
    await send_log("Whitelist Entfernt", ctx.author, f"{member} ({member.id}) wurde aus der Whitelist entfernt", 0xff0000)

@bot.command()
async def listwhitelist(ctx):
    """Listet alle User in der Whitelist auf"""
    if not is_whitelisted(ctx.author.id):
        await ctx.send("❌ Du bist nicht in der Whitelist!", ephemeral=True)
        return
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT discord_id, added_at FROM whitelist ORDER BY added_at DESC")
    results = c.fetchall()
    conn.close()
    
    embed = discord.Embed(
        title="📋 Whitelist",
        color=0x3498db
    )
    
    for row in results:
        user_id, added_at = row
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = "Unbekannt"
        embed.add_field(
            name=f"👤 {username}",
            value=f"ID: `{user_id}`\nHinzugefügt: {added_at[:10]}",
            inline=False
        )
    
    await ctx.send(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot ist online als {bot.user}")
    print(f"Bot ist in {len(bot.guilds)} Guilds")
    for g in bot.guilds:
        print(f"  - Guild: {g.name} (ID: {g.id})")
    
    await send_bot_log("Bot Gestartet", f"Bot ist online als {bot.user}")
    
    bot.add_view(AdminMenuView())
    bot.add_view(UserMenuView())
    bot.add_view(WhitelistMenuView())
    bot.add_view(TicketView())
    bot.add_view(TicketButtons())
    
    start_api_server()
    print("API Server gestartet auf http://0.0.0.0:5000")
    await post_key_embed_start()
    await post_whitelist_embed_start()
    bot.loop.create_task(post_key_embed_loop())
    bot.loop.create_task(post_whitelist_embed_loop())
    bot.loop.create_task(purge_channel_task())

async def post_key_embed_start():
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            channel = guild.get_channel(PURGE_CHANNEL_ID)
            if channel:
                await channel.purge(check=lambda m: m.embeds and m.embeds[0].title and "Key Verwaltung" in m.embeds[0].title)
                
                key_embed = discord.Embed(
                    title="🔐 Key Verwaltung",
                    color=0x000000
                )
                key_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1475174657488322582/1492708596839088180/bypass_logo.png")
                key_embed.add_field(name="📦 Erstellen", value="> Erstelle einen neuen Key", inline=True)
                key_embed.add_field(name="🔍 Prüfen", value="> Prüfe einen Key", inline=True)
                key_embed.add_field(name="🗑️ Löschen", value="> Lösche einen Key", inline=True)
                key_embed.add_field(name="⏰ Zeit+", value="> Füge Zeit hinzu", inline=True)
                key_embed.add_field(name="📋 Keys", value="> Zeige alle Keys", inline=True)
                key_embed.add_field(name="🔄 HWID", value="> Setzt HWID zurück", inline=True)
                key_embed.add_field(name="🔁 Restart", value="> Bot neu starten", inline=True)
                key_embed.add_field(name="🧹 Clear", value="> Löscht Nachrichten", inline=True)
                key_embed.add_field(name="🔓 Unlock", value="> Entsperrt Channel", inline=True)
                key_embed.set_footer(text="F I STEINKE C++ MEISTER")
                await channel.send(embed=key_embed, view=AdminMenuView())
                print("✅ Key Embed mit Menü beim Start gesendet!")
    except Exception as e:
        print(f"Key Embed Start error: {e}")

async def post_key_embed_loop():
    while True:
        await asyncio.sleep(600)
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                channel = guild.get_channel(PURGE_CHANNEL_ID)
                if channel:
                    await asyncio.sleep(2)
                    await channel.purge(check=lambda m: m.embeds and m.embeds[0].title and "Key Verwaltung" in m.embeds[0].title, limit=1)
                    
                    key_embed = discord.Embed(
                        title="🔐 Key Verwaltung",
                        color=0x000000
                    )
                    key_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1475174657488322582/1492708596839088180/bypass_logo.png")
                    key_embed.add_field(name="📦 Erstellen", value="> Erstelle einen neuen Key", inline=True)
                    key_embed.add_field(name="🔍 Prüfen", value="> Prüfe einen Key", inline=True)
                    key_embed.add_field(name="🗑️ Löschen", value="> Lösche einen Key", inline=True)
                    key_embed.add_field(name="⏰ Zeit+", value="> Füge Zeit hinzu", inline=True)
                    key_embed.add_field(name="📋 Keys", value="> Zeige alle Keys", inline=True)
                    key_embed.add_field(name="🔄 HWID", value="> Setzt HWID zurück", inline=True)
                    key_embed.add_field(name="🔁 Restart", value="> Bot neu starten", inline=True)
                    key_embed.add_field(name="🧹 Clear", value="> Löscht Nachrichten", inline=True)
                    key_embed.add_field(name="🔓 Unlock", value="> Entsperrt Channel", inline=True)
                    key_embed.set_footer(text="F I STEINKE C++ MEISTER")
                    
                    await channel.send(embed=key_embed, view=AdminMenuView())
                    print("✅ Key Embed mit Menü gesendet!")
        except Exception as e:
            print(f"Key Embed error: {e}")
            await asyncio.sleep(10)

async def post_whitelist_embed_start():
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            channel = guild.get_channel(WHITELIST_CHANNEL_ID)
            if channel:
                await channel.purge(check=lambda m: m.embeds and m.embeds[0].title and "Whitelist Verwaltung" in m.embeds[0].title)
                
                whitelist_embed = discord.Embed(
                    title="📋 Whitelist Verwaltung",
                    color=0x000000
                )
                whitelist_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1475174657488322582/1492708596839088180/bypass_logo.png")
                whitelist_embed.add_field(name="➕ Add Whitelist", value="> Füge einen User hinzu", inline=True)
                whitelist_embed.add_field(name="➖ Remove Whitelist", value="> Entferne einen User", inline=True)
                whitelist_embed.add_field(name="📋 Whitelist", value="> Zeige alle Whitelist Users", inline=True)
                whitelist_embed.set_footer(text="F I STEINKE C++ MEISTER")
                await channel.send(embed=whitelist_embed, view=WhitelistMenuView())
                print("✅ Whitelist Embed gesendet!")
    except Exception as e:
        print(f"Whitelist Embed Start error: {e}")

async def post_whitelist_embed_loop():
    while True:
        await asyncio.sleep(600)
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                channel = guild.get_channel(WHITELIST_CHANNEL_ID)
                if channel:
                    await asyncio.sleep(2)
                    await channel.purge(check=lambda m: m.embeds and m.embeds[0].title and "Whitelist Verwaltung" in m.embeds[0].title, limit=1)
                    
                    whitelist_embed = discord.Embed(
                        title="📋 Whitelist Verwaltung",
                        color=0x000000
                    )
                    whitelist_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1475174657488322582/1492708596839088180/bypass_logo.png")
                    whitelist_embed.add_field(name="👑 Add Master", value="> Füge einen Master hinzu", inline=True)
                    whitelist_embed.add_field(name="➕ Add Whitelist", value="> Füge einen User hinzu", inline=True)
                    whitelist_embed.add_field(name="➖ Remove Whitelist", value="> Entferne einen User", inline=True)
                    whitelist_embed.add_field(name="📋 Whitelist", value="> Zeige alle Whitelist Users", inline=True)
                    whitelist_embed.set_footer(text="F I STEINKE C++ MEISTER")
                    await channel.send(embed=whitelist_embed, view=WhitelistMenuView())
                    print("✅ Whitelist Embed gesendet!")
        except Exception as e:
            print(f"Whitelist Embed error: {e}")
            await asyncio.sleep(10)

class WhitelistMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Master+", style=discord.ButtonStyle.grey, custom_id="wl_add_master", emoji="👑")
    async def add_master_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message("Nur der Boss kann das.", ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Add Master"))

    @discord.ui.button(label="Add", style=discord.ButtonStyle.grey, custom_id="wl_add", emoji="➕")
    async def add_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message("Nur der Boss kann das.", ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Add Whitelist"))

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.grey, custom_id="wl_remove", emoji="➖")
    async def remove_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_master(interaction.user.id):
            await interaction.response.send_message("Nur der Boss kann das.", ephemeral=True)
            return
        await interaction.response.send_modal(WhitelistModal("Remove Whitelist"))

    @discord.ui.button(label="List", style=discord.ButtonStyle.grey, custom_id="wl_list", emoji="📋")
    async def list_whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_whitelisted(interaction.user.id):
            await interaction.response.send_message("Kein Zugriff", ephemeral=True)
            return
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT * FROM whitelist ORDER BY added_at DESC")
        results = c.fetchall()
        conn.close()
        
        if not results:
            await interaction.response.send_message("Keine Whitelist Users vorhanden.", ephemeral=True)
            return
        
        embed = discord.Embed(title="📋 Whitelist Users", color=0x000000)
        for row in results:
            discord_id, added_at = row
            try:
                user = await bot.fetch_user(int(discord_id))
                username = f"{user.name}#{user.discriminator}" if user else "Unbekannt"
            except:
                username = "Unbekannt"
            embed.add_field(name=f"👤 {username}", value=f"ID: `{discord_id}`\nHinzugefügt: {added_at[:10]}", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class WhitelistModal(discord.ui.Modal):
    def __init__(self, action):
        super().__init__(title=action)
        self.action = action
        self.discord_id = discord.ui.TextInput(label="Discord ID", placeholder="z.B. 123456789012345678")
        self.add_item(self.discord_id)

    async def on_submit(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        if self.action == "Add Whitelist":
            try:
                discord_id = self.discord_id.value.strip()
                c.execute("INSERT OR IGNORE INTO whitelist (discord_id, added_at) VALUES (?, ?)", (discord_id, datetime.now().isoformat()))
                conn.commit()
                sync_db_to_gist()
                embed = discord.Embed(title="✅ Whitelist hinzugefügt", color=0x000000, description=f"User ID: `{discord_id}`")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log("Whitelist Hinzugefügt", interaction.user, f"User ID: `{discord_id}`", 0x00ff00)
            except Exception as e:
                await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)
        
        elif self.action == "Remove Whitelist":
            try:
                discord_id = self.discord_id.value.strip()
                c.execute("DELETE FROM whitelist WHERE discord_id = ?", (discord_id,))
                conn.commit()
                sync_db_to_gist()
                embed = discord.Embed(title="✅ Whitelist entfernt", color=0x000000, description=f"User ID: `{discord_id}`")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log("Whitelist Entfernt", interaction.user, f"User ID: `{discord_id}`", 0xff0000)
            except Exception as e:
                await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)
        
        elif self.action == "Add Master":
            try:
                discord_id = self.discord_id.value.strip()
                c.execute("INSERT OR IGNORE INTO masters (discord_id, added_at) VALUES (?, ?)", (discord_id, datetime.now().isoformat()))
                c.execute("INSERT OR IGNORE INTO whitelist (discord_id, added_at) VALUES (?, ?)", (discord_id, datetime.now().isoformat()))
                conn.commit()
                sync_db_to_gist()
                embed = discord.Embed(title="✅ Master hinzugefügt", color=0x000000, description=f"User ID: `{discord_id}`")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log("Master Hinzugefügt", interaction.user, f"Neuer Master: `{discord_id}`", 0x00ff00)
            except Exception as e:
                await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)
        
        conn.close()

# === TICKET SYSTEM START ===
async def send_ticket_log(message):
    try:
        guild = bot.get_guild(TICKET_GUILD_ID)
        if guild:
            log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(description=message, color=TICKET_EMBED_COLOR, timestamp=datetime.now())
                embed.set_footer(text="Rayx Logs")
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Ticket log error: {e}")

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Advanced Phone", description="If you want to buy the Advanced Phone Plan click here", emoji="📱", value="advanced_phone"),
            discord.SelectOption(label="Support", description="If you have a question click here", emoji="❓", value="support")
        ]
        super().__init__(placeholder="Triff eine Auswahl", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        type_name = "Advanced Phone" if self.values[0] == "advanced_phone" else "Support"
        member = interaction.user
        guild = interaction.guild

        existing = discord.utils.get(guild.text_channels, name=f"ticket-{member.name.lower()}")
        if existing:
            await interaction.response.send_message(f"❌ Du hast bereits ein Ticket: {existing.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        }

        category_id = ADVANCED_CATEGORY_ID if self.values[0] == "advanced_phone" else SUPPORT_CATEGORY_ID
        category = guild.get_channel(category_id)

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{member.name.lower()}",
            overwrites=overwrites,
            category=category
        )

        ticket_channels[ticket_channel.id] = {
            "user_id": member.id,
            "type": type_name,
            "created_at": datetime.now()
        }
        ticket_messages[ticket_channel.id] = []

        embed = discord.Embed(
            title=f"Rayx {type_name} Ticket",
            description=f"Hallo {member.mention}, willkommen bei deinem **{type_name}** Ticket.\n\nBitte beschreibe dein Anliegen und ein Mitarbeiter wird sich bei dir melden.\n\n**Ticket Info:**\n> Erstellt von: {member}\n> Typ: {type_name}\n> Erstellt am: <t:{int(datetime.now().timestamp())}:F>",
            color=TICKET_EMBED_COLOR
        )
        embed.set_image(url=TICKET_LOGO_URL)
        embed.set_footer(text="Rayx Support © 2026")

        view = TicketButtons()
        await ticket_channel.send(content=f"{member.mention}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Dein Ticket wurde erstellt: {ticket_channel.mention}", ephemeral=True)
        await send_ticket_log(f"🎫 **Neues Ticket erstellt**\n> Von: {member}\n> Typ: {type_name}\n> Channel: {ticket_channel.mention}")

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_data = ticket_channels.get(interaction.channel.id)
        if not ticket_data:
            await interaction.response.send_message("❌ Dies ist kein Ticket.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Ticket wird geschlossen...")
        user = await bot.fetch_user(ticket_data["user_id"])

        embed = discord.Embed(
            title="🔒 Ticket geschlossen",
            description=f"**Ticket wurde geschlossen:**\n> Geschlossen von: {interaction.user}\n> Erstellt von: {user}\n> Typ: {ticket_data['type']}\n> Erstellt am: <t:{int(ticket_data['created_at'].timestamp())}:F>\n> Geschlossen am: <t:{int(datetime.now().timestamp())}:F>",
            color=0xff0000
        )
        embed.set_footer(text="Rayx Support © 2026")
        await interaction.channel.send(embed=embed)

        await send_ticket_log(f"🔒 **Ticket geschlossen**\n> Von: {interaction.user}\n> Ticket: {interaction.channel.mention}\n> Erstellt von: {user}\n> Typ: {ticket_data['type']}")

        ticket_channels.pop(interaction.channel.id, None)
        ticket_messages.pop(interaction.channel.id, None)

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass

    @discord.ui.button(label="Ticket umbenennen", style=discord.ButtonStyle.grey, custom_id="rename_ticket", emoji="✏️")
    async def rename_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_data = ticket_channels.get(interaction.channel.id)
        if not ticket_data:
            await interaction.response.send_message("❌ Dies ist kein Ticket.", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

class RenameModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Ticket umbenennen")
        self.new_name = discord.ui.TextInput(label="Neuer Name", placeholder="Gib den neuen Ticket-Namen ein", style=discord.TextStyle.short, required=True)
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.new_name.value.lower().replace(" ", "-").replace("ticket-", "")
        await interaction.channel.edit(name=f"ticket-{name}")
        await interaction.response.send_message(f"✅ Ticket wurde zu **{name}** umbenannt.", ephemeral=True)
        await send_ticket_log(f"✏️ **Ticket umbenannt**\n> Von: {interaction.user}\n> Neuer Name: {name}\n> Channel: {interaction.channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def ticket(ctx):
    if ctx.channel.id != TICKET_CHANNEL_ID:
        await ctx.send("❌ Dieser Befehl ist nur im Ticket-Channel verfügbar.", delete_after=5)
        return
    embed = discord.Embed(
        title="Rayx Ticket",
        description="**Triff eine Auswahl um ein Ticket zu eröffnen:**\n\n- **Advanced Phone** — If you want to buy the Advanced Phone Plan click here\n- **Support** — If you have a question click here",
        color=TICKET_EMBED_COLOR
    )
    embed.set_image(url=TICKET_LOGO_URL)
    embed.set_footer(text="Rayx Support © 2026")
    embed.timestamp = datetime.now()
    await ctx.send(embed=embed, view=TicketView())

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
# === TICKET SYSTEM END ===

bot.run(os.environ.get("DISCORD_TOKEN"))
