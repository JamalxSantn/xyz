import discord
from discord.ext import commands
import sqlite3
import uuid
from datetime import datetime, timedelta
import json
import os
import sys
import subprocess
import ctypes
import asyncio
import threading
from flask import Flask, jsonify, request, render_template

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.db")
PURGE_CHANNEL_ID = 1475174657488322582
WHITELIST_CHANNEL_ID = 1492701238993621073
LOG_CHANNEL_ID = 1486684959514300467
BOT_LOG_CHANNEL_ID = 1492724379514048645
GUILD_ID = 1475174654741319762
MASTER_ID = "1027571297514967140"

def init_db():
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
    conn.close()

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

def send_key_log_sync(action, details, color=0x00ff00):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(send_log(action, None, details, color))
        else:
            loop.run_until_complete(send_log(action, None, details, color))
    except:
        pass

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

@bot.command()
async def checkkey(ctx, *, key: str):
    """Prüft einen Key: !checkkey XXXX-XXXX-XXXX"""
    key = key.strip()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!")
        return
    
    _, hwid, discord_id, created_at, expires_at, duration_type, duration_value, used = result
    
    status = "✅ Eingelöst" if used else "⏳ Unbenutzt"
    remaining = time_remaining(expires_at)
    
    embed = discord.Embed(title=f"Key Info: {key}", color=0x3498db)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Time", value=remaining, inline=True)
    
    if discord_id:
        embed.add_field(name="Discord", value=f"<@{discord_id}>", inline=False)
        embed.add_field(name="Discord ID", value=discord_id, inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
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

LOAD_CHANNEL_ID = 1495527186700959865
LOAD_URL = "http://192.168.178.72:5000"
CHEAT_EXE = r"C:\Users\jamal\Downloads\cellphone\cellphone\js\cellphone\x64\Release\Fivem-External.exe"

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
                embed = discord.Embed(title="✅ Master hinzugefügt", color=0x000000, description=f"User ID: `{discord_id}`")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log("Master Hinzugefügt", interaction.user, f"Neuer Master: `{discord_id}`", 0x00ff00)
            except Exception as e:
                await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)
        
        conn.close()

bot.run("MTQyNjI1NDEyNjE2MDk0MTA4NQ.GraR20.orpRf7HtnjTrghu-WTcffRUSa7Hkj9RmLDqvFM")
