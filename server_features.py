# ══════════════════════════════════════════════════════════════
#  RAYX Bot – Server-Features (NEU, Erweiterung)
# ══════════════════════════════════════════════════════════════
#
#  Dieses Modul ERGÄNZT den bestehenden Bot (discord_key_bot.py).
#  Es verändert KEIN bestehendes Logging (send_log, send_bot_log,
#  send_ticket_log, Key-/Inject-Logs, Chat-Logs bleiben unangetastet).
#
#  Enthalten:
#    1. Server-Logging   → alle wichtigen Server-Aktionen als Embeds
#                          in SERVER_LOG_CHANNEL_ID
#    2. Ankündigungs-System (Bilder + Text) in ANNOUNCE_CHANNEL_ID
#    3. Slash-Command  /send
#
#  Eingebunden in discord_key_bot.py (kurz vor "Start"):
#       from server_features import install_server_features
#       install_server_features(bot)
#
#  Alle Listener sind Cog-Listener → sie laufen ZUSÄTZLICH zu den
#  bestehenden @bot.event-Handlern (on_ready / on_message bleiben gleich).
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import io
import os
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


# ══════════════════════════════════════════════════════════════
#  .env laden (optional, ohne Zusatz-Paket)
# ══════════════════════════════════════════════════════════════

def _load_dotenv() -> None:
    """Liest eine .env-Datei neben dieser Datei ein (falls vorhanden).
    Bereits gesetzte Umgebungsvariablen (z.B. aus start.bat) werden
    NICHT überschrieben."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"[SERVER-FEATURES] .env konnte nicht gelesen werden: {e}")


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "ja", "on")


# ══════════════════════════════════════════════════════════════
#  Konfiguration  (per .env überschreibbar)
# ══════════════════════════════════════════════════════════════

# Server, dessen Aktionen geloggt werden + Log-Channel
LOG_GUILD_ID          = _env_int("SERVER_LOG_GUILD_ID", 1472228342118879370)
SERVER_LOG_CHANNEL_ID = _env_int("SERVER_LOG_CHANNEL_ID", 1472321917129068825)

# Ankündigungs-System
ANNOUNCE_CHANNEL_ID        = _env_int("ANNOUNCE_CHANNEL_ID", 1553621442992672918)
ANNOUNCE_DEFAULT_TARGET_ID = _env_int("ANNOUNCE_DEFAULT_TARGET_ID", 0)   # 0 = gleicher Channel

# Server, in denen /send registriert wird (sofort sichtbar per Guild-Sync)
SLASH_GUILD_IDS = [
    int(x) for x in os.environ.get(
        "SLASH_GUILD_IDS", "1472228342118879370,1537561860163768412"
    ).split(",") if x.strip().isdigit()
]

# Einzelne Log-Kategorien an/aus
LOG_MENTIONS     = _env_bool("LOG_MENTIONS", True)
LOG_ATTACHMENTS  = _env_bool("LOG_ATTACHMENTS", True)
LOG_VOICE        = _env_bool("LOG_VOICE", True)
LOG_MESSAGE_EDIT = _env_bool("LOG_MESSAGE_EDIT", True)

# Staff-Liste (Embed wird automatisch aktualisiert)
STAFF_LIST_CHANNEL_ID = _env_int("STAFF_LIST_CHANNEL_ID", 1553630672596504636)
# Reihenfolge = Rang (oben = höchster). Jeder wird nur unter seiner HÖCHSTEN Rolle gelistet.
STAFF_ROLES = [
    ("Owner",         1472321741391925362),
    ("Developer",     1472321746236604436),
    ("Manager",       1472321749298446611),
    ("Administrator", 1472321744839901334),
    ("Staff",         1541543148122280026),
    ("7z",            1472321748358660259),
]
STAFF_LIST_TITLE = "‶ Staff Team"

# ── Design ──
LOG_FOOTER       = "RAYX • Server Logs"
ANNOUNCE_FOOTER  = "RAYX"
EMBED_DARK       = 0x000000     # schwarzer Balken links (wie im "PASSED"-Stil)
ANNOUNCE_SHOW_FOOTER = _env_bool("ANNOUNCE_SHOW_FOOTER", False)   # "von <User>" unter der Ankündigung

C_CREATE  = 0x2ECC71   # grün      – erstellt
C_DELETE  = 0xE74C3C   # rot       – gelöscht
C_UPDATE  = 0xF1C40F   # gelb      – geändert
C_JOIN    = 0x57F287   # hellgrün  – beigetreten
C_LEAVE   = 0xED4245   # hellrot   – verlassen
C_BAN     = 0x992D22   # dunkelrot – Ban
C_MOD     = 0xE67E22   # orange    – Timeout / Kick
C_MESSAGE = 0x3498DB   # blau      – Nachrichten
C_MENTION = 0x1ABC9C   # türkis    – Pings
C_MEDIA   = 0x9B59B6   # lila      – Bilder / Dateien
C_VOICE   = 0x5865F2   # blurple   – Voice
C_INFO    = 0x95A5A6   # grau      – Sonstiges

# Farb-Presets für /send (Name → Hex)
COLOR_PRESETS = {
    "dark": EMBED_DARK, "schwarz": EMBED_DARK, "black": EMBED_DARK,
    "rot": 0xE74C3C, "red": 0xE74C3C,
    "grün": 0x2ECC71, "gruen": 0x2ECC71, "green": 0x2ECC71,
    "blau": 0x3498DB, "blue": 0x3498DB,
    "blurple": 0x5865F2,
    "gelb": 0xF1C40F, "yellow": 0xF1C40F,
    "orange": 0xE67E22,
    "lila": 0x9B59B6, "purple": 0x9B59B6,
    "pink": 0xEB459E,
    "weiß": 0xFFFFFF, "weiss": 0xFFFFFF, "white": 0xFFFFFF,
    "gold": 0xD4AF37,
}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_EMBED_IMAGES = 10           # Discord erlaubt max. 10 Embeds pro Nachricht (1 Bild je Embed)


# ══════════════════════════════════════════════════════════════
#  Kleine Helfer
# ══════════════════════════════════════════════════════════════

def _cut(text, limit: int = 1024) -> str:
    """Kürzt Text auf Discord-Limits (Felder: 1024, Beschreibung: 4096)."""
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _code(text, limit: int = 1000) -> str:
    """Setzt Text in einen Codeblock (für Nachrichteninhalte)."""
    text = (text or "").replace("```", "`​``")
    return f"```\n{_cut(text, limit - 8)}\n```" if text else "*— kein Text —*"


def _user(u) -> str:
    if u is None:
        return "*Unbekannt*"
    return f"{u.mention}\n`{u}` · `{u.id}`"


def _chan(c) -> str:
    if c is None:
        return "*Unbekannt*"
    mention = getattr(c, "mention", f"#{c}")
    return f"{mention}\n`#{getattr(c, 'name', c)}` · `{c.id}`"


def _ts(dt: Optional[datetime], style: str = "R") -> str:
    return discord.utils.format_dt(dt, style) if dt else "—"


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _is_image(filename: str, content_type: Optional[str] = None) -> bool:
    if content_type and content_type.startswith("image/"):
        return True
    return filename.lower().endswith(IMAGE_EXTS)


def _safe_filename(name: str, index: int) -> str:
    """Dateinamen für attachment:// müssen ASCII-sicher sein."""
    base = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "file"
    return f"{index}_{base}"[:100]


