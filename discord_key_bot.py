import discord
from discord.ext import commands
import sqlite3
import uuid
from datetime import datetime, timedelta
import json
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATABASE = "keys.db"

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
    conn.commit()
    conn.close()

init_db()

def get_expiry(duration_type, duration_value, created_at=None):
    if created_at is None:
        created_at = datetime.now()
    else:
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

@bot.command()
@commands.has_permissions(administrator=True)
async def createkey(ctx, duration_value: int, duration_type: str):
    """Erstellt einen neuen Key: !createkey 30 day"""
    valid_types = ["minute", "hour", "day", "week", "month", "year"]
    if duration_type.lower() not in valid_types:
        await ctx.send(f"Ungültiger Zeittyp. Gültige Typen: {', '.join(valid_types)}")
        return
    
    key_id = str(uuid.uuid4())[:8].upper()
    key = f"{key_id}-{uuid.uuid4().hex[:8].upper()}"
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
    embed.add_field(name="Lifetime", value=time_remaining(expires_at), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def redeem(ctx, *, key: str):
    """Löst einen Key ein: !redeem XXXX-XXXX-XXXX"""
    key = key.strip()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!")
        conn.close()
        return
    
    _, hwid, discord_id, created_at, expires_at, _, _, used = result
    
    if used:
        await ctx.send("❌ Key wurde bereits eingelöst!")
        conn.close()
        return
    
    if datetime.now() > datetime.fromisoformat(expires_at):
        await ctx.send("❌ Key ist abgelaufen!")
        conn.close()
        return
    
    hwid_input = str(ctx.author.id)
    
    c.execute("""UPDATE keys SET used = 1, hwid = ?, discord_id = ? WHERE key = ?""",
              (hwid_input, str(ctx.author.id), key))
    conn.commit()
    conn.close()
    
    embed = discord.Embed(title="✅ Key Eingelöst", color=0x00ff00)
    embed.add_field(name="Discord", value=f"{ctx.author} ({ctx.author.id})", inline=False)
    embed.add_field(name="Lifetime", value=time_remaining(expires_at), inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def deletekey(ctx, *, key: str):
    """Löscht einen Key: !deletekey XXXX-XXXX-XXXX"""
    key = key.strip()
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    result = c.fetchone()
    
    if not result:
        await ctx.send("❌ Key existiert nicht!")
        conn.close()
        return
    
    c.execute("DELETE FROM keys WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ Key `{key}` wurde gelöscht!")

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
            value=f"Lifetime: {remaining}\nDiscord: {discord_info}",
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
    embed.add_field(name="Lifetime", value=remaining, inline=True)
    
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

@bot.event
async def on_ready():
    print(f"Bot ist online als {bot.user}")

bot.run("MTQyNjI1NDEyNjE2MDk0MTA4NQ.G8K0Gr.nwJvVQevK7hSWaRTCM6ki3BrH4cVV8gNxTACNI")