def _perm_names(perms: discord.Permissions) -> list[str]:
    return [name.replace("_", " ").title() for name, value in perms if value]


def parse_color(value: Optional[str], default: int = EMBED_DARK) -> int:
    """Akzeptiert Preset-Namen ('rot', 'blue') oder Hex ('#ff0000', '0xff0000', 'ff0000')."""
    if not value:
        return default
    v = value.strip().lower()
    if v in COLOR_PRESETS:
        return COLOR_PRESETS[v]
    v = v.removeprefix("#").removeprefix("0x")
    if re.fullmatch(r"[0-9a-f]{6}", v):
        return int(v, 16)
    raise ValueError(f"Ungültige Farbe: `{value}` – nutze z.B. `#ff0000` oder `rot`.")


def log_embed(title: str, color: int, *, user=None, description: Optional[str] = None) -> discord.Embed:
    """Einheitliches, modernes Log-Embed: Titel, Autor mit Avatar, Zeitstempel, Footer mit ID."""
    embed = discord.Embed(title=title, description=description, color=color,
                          timestamp=discord.utils.utcnow())
    if user is not None:
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"{LOG_FOOTER}  •  User-ID: {user.id}")
    else:
        embed.set_footer(text=LOG_FOOTER)
    return embed


# ══════════════════════════════════════════════════════════════
#  1.  SERVER-LOGGING
# ══════════════════════════════════════════════════════════════

class ServerLogger(commands.Cog):
    """Loggt Server-Aktionen in SERVER_LOG_CHANNEL_ID."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Nachrichten, die der Bot selbst löscht (Ankündigungs-Entwürfe) → nicht loggen
        self.suppressed_deletes: set[int] = set()

    # ── Infrastruktur ─────────────────────────────────────────

    def _relevant(self, guild: Optional[discord.Guild]) -> bool:
        return guild is not None and guild.id == LOG_GUILD_ID

    async def _log_channel(self) -> Optional[discord.abc.Messageable]:
        ch = self.bot.get_channel(SERVER_LOG_CHANNEL_ID)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(SERVER_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return None
        return ch

    async def send(self, embed: discord.Embed, **kwargs) -> None:
        """Sendet ein Embed in den Server-Log-Channel – Fehler werden nur geprintet."""
        try:
            channel = await self._log_channel()
            if channel is None:
                print(f"[SERVER-LOG] Log-Channel {SERVER_LOG_CHANNEL_ID} nicht gefunden.")
                return
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(), **kwargs)
        except discord.Forbidden:
            print("[SERVER-LOG] Keine Rechte im Log-Channel (Nachrichten senden / Links einbetten).")
        except Exception as e:
            print(f"[SERVER-LOG] Fehler: {e}")

    async def audit(self, guild: discord.Guild, action: discord.AuditLogAction,
                    target_id: Optional[int] = None, max_age: float = 20.0,
                    delay: float = 1.5) -> Optional[discord.AuditLogEntry]:
        """Sucht den passenden Audit-Log-Eintrag (wer hat es getan? Grund?).
        Braucht die Bot-Berechtigung 'Audit-Log anzeigen'."""
        if not guild.me or not guild.me.guild_permissions.view_audit_log:
            return None
        await asyncio.sleep(delay)          # Audit-Log wird minimal verzögert geschrieben
        try:
            now = discord.utils.utcnow()
            async for entry in guild.audit_logs(limit=8, action=action):
                if (now - entry.created_at).total_seconds() > max_age:
                    continue
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    @staticmethod
    def _add_executor(embed: discord.Embed, entry: Optional[discord.AuditLogEntry]) -> None:
        if entry is None:
            return
        embed.add_field(name="Ausgeführt von", value=_user(entry.user), inline=True)
        if entry.reason:
            embed.add_field(name="Grund", value=_cut(entry.reason), inline=False)

    # ── Rollen ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if not self._relevant(role.guild):
            return
        e = log_embed("🟢  Rolle erstellt", C_CREATE)
        e.add_field(name="Rolle", value=f"{role.mention}\n`{role.name}` · `{role.id}`", inline=True)
        e.add_field(name="Farbe", value=f"`{role.color}`", inline=True)
        self._add_executor(e, await self.audit(role.guild, discord.AuditLogAction.role_create, role.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if not self._relevant(role.guild):
            return
        e = log_embed("🔴  Rolle gelöscht", C_DELETE)
        e.add_field(name="Rolle", value=f"`{role.name}` · `{role.id}`", inline=True)
        e.add_field(name="Farbe", value=f"`{role.color}`", inline=True)
        e.add_field(name="Mitglieder", value=f"`{len(role.members)}`", inline=True)
        self._add_executor(e, await self.audit(role.guild, discord.AuditLogAction.role_delete, role.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if not self._relevant(after.guild):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Farbe:** `{before.color}` → `{after.color}`")
        if before.hoist != after.hoist:
            changes.append(f"**Separat anzeigen:** `{before.hoist}` → `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Erwähnbar:** `{before.mentionable}` → `{after.mentionable}`")
        if getattr(before, "icon", None) != getattr(after, "icon", None) or \
           getattr(before, "unicode_emoji", None) != getattr(after, "unicode_emoji", None):
            changes.append("**Icon** wurde geändert")

        added = removed = []
        if before.permissions != after.permissions:
            b, a = set(_perm_names(before.permissions)), set(_perm_names(after.permissions))
            added, removed = sorted(a - b), sorted(b - a)

        # Reine Positions-Änderungen (Rollen verschieben) erzeugen sonst Spam → ignorieren
        if not changes and not added and not removed:
            return

        e = log_embed("🟡  Rolle aktualisiert", C_UPDATE)
        e.add_field(name="Rolle", value=f"{after.mention}\n`{after.name}` · `{after.id}`", inline=False)
        if changes:
            e.add_field(name="Änderungen", value=_cut("\n".join(changes)), inline=False)
        if added:
            e.add_field(name="✅ Rechte hinzugefügt", value=_cut("\n".join(f"`{p}`" for p in added)), inline=True)
        if removed:
            e.add_field(name="❌ Rechte entfernt", value=_cut("\n".join(f"`{p}`" for p in removed)), inline=True)
        self._add_executor(e, await self.audit(after.guild, discord.AuditLogAction.role_update, after.id))
        await self.send(e)

    # ── Mitglieder: Nickname, Timeout, Rollen ─────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not self._relevant(after.guild):
            return

        # Nickname / Server-Anzeigename
        if before.nick != after.nick:
            e = log_embed("✏️  Nickname geändert", C_UPDATE, user=after)
            e.add_field(name="Mitglied", value=_user(after), inline=False)
            e.add_field(name="Vorher", value=f"`{before.nick or before.name}`", inline=True)
            e.add_field(name="Nachher", value=f"`{after.nick or after.name}`", inline=True)
            entry = await self.audit(after.guild, discord.AuditLogAction.member_update, after.id)
            if entry and entry.user and entry.user.id != after.id:
                self._add_executor(e, entry)
            await self.send(e)

        # Timeout
        b_to = getattr(before, "timed_out_until", None)
        a_to = getattr(after, "timed_out_until", None)
        if b_to != a_to:
            now = discord.utils.utcnow()
            if a_to and a_to > now:
                e = log_embed("⏳  Mitglied getimeoutet", C_MOD, user=after)
                e.add_field(name="Mitglied", value=_user(after), inline=True)
                e.add_field(name="Endet", value=f"{_ts(a_to, 'F')}\n({_ts(a_to, 'R')})", inline=True)
            else:
                e = log_embed("✅  Timeout aufgehoben", C_CREATE, user=after)
                e.add_field(name="Mitglied", value=_user(after), inline=True)
            self._add_executor(e, await self.audit(after.guild, discord.AuditLogAction.member_update, after.id))
            await self.send(e)

        # Rollen vergeben / entfernt
        if before.roles != after.roles:
            b, a = set(before.roles), set(after.roles)
            added, removed = a - b, b - a
            if added or removed:
                e = log_embed("🎭  Rollen des Mitglieds geändert", C_UPDATE, user=after)
                e.add_field(name="Mitglied", value=_user(after), inline=False)
                if added:
                    e.add_field(name="➕ Hinzugefügt", value=_cut(" ".join(r.mention for r in added)), inline=True)
                if removed:
                    e.add_field(name="➖ Entfernt", value=_cut(" ".join(r.mention for r in removed)), inline=True)
                self._add_executor(e, await self.audit(after.guild, discord.AuditLogAction.member_role_update, after.id))
                await self.send(e)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        """Globaler Anzeigename / Username geändert (nur wenn im Log-Server)."""
        guild = self.bot.get_guild(LOG_GUILD_ID)
        if guild is None or guild.get_member(after.id) is None:
            return
        b_name, a_name = getattr(before, "global_name", None), getattr(after, "global_name", None)
        if before.name == after.name and b_name == a_name:
            return
        e = log_embed("🪪  Anzeigename / Username geändert", C_UPDATE, user=after)
        e.add_field(name="Mitglied", value=_user(after), inline=False)
        if b_name != a_name:
            e.add_field(name="Anzeigename", value=f"`{b_name or '—'}` → `{a_name or '—'}`", inline=False)
        if before.name != after.name:
            e.add_field(name="Username", value=f"`{before.name}` → `{after.name}`", inline=False)
        await self.send(e)

    # ── Join / Leave / Kick / Ban ─────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self._relevant(member.guild):
            return
        age_days = (discord.utils.utcnow() - member.created_at).days
        title = "🤖  Bot hinzugefügt" if member.bot else "📥  Mitglied beigetreten"
        e = log_embed(title, C_JOIN, user=member)
        e.add_field(name="Mitglied", value=_user(member), inline=True)
        e.add_field(name="Account erstellt", value=f"{_ts(member.created_at, 'D')}\n({_ts(member.created_at)})", inline=True)
        e.add_field(name="Mitglieder jetzt", value=f"`{member.guild.member_count}`", inline=True)
        if age_days < 7:
            e.add_field(name="⚠️ Achtung", value=f"Account ist erst **{age_days} Tag(e)** alt.", inline=False)
        if member.bot:
            self._add_executor(e, await self.audit(member.guild, discord.AuditLogAction.bot_add, member.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not self._relevant(member.guild):
            return
        # Kick oder freiwillig verlassen? → Audit-Log prüfen
        kick = await self.audit(member.guild, discord.AuditLogAction.kick, member.id)
        if kick:
            e = log_embed("👢  Mitglied gekickt", C_MOD, user=member)
        else:
            # Bei Bans kommt zusätzlich on_member_ban – hier trotzdem "verlassen" loggen, wenn kein Ban
            ban = await self.audit(member.guild, discord.AuditLogAction.ban, member.id, delay=0)
            if ban:
                return          # Ban wird separat geloggt
            e = log_embed("📤  Mitglied hat den Server verlassen", C_LEAVE, user=member)
        e.add_field(name="Mitglied", value=_user(member), inline=True)
        if member.joined_at:
            e.add_field(name="Beigetreten", value=_ts(member.joined_at), inline=True)
        e.add_field(name="Mitglieder jetzt", value=f"`{member.guild.member_count}`", inline=True)
        roles = [r.mention for r in member.roles if not r.is_default()]
        if roles:
            e.add_field(name="Rollen", value=_cut(" ".join(reversed(roles))), inline=False)
        self._add_executor(e, kick)
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not self._relevant(guild):
            return
        e = log_embed("🔨  Mitglied gebannt", C_BAN, user=user)
        e.add_field(name="Mitglied", value=_user(user), inline=True)
        self._add_executor(e, await self.audit(guild, discord.AuditLogAction.ban, user.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if not self._relevant(guild):
            return
        e = log_embed("🔓  Ban aufgehoben", C_CREATE, user=user)
        e.add_field(name="Mitglied", value=_user(user), inline=True)
        self._add_executor(e, await self.audit(guild, discord.AuditLogAction.unban, user.id))
        await self.send(e)

    # ── Nachrichten ───────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id != LOG_GUILD_ID or payload.channel_id == SERVER_LOG_CHANNEL_ID:
            return
        if payload.message_id in self.suppressed_deletes:
            self.suppressed_deletes.discard(payload.message_id)
            return
        msg = payload.cached_message
        if msg is not None and msg.author.bot and msg.author.id == self.bot.user.id:
            return      # eigene Bot-Nachrichten nicht loggen
        channel = self.bot.get_channel(payload.channel_id)

        e = log_embed("🗑️  Nachricht gelöscht", C_DELETE, user=msg.author if msg else None)
        if msg is not None:
            e.add_field(name="Autor", value=_user(msg.author), inline=True)
            e.add_field(name="Channel", value=_chan(channel), inline=True)
            e.add_field(name="Gesendet", value=_ts(msg.created_at), inline=True)
            e.add_field(name="Inhalt", value=_code(msg.content), inline=False)
            if msg.attachments:
                files = "\n".join(f"📎 `{a.filename}` ({_size(a.size)})" for a in msg.attachments)
                e.add_field(name="Anhänge", value=_cut(files), inline=False)
            # Wer hat gelöscht? (nur sichtbar, wenn jemand ANDERES gelöscht hat)
            guild = self.bot.get_guild(LOG_GUILD_ID)
            if guild:
                entry = await self.audit(guild, discord.AuditLogAction.message_delete, msg.author.id, max_age=30)
                if entry and getattr(getattr(entry, "extra", None), "channel", None) \
                        and entry.extra.channel.id == payload.channel_id:
                    e.add_field(name="Gelöscht von", value=_user(entry.user), inline=True)
        else:
            e.add_field(name="Channel", value=_chan(channel), inline=True)
            e.add_field(name="Nachricht-ID", value=f"`{payload.message_id}`", inline=True)
            e.add_field(name="Inhalt", value="*Nicht im Cache (Nachricht war zu alt oder Bot war offline).*", inline=False)
        await self.send(e)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id != LOG_GUILD_ID or payload.channel_id == SERVER_LOG_CHANNEL_ID:
            return
        ids = set(payload.message_ids) - self.suppressed_deletes
        if not ids:
            return
        channel = self.bot.get_channel(payload.channel_id)
        e = log_embed("🧹  Mehrere Nachrichten gelöscht", C_DELETE)
        e.add_field(name="Channel", value=_chan(channel), inline=True)
        e.add_field(name="Anzahl", value=f"`{len(ids)}`", inline=True)
        preview = [f"**{m.author}:** {_cut(m.content or '[Anhang]', 80)}"
                   for m in sorted(payload.cached_messages, key=lambda m: m.created_at)[-10:]]
        if preview:
            e.add_field(name="Letzte Nachrichten (Cache)", value=_cut("\n".join(preview)), inline=False)
        await self.send(e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not LOG_MESSAGE_EDIT or not self._relevant(after.guild) or after.author.bot:
            return
        if before.content == after.content:
            return      # z.B. nur Embed-Vorschau geladen
        e = log_embed("📝  Nachricht bearbeitet", C_MESSAGE, user=after.author)
        e.add_field(name="Autor", value=_user(after.author), inline=True)
        e.add_field(name="Channel", value=_chan(after.channel), inline=True)
        e.add_field(name="Link", value=f"[Zur Nachricht]({after.jump_url})", inline=True)
        e.add_field(name="Vorher", value=_code(before.content, 1024), inline=False)
        e.add_field(name="Nachher", value=_code(after.content, 1024), inline=False)
        await self.send(e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Pings + Bilder/Anhänge loggen. (Läuft ZUSÄTZLICH zum bestehenden on_message.)"""
        if message.author.bot or not self._relevant(message.guild):
            return
        if message.channel.id in (SERVER_LOG_CHANNEL_ID, ANNOUNCE_CHANNEL_ID):
            return      # Log-Channel selbst + Ankündigungs-Entwürfe nicht loggen

        # ── Pings ──
        if LOG_MENTIONS:
            users = [m for m in message.mentions if not m.bot and m.id != message.author.id]
            roles = message.role_mentions
            if users or roles or message.mention_everyone:
                e = log_embed("🔔  Mitglied gepingt", C_MENTION, user=message.author)
                e.add_field(name="Von", value=_user(message.author), inline=True)
                e.add_field(name="Channel", value=_chan(message.channel), inline=True)
                e.add_field(name="Link", value=f"[Zur Nachricht]({message.jump_url})", inline=True)
                pinged = [u.mention for u in users] + [r.mention for r in roles]
                if message.mention_everyone:
                    pinged.insert(0, "**@everyone / @here**")
                e.add_field(name="Gepingt", value=_cut(" ".join(pinged)), inline=False)
                e.add_field(name="Nachricht", value=_code(message.content, 800), inline=False)
                await self.send(e)

        # ── Bilder / Anhänge ──
        if LOG_ATTACHMENTS and message.attachments:
            images = [a for a in message.attachments if _is_image(a.filename, a.content_type)]
            title = "🖼️  Bild gesendet" if images and len(images) == len(message.attachments) else "📎  Anhang gesendet"
            e = log_embed(title, C_MEDIA, user=message.author)
            e.add_field(name="Von", value=_user(message.author), inline=True)
            e.add_field(name="Channel", value=_chan(message.channel), inline=True)
            e.add_field(name="Link", value=f"[Zur Nachricht]({message.jump_url})", inline=True)
            files = "\n".join(f"📎 [{a.filename}]({a.url}) · {_size(a.size)}" for a in message.attachments)
            e.add_field(name=f"Dateien ({len(message.attachments)})", value=_cut(files), inline=False)
            if message.content:
                e.add_field(name="Text", value=_code(message.content, 600), inline=False)
            if images:
                e.set_image(url=images[0].url)
            await self.send(e)

    # ── Channels ──────────────────────────────────────────────

    @staticmethod
    def _chan_type(c) -> str:
        return str(getattr(c, "type", "channel")).replace("_", " ").title()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if not self._relevant(channel.guild):
            return
        e = log_embed("📁  Channel erstellt", C_CREATE)
        e.add_field(name="Channel", value=_chan(channel), inline=True)
        e.add_field(name="Typ", value=f"`{self._chan_type(channel)}`", inline=True)
        e.add_field(name="Kategorie", value=f"`{channel.category.name}`" if channel.category else "—", inline=True)
        self._add_executor(e, await self.audit(channel.guild, discord.AuditLogAction.channel_create, channel.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not self._relevant(channel.guild):
            return
        e = log_embed("🗂️  Channel gelöscht", C_DELETE)
        e.add_field(name="Channel", value=f"`#{channel.name}` · `{channel.id}`", inline=True)
        e.add_field(name="Typ", value=f"`{self._chan_type(channel)}`", inline=True)
        e.add_field(name="Kategorie", value=f"`{channel.category.name}`" if channel.category else "—", inline=True)
        self._add_executor(e, await self.audit(channel.guild, discord.AuditLogAction.channel_delete, channel.id))
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if not self._relevant(after.guild):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append(f"**Thema:** `{_cut(before.topic or '—', 200)}` → `{_cut(after.topic or '—', 200)}`")
        if before.category != after.category:
            changes.append(f"**Kategorie:** `{before.category or '—'}` → `{after.category or '—'}`")
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
            changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
        if getattr(before, "user_limit", None) != getattr(after, "user_limit", None):
            changes.append(f"**User-Limit:** `{before.user_limit}` → `{after.user_limit}`")
        if getattr(before, "bitrate", None) != getattr(after, "bitrate", None):
            changes.append(f"**Bitrate:** `{before.bitrate}` → `{after.bitrate}`")
        if before.overwrites != after.overwrites:
            targets = set(before.overwrites) | set(after.overwrites)
            changed = [t for t in targets if before.overwrites.get(t) != after.overwrites.get(t)]
            names = ", ".join(getattr(t, "mention", str(t)) for t in changed[:10])
            changes.append(f"**Berechtigungen geändert für:** {names}")

        if not changes:
            return      # nur Position verschoben → kein Spam
        e = log_embed("🔧  Channel aktualisiert", C_UPDATE)
        e.add_field(name="Channel", value=_chan(after), inline=False)
        e.add_field(name="Änderungen", value=_cut("\n".join(changes)), inline=False)
        entry = await self.audit(after.guild, discord.AuditLogAction.channel_update, after.id)
        if entry is None and before.overwrites != after.overwrites:
            entry = await self.audit(after.guild, discord.AuditLogAction.overwrite_update, after.id, delay=0)
        self._add_executor(e, entry)
        await self.send(e)

    # ── Threads ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if not self._relevant(thread.guild):
            return
        e = log_embed("🧵  Thread erstellt", C_CREATE)
        e.add_field(name="Thread", value=_chan(thread), inline=True)
        e.add_field(name="In Channel", value=_chan(thread.parent), inline=True)
        if thread.owner_id:
            e.add_field(name="Ersteller", value=f"<@{thread.owner_id}>", inline=True)
        await self.send(e)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        if not self._relevant(thread.guild):
            return
        e = log_embed("🧵  Thread gelöscht", C_DELETE)
        e.add_field(name="Thread", value=f"`#{thread.name}` · `{thread.id}`", inline=True)
        e.add_field(name="In Channel", value=_chan(thread.parent), inline=True)
        await self.send(e)

    # ── Einladungen ───────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not self._relevant(invite.guild):
            return
        e = log_embed("✉️  Einladung erstellt", C_INFO, user=invite.inviter)
        e.add_field(name="Von", value=_user(invite.inviter), inline=True)
        e.add_field(name="Code", value=f"`{invite.code}`", inline=True)
        e.add_field(name="Channel", value=_chan(invite.channel), inline=True)
        e.add_field(name="Max. Nutzungen", value=f"`{invite.max_uses or '∞'}`", inline=True)
        e.add_field(name="Läuft ab", value=_ts(invite.expires_at) if invite.expires_at else "`Nie`", inline=True)
        await self.send(e)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not self._relevant(invite.guild):
            return
        e = log_embed("✉️  Einladung gelöscht", C_INFO)
        e.add_field(name="Code", value=f"`{invite.code}`", inline=True)
        e.add_field(name="Channel", value=_chan(invite.channel), inline=True)
        await self.send(e)

    # ── Server / Emojis ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if not self._relevant(after):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Server-Icon** wurde geändert")
        if before.banner != after.banner:
            changes.append("**Server-Banner** wurde geändert")
        if before.verification_level != after.verification_level:
            changes.append(f"**Verifizierung:** `{before.verification_level}` → `{after.verification_level}`")
        if before.vanity_url_code != after.vanity_url_code:
            changes.append(f"**Vanity-URL:** `{before.vanity_url_code}` → `{after.vanity_url_code}`")
        if not changes:
            return
        e = log_embed("🏠  Server aktualisiert", C_UPDATE)
        e.add_field(name="Änderungen", value=_cut("\n".join(changes)), inline=False)
        if after.icon:
            e.set_thumbnail(url=after.icon.url)
        self._add_executor(e, await self.audit(after, discord.AuditLogAction.guild_update))
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        if not self._relevant(guild):
            return
        b, a = {x.id: x for x in before}, {x.id: x for x in after}
        added = [a[i] for i in a.keys() - b.keys()]
        removed = [b[i] for i in b.keys() - a.keys()]
        renamed = [(b[i], a[i]) for i in a.keys() & b.keys() if a[i].name != b[i].name]
        if not (added or removed or renamed):
            return
        e = log_embed("😀  Emojis geändert", C_UPDATE)
        if added:
            e.add_field(name="➕ Hinzugefügt", value=_cut(" ".join(f"{x} `:{x.name}:`" for x in added)), inline=False)
        if removed:
            e.add_field(name="➖ Entfernt", value=_cut(" ".join(f"`:{x.name}:`" for x in removed)), inline=False)
        if renamed:
            e.add_field(name="✏️ Umbenannt", value=_cut("\n".join(f"`:{o.name}:` → `:{n.name}:`" for o, n in renamed)), inline=False)
        await self.send(e)

    # ── Voice ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if not LOG_VOICE or not self._relevant(member.guild) or before.channel == after.channel:
            return
        if before.channel is None:
            e = log_embed("🔊  Voice beigetreten", C_VOICE, user=member)
            e.add_field(name="Channel", value=_chan(after.channel), inline=True)
        elif after.channel is None:
            e = log_embed("🔇  Voice verlassen", C_VOICE, user=member)
            e.add_field(name="Channel", value=_chan(before.channel), inline=True)
        else:
            e = log_embed("🔀  Voice gewechselt", C_VOICE, user=member)
            e.add_field(name="Von", value=_chan(before.channel), inline=True)
            e.add_field(name="Nach", value=_chan(after.channel), inline=True)
        e.add_field(name="Mitglied", value=_user(member), inline=True)
        await self.send(e)


# ══════════════════════════════════════════════════════════════
#  2.  ANKÜNDIGUNGS-SYSTEM  (Bilder + Text)
# ══════════════════════════════════════════════════════════════
#
#  Ablauf:
#   1. User schreibt in ANNOUNCE_CHANNEL_ID eine Nachricht mit Text
#      und/oder einem oder mehreren Bildern.
#      • Erste Zeile mit "# " am Anfang  → wird zum Titel
#      • "--everyone" im Text            → @everyone ist vorausgewählt
#   2. Bot löscht die Original-Nachricht und zeigt eine VORSCHAU mit Buttons:
#      📍 Ziel-Channel wählen · 📣 @everyone an/aus · ✏️ Bearbeiten · ✅ Senden · ✖ Abbrechen
#   3. Bei "Senden" postet der Bot das fertige Embed im Ziel-Channel.
# ══════════════════════════════════════════════════════════════

class AnnouncementDraft:
    """Hält alle Daten einer Ankündigung (Dateien als Bytes, damit sie
    mehrfach gesendet werden können – Vorschau + finale Nachricht)."""

    def __init__(self, author: discord.Member, source: discord.TextChannel):
        self.author = author
        self.guild = source.guild
        self.source = source
        self.title: str = ""
        self.text: str = ""
        self.ping_everyone: bool = False
        self.target: discord.abc.Messageable = source
        self.files: list[tuple[str, bytes, bool, bool]] = []   # (name, data, is_image, spoiler)

    def build(self) -> tuple[list[discord.Embed], list[discord.File]]:
        """Erzeugt Embeds + frische discord.File-Objekte im "PASSED"-Stil:
        schwarzer Balken, fetter Titel, jedes Bild in einem eigenen Embed-Kasten."""
        files = [discord.File(io.BytesIO(data), filename=name, spoiler=spoiler)
                 for name, data, _img, spoiler in self.files]
        images = [name for name, _d, is_img, spoiler in self.files if is_img and not spoiler][:MAX_EMBED_IMAGES]

        title, text = self.title, self.text
        # Kein eigener Titel + kurzer einzeiliger Text → Text wird zum fetten Titel (wie im Screenshot)
        if not title and text and "\n" not in text and len(text) <= 256:
            title, text = text, ""

        main = discord.Embed(title=_cut(title, 256) or None,
                             description=_cut(text, 4096) or None,
                             color=EMBED_DARK)
        if ANNOUNCE_SHOW_FOOTER:
            main.set_footer(text=f"von {self.author.display_name}", icon_url=self.author.display_avatar.url)
        embeds = [main]
        if images:
            main.set_image(url=f"attachment://{images[0]}")
            for name in images[1:]:
                extra = discord.Embed(color=EMBED_DARK)
                extra.set_image(url=f"attachment://{name}")
                embeds.append(extra)
        return embeds, files


class AnnouncementEditModal(discord.ui.Modal, title="Ankündigung bearbeiten"):
    def __init__(self, view: "AnnouncementPreviewView"):
        super().__init__(timeout=600)
        self.preview = view
        self.title_input = discord.ui.TextInput(
            label="Titel (optional)", default=view.draft.title[:256], required=False, max_length=256,
            placeholder="z.B. PASSED APP")
        self.text_input = discord.ui.TextInput(
            label="Text", style=discord.TextStyle.paragraph, default=view.draft.text[:4000],
            required=False, max_length=4000)
        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        d = self.preview.draft
        d.title, d.text = self.title_input.value.strip(), self.text_input.value.strip()
        if not d.title and not d.text and not d.files:
            await interaction.response.send_message("❌ Titel, Text oder Bild wird benötigt.", ephemeral=True)
            return
        embeds, _ = d.build()
        await interaction.response.edit_message(content=self.preview.status_line(), embeds=embeds, view=self.preview)


class TargetChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "AnnouncementPreviewView"):
        super().__init__(
            placeholder="📍 Ziel-Channel wählen (Standard: aktueller Channel)",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1, row=0)
        self.preview = view

    async def callback(self, interaction: discord.Interaction):
        picked = self.values[0]
        channel = interaction.guild.get_channel(picked.id)
        if channel is None:
            await interaction.response.send_message("❌ Channel nicht gefunden.", ephemeral=True)
            return
        self.preview.draft.target = channel
        await interaction.response.edit_message(content=self.preview.status_line(), view=self.preview)


class AnnouncementPreviewView(discord.ui.View):
    def __init__(self, draft: AnnouncementDraft, logger: Optional[ServerLogger]):
        super().__init__(timeout=900)       # 15 Minuten
        self.draft = draft
        self.logger = logger
        self.message: Optional[discord.Message] = None
        self.add_item(TargetChannelSelect(self))
        self._sync_everyone_button()

    def status_line(self) -> str:
        d = self.draft
        ping = "✅ an" if d.ping_everyone else "❌ aus"
        return (f"### 📢 Vorschau\n"
                f"**Ziel:** {d.target.mention}  ·  **@everyone:** {ping}  ·  "
                f"**Bilder/Dateien:** {len(d.files)}\n"
                f"-# Nur {d.author.mention} kann diese Vorschau bedienen · läuft nach 15 Min. ab")

    def _sync_everyone_button(self):
        self.toggle_everyone.label = "@everyone: AN" if self.draft.ping_everyone else "@everyone: AUS"
        self.toggle_everyone.style = discord.ButtonStyle.danger if self.draft.ping_everyone else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.draft.author.id or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ Das ist nicht deine Vorschau.", ephemeral=True)
        return False

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⌛ Vorschau abgelaufen – nichts wurde gesendet.",
                                        embeds=[], attachments=[], view=None, delete_after=15)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print(f"[ANNOUNCE] Fehler: {error}")
        msg = "❌ Es ist ein Fehler aufgetreten. Bitte erneut versuchen."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="@everyone: AUS", emoji="📣", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_everyone(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.draft.ping_everyone and not interaction.user.guild_permissions.mention_everyone:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, @everyone zu pingen.", ephemeral=True)
            return
        self.draft.ping_everyone = not self.draft.ping_everyone
        self._sync_everyone_button()
        await interaction.response.edit_message(content=self.status_line(), view=self)

    @discord.ui.button(label="Bearbeiten", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnnouncementEditModal(self))

    @discord.ui.button(label="Senden", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = self.draft
        target = d.target
        member = interaction.user
        me = interaction.guild.me

        # ── Berechtigungen prüfen ──
        u_perms = target.permissions_for(member)
        if not u_perms.send_messages:
            await interaction.response.send_message(f"❌ Du darfst in {target.mention} nicht schreiben.", ephemeral=True)
            return
        if d.ping_everyone and not u_perms.mention_everyone:
            await interaction.response.send_message(f"❌ Du darfst in {target.mention} nicht @everyone pingen.", ephemeral=True)
            return
        b_perms = target.permissions_for(me)
        missing = [n for n, ok in (("Nachrichten senden", b_perms.send_messages),
                                   ("Links einbetten", b_perms.embed_links),
                                   ("Dateien anhängen", b_perms.attach_files or not d.files),
                                   ("@everyone erwähnen", b_perms.mention_everyone or not d.ping_everyone)) if not ok]
        if missing:
            await interaction.response.send_message(
                f"❌ Dem Bot fehlen in {target.mention} Rechte: {', '.join(missing)}", ephemeral=True)
            return

        await interaction.response.defer()
        embeds, files = d.build()
        try:
            sent = await target.send(
                content="@everyone" if d.ping_everyone else None,
                embeds=embeds, files=files,
                allowed_mentions=discord.AllowedMentions(everyone=d.ping_everyone, users=False, roles=False),
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Senden fehlgeschlagen: `{e}`", ephemeral=True)
            return

        self.stop()
        try:
            await interaction.message.edit(
                content=f"✅ **Ankündigung gesendet** in {target.mention} → [Zur Nachricht]({sent.jump_url})",
                embeds=[], attachments=[], view=None, delete_after=20)
        except discord.HTTPException:
            pass

        if self.logger:
            e = log_embed("📢  Ankündigung gesendet", C_INFO, user=member)
            e.add_field(name="Von", value=_user(member), inline=True)
            e.add_field(name="Channel", value=_chan(target), inline=True)
            e.add_field(name="Link", value=f"[Zur Nachricht]({sent.jump_url})", inline=True)
            e.add_field(name="@everyone", value="Ja" if d.ping_everyone else "Nein", inline=True)
            e.add_field(name="Dateien", value=f"`{len(d.files)}`", inline=True)
            if d.title:
                e.add_field(name="Titel", value=_cut(d.title, 256), inline=False)
            await self.logger.send(e)

    @discord.ui.button(label="Abbrechen", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="✖️ Abgebrochen – nichts wurde gesendet.",
                                                embeds=[], attachments=[], view=None, delete_after=10)


class AnnouncementSystem(commands.Cog):
    """Verarbeitet Nachrichten im Ankündigungs-Channel."""

    GUIDE_TITLE = "📢  Ankündigungs-System"
    MAX_FILE_BYTES = 25 * 1024 * 1024

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._guide_checked = False

    @property
    def logger(self) -> Optional[ServerLogger]:
        return self.bot.get_cog("ServerLogger")

    # Anleitung einmalig im Channel posten
    @commands.Cog.listener()
    async def on_ready(self):
        if self._guide_checked:
            return
        self._guide_checked = True
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if channel is None:
            print(f"[ANNOUNCE] Channel {ANNOUNCE_CHANNEL_ID} nicht gefunden.")
            return
        try:
            async for msg in channel.history(limit=50):
                if msg.author.id == self.bot.user.id and msg.embeds and msg.embeds[0].title == self.GUIDE_TITLE:
                    return
            e = discord.Embed(
                title=self.GUIDE_TITLE,
                description=(
                    "Schreib hier einfach deine Nachricht – mit **einem oder mehreren Bildern**.\n"
                    "Der Bot macht daraus ein sauberes Embed und zeigt dir erst eine **Vorschau**.\n\n"
                    "**So geht's**\n"
                    "› Bilder anhängen + Text schreiben → absenden\n"
                    "› Erste Zeile mit `# ` wird zum **Titel** (z.B. `# PASSED APP`)\n"
                    "› `--everyone` im Text → @everyone vorausgewählt\n\n"
                    "**In der Vorschau**\n"
                    "📍 Ziel-Channel wählen · 📣 @everyone an/aus · ✏️ Bearbeiten · ✅ Senden · ✖️ Abbrechen"
                ),
                color=EMBED_DARK,
            )
            e.set_footer(text=ANNOUNCE_FOOTER)
            await channel.send(embed=e)
        except discord.HTTPException as e:
            print(f"[ANNOUNCE] Anleitung konnte nicht gepostet werden: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or message.channel.id != ANNOUNCE_CHANNEL_ID:
            return
        if not message.content and not message.attachments:
            return

        draft = AnnouncementDraft(message.author, message.channel)

        # Standard-Ziel
        if ANNOUNCE_DEFAULT_TARGET_ID:
            default = message.guild.get_channel(ANNOUNCE_DEFAULT_TARGET_ID)
            if default is not None:
                draft.target = default

        # Text parsen: "# Titel" + "--everyone"
        text = message.content or ""
        if re.search(r"(^|\s)--everyone\b", text):
            text = re.sub(r"(^|\s)--everyone\b", " ", text)
            draft.ping_everyone = message.author.guild_permissions.mention_everyone
        lines = text.strip().splitlines()
        if lines and re.match(r"^#{1,3}\s+\S", lines[0]):
            draft.title = re.sub(r"^#{1,3}\s+", "", lines[0]).strip()
            lines = lines[1:]
        draft.text = "\n".join(lines).strip()

        # Anhänge herunterladen (bevor die Original-Nachricht gelöscht wird)
        for i, att in enumerate(message.attachments):
            if att.size > self.MAX_FILE_BYTES:
                continue
            try:
                data = await att.read()
            except discord.HTTPException:
                continue
            draft.files.append((_safe_filename(att.filename, i), data,
                                _is_image(att.filename, att.content_type), att.is_spoiler()))

        if not draft.title and not draft.text and not draft.files:
            return

        # Original löschen (Channel sauber halten) – nicht als "gelöscht" loggen
        if self.logger:
            self.logger.suppressed_deletes.add(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            if self.logger:
                self.logger.suppressed_deletes.discard(message.id)

        view = AnnouncementPreviewView(draft, self.logger)
        embeds, files = draft.build()
        try:
            view.message = await message.channel.send(
                content=view.status_line(), embeds=embeds, files=files, view=view,
                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            print(f"[ANNOUNCE] Vorschau fehlgeschlagen: {e}")


# ══════════════════════════════════════════════════════════════
#  3a. STAFF-LISTE  (auto-aktualisierendes Embed)
# ══════════════════════════════════════════════════════════════
#
#  Postet EIN Embed in STAFF_LIST_CHANNEL_ID und bearbeitet es danach
#  immer wieder (kein Spam). Aktualisiert sich automatisch, wenn:
#   • jemand eine Staff-Rolle bekommt / verliert
#   • ein Staff-Mitglied den Server verlässt
#   • eine Staff-Rolle umbenannt wird
#   • sonst alle 10 Minuten (Sicherheitsnetz)
# ══════════════════════════════════════════════════════════════

class StaffList(commands.Cog):

    UPDATE_DELAY = 5            # Sekunden sammeln, bevor aktualisiert wird (bei vielen Änderungen)
    REFRESH_INTERVAL = 600      # 10 Minuten

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending: Optional[asyncio.Task] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._message_id: Optional[int] = None
        self._lock = asyncio.Lock()
        self._role_ids = {rid for _n, rid in STAFF_ROLES}

    async def cog_unload(self):
        for t in (self._pending, self._loop_task):
            if t:
                t.cancel()

    # ── Embed bauen ───────────────────────────────────────────

    def build_embed(self, guild: discord.Guild) -> discord.Embed:
        listed: set[int] = set()
        embed = discord.Embed(title=STAFF_LIST_TITLE, color=EMBED_DARK)
        total = 0
        for fallback_name, role_id in STAFF_ROLES:
            role = guild.get_role(role_id)
            name = role.name if role else fallback_name
            members = []
            if role:
                for m in sorted(role.members, key=lambda x: x.display_name.lower()):
                    if m.id in listed or m.bot:
                        continue
                    listed.add(m.id)
                    members.append(m)
            total += len(members)

            lines, value = [f"> {m.mention}" for m in members], ""
            for i, line in enumerate(lines):
                if len(value) + len(line) + 30 > 1024:
                    value += f"> *+{len(lines) - i} weitere*"
                    break
                value += line + "\n"
            header = f"{role.mention}" if role else f"`{fallback_name}`"
            embed.add_field(
                name=f"‶ {name}  ·  {len(members)}",
                value=(f"{header}\n{value}" if members else f"{header}\n> *— niemand —*")[:1024],
                inline=False,
            )
        embed.set_footer(text=f"{total} Teammitglieder  •  Automatisch aktualisiert")
        embed.timestamp = discord.utils.utcnow()
        return embed

    # ── Senden / Bearbeiten ───────────────────────────────────

    async def update(self) -> None:
        async with self._lock:
            channel = self.bot.get_channel(STAFF_LIST_CHANNEL_ID)
            if channel is None:
                print(f"[STAFF] Channel {STAFF_LIST_CHANNEL_ID} nicht gefunden.")
                return
            embed = self.build_embed(channel.guild)
            try:
                msg = None
                if self._message_id:
                    try:
                        msg = await channel.fetch_message(self._message_id)
                    except discord.NotFound:
                        msg = None
                if msg is None:
                    # Bestehende Liste suchen (z.B. nach Neustart auf Render)
                    async for m in channel.history(limit=30):
                        if m.author.id == self.bot.user.id and m.embeds and m.embeds[0].title == STAFF_LIST_TITLE:
                            msg = m
                            break
                if msg is None:
                    msg = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await msg.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                self._message_id = msg.id
            except discord.Forbidden:
                print("[STAFF] Keine Rechte im Staff-Channel (Nachrichten senden / Verlauf lesen / Links einbetten).")
            except discord.HTTPException as e:
                print(f"[STAFF] Fehler: {e}")

    def schedule_update(self) -> None:
        """Mehrere Änderungen kurz hintereinander → nur EIN Edit."""
        if self._pending and not self._pending.done():
            return

        async def _run():
            await asyncio.sleep(self.UPDATE_DELAY)
            await self.update()
        self._pending = asyncio.create_task(_run())

    # ── Events ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await self.update()
        if self._loop_task is None:
            async def _loop():
                while True:
                    await asyncio.sleep(self.REFRESH_INTERVAL)
                    try:
                        await self.update()
                    except Exception as e:
                        print(f"[STAFF] Loop-Fehler: {e}")
            self._loop_task = asyncio.create_task(_loop())

    def _is_staff_guild(self, guild) -> bool:
        ch = self.bot.get_channel(STAFF_LIST_CHANNEL_ID)
        return ch is not None and guild is not None and ch.guild.id == guild.id

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not self._is_staff_guild(after.guild):
            return
        changed = {r.id for r in before.roles} ^ {r.id for r in after.roles}
        if changed & self._role_ids or (before.display_name != after.display_name
                                        and {r.id for r in after.roles} & self._role_ids):
            self.schedule_update()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if self._is_staff_guild(member.guild) and {r.id for r in member.roles} & self._role_ids:
            self.schedule_update()

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if after.id in self._role_ids and (before.name != after.name or before.color != after.color):
            self.schedule_update()


# ══════════════════════════════════════════════════════════════
#  3.  SLASH-COMMAND  /send
# ══════════════════════════════════════════════════════════════

class SendCommand(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def color_autocomplete(self, interaction: discord.Interaction, current: str):
        shown = ["dark", "rot", "grün", "blau", "blurple", "gelb", "orange", "lila", "pink", "gold", "weiß"]
        cur = current.lower()
        choices = [app_commands.Choice(name=f"{n}  (#{COLOR_PRESETS[n]:06X})", value=n) for n in shown if cur in n]
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", current.strip()):
            choices.insert(0, app_commands.Choice(name=f"Eigene Farbe: {current}", value=current.strip()))
        return choices[:25]

    @app_commands.command(name="send", description="Sendet eine Nachricht oder ein Embed als Bot in einen Channel.")
    @app_commands.describe(
        channel="Ziel-Channel",
        message="Text der Nachricht (\\n = neue Zeile)",
        title="Titel → macht daraus ein Embed",
        description="Zusätzlicher Text im Embed (unter der Nachricht)",
        color="Embed-Farbe, z.B. #ff0000 oder rot",
        image_url="Bild-URL (https://...)",
        ping_everyone="@everyone pingen?",
        image="Bild direkt hochladen (optional)",
    )
    @app_commands.autocomplete(color=color_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def send(self, interaction: discord.Interaction,
                   channel: discord.TextChannel,
                   message: str,
                   title: Optional[str] = None,
                   description: Optional[str] = None,
                   color: Optional[str] = None,
                   image_url: Optional[str] = None,
                   ping_everyone: Optional[bool] = False,
                   image: Optional[discord.Attachment] = None):

        member = interaction.user
        message = message.replace("\\n", "\n")
        description = description.replace("\\n", "\n") if description else None

        # ── Eingaben prüfen ──
        try:
            embed_color = parse_color(color)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        if image_url and not re.match(r"^https?://\S+$", image_url):
            await interaction.response.send_message("❌ `image_url` muss mit http:// oder https:// beginnen.", ephemeral=True)
            return
        if not channel.permissions_for(member).send_messages:
            await interaction.response.send_message(f"❌ Du darfst in {channel.mention} nicht schreiben.", ephemeral=True)
            return
        if ping_everyone and not channel.permissions_for(member).mention_everyone:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, @everyone zu pingen.", ephemeral=True)
            return
        bot_perms = channel.permissions_for(interaction.guild.me)
        if not (bot_perms.send_messages and bot_perms.embed_links):
            await interaction.response.send_message(
                f"❌ Dem Bot fehlen in {channel.mention} die Rechte *Nachrichten senden* / *Links einbetten*.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        use_embed = any((title, description, color, image_url))
        files: list[discord.File] = []
        if image is not None:
            files.append(await image.to_file(filename=_safe_filename(image.filename, 0)))

        content_parts = ["@everyone"] if ping_everyone else []
        embed = None
        if use_embed:
            body = message + (f"\n\n{description}" if description else "")
            # Schlichter "PASSED"-Stil: farbiger Balken, Titel, Text, Bild – kein Autor/Footer
            embed = discord.Embed(title=_cut(title, 256) if title else None,
                                  description=_cut(body, 4096), color=embed_color)
            if image_url:
                embed.set_image(url=image_url)
            elif files and _is_image(image.filename, image.content_type):
                embed.set_image(url=f"attachment://{files[0].filename}")
        else:
            content_parts.append(message)

        content = "\n".join(content_parts) or None
        if content and len(content) > 2000:
            await interaction.followup.send("❌ Nachricht zu lang (max. 2000 Zeichen ohne Embed). "
                                            "Tipp: gib einen `title` an → Embed erlaubt 4096 Zeichen.", ephemeral=True)
            return

        try:
            sent = await channel.send(
                content=content, embed=embed, files=files,
                allowed_mentions=discord.AllowedMentions(everyone=bool(ping_everyone), users=True, roles=False))
        except discord.Forbidden:
            await interaction.followup.send(f"❌ Keine Berechtigung, in {channel.mention} zu senden.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Senden fehlgeschlagen: `{e}`", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Gesendet in {channel.mention} → [Zur Nachricht]({sent.jump_url})", ephemeral=True)

        logger: Optional[ServerLogger] = self.bot.get_cog("ServerLogger")
        if logger and interaction.guild.id == LOG_GUILD_ID:
            e = log_embed("📨  /send benutzt", C_INFO, user=member)
            e.add_field(name="Von", value=_user(member), inline=True)
            e.add_field(name="Channel", value=_chan(channel), inline=True)
            e.add_field(name="Link", value=f"[Zur Nachricht]({sent.jump_url})", inline=True)
            e.add_field(name="Typ", value="Embed" if use_embed else "Nachricht", inline=True)
            e.add_field(name="@everyone", value="Ja" if ping_everyone else "Nein", inline=True)
            e.add_field(name="Inhalt", value=_code(message, 800), inline=False)
            await logger.send(e)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        print(f"[/send] Fehler: {error}")
        msg = f"❌ Fehler: `{getattr(error, 'original', error)}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


# ══════════════════════════════════════════════════════════════
#  Installation  (einziger Einstiegspunkt aus discord_key_bot.py)
# ══════════════════════════════════════════════════════════════

def install_server_features(bot: commands.Bot) -> None:
    """Hängt die neuen Features in den Bot ein, ohne bestehenden Code zu ändern.
    Nutzt setup_hook (läuft einmal beim Start, vor on_ready)."""
    ver = tuple(int(x) for x in re.findall(r"\d+", discord.__version__)[:2])
    if ver < (2, 4):
        print(f"[SERVER-FEATURES] WARNUNG: discord.py {discord.__version__} ist zu alt – "
              f"bitte 'pip install -U discord.py' ausführen (mind. 2.4).")
    original_setup_hook = bot.setup_hook

    async def setup_hook():
        await original_setup_hook()
        for cog_cls in (ServerLogger, AnnouncementSystem, StaffList, SendCommand):
            try:
                await bot.add_cog(cog_cls(bot))
                print(f"[SERVER-FEATURES] {cog_cls.__name__} geladen")
            except Exception as e:
                print(f"[SERVER-FEATURES] {cog_cls.__name__} Fehler: {e}")

        # Slash-Commands pro Server synchronisieren (sofort verfügbar)
        for gid in SLASH_GUILD_IDS:
            guild = discord.Object(id=gid)
            try:
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"[SLASH] {len(synced)} Command(s) in Guild {gid} synchronisiert")
            except discord.Forbidden:
                print(f"[SLASH] Guild {gid}: Bot fehlt der Scope 'applications.commands' – Bot neu einladen.")
            except Exception as e:
                print(f"[SLASH] Guild {gid}: Sync fehlgeschlagen: {e}")

    bot.setup_hook = setup_hook
