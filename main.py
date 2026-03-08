import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import csv
import os
import json
import asyncio
import re
import pytz
import aiohttp
from config import (
    CONTROL_CHANNEL_ID,
    VOTE_CONFIG,
    STATS_CONFIG,
    PING_SETTINGS_CHANNEL_ID,
    MOD_ROLE_ID,
    FAKE_EVERYONE_ROLE_ID,
    DUNGEON_CONFIG,
    DUNGEON_SETTINGS_CHANNEL_ID,
    PARTY_SIZE,
    DEFAULT_INACTIVITY_MINUTES,
    PRICE_PUBLIC_CHANNEL_ID,
    PRICE_REVIEW_CHANNEL_ID,
    PRICE_CHECK_CHANNEL_ID,
    PRICE_CHECKER_ROLE_ID,
    ITEMS_API_URL,
    UNSURE_VOTES_NEEDED,
    VALID_SERVERS,
    GUILD_ID,
    INVENTORY_CHANNEL_ID,
    NETWORTH_CHANNEL_ID,
    INVENTORY_CATEGORY_ID,
)

if os.path.exists('token.txt'):
    with open('token.txt', 'r') as f:
        TOKEN = f.read().strip()
else:
    print("Error: token.txt not found. Please create it and paste your token inside.")
    TOKEN = None

DATA_FILE = "player_trends.csv"
SETTINGS_FILE = "bot_settings.json"
DUNGEON_SETTINGS_FILE = "dungeon_settings.json"
channel_data = {}
channel_cooldowns = {}
last_manual_stats = {}

dungeon_parties: dict = {}  

REALM_PING_ROLES = {realm: ping_rid for _, (_, ping_rid, realm) in VOTE_CONFIG.items()}

SCHEDULES_FILE = "ping_schedules.json"

TIMEZONE_OPTIONS = [
    ("UTC+0  — London (GMT)",            "Europe/London"),
    ("UTC+1  — Paris, Berlin, Rome",     "Europe/Paris"),
    ("UTC+2  — Helsinki, Athens",        "Europe/Helsinki"),
    ("UTC+3  — Moscow, Istanbul",        "Europe/Moscow"),
    ("UTC+4  — Dubai",                   "Asia/Dubai"),
    ("UTC+5  — Karachi",                 "Asia/Karachi"),
    ("UTC+5:30 — Mumbai, Delhi",         "Asia/Kolkata"),
    ("UTC+6  — Dhaka",                   "Asia/Dhaka"),
    ("UTC+7  — Bangkok, Jakarta",        "Asia/Bangkok"),
    ("UTC+8  — Beijing, Singapore",      "Asia/Singapore"),
    ("UTC+9  — Tokyo, Seoul",            "Asia/Tokyo"),
    ("UTC+10 — Sydney",                  "Australia/Sydney"),
    ("UTC+11 — Solomon Islands",         "Pacific/Guadalcanal"),
    ("UTC+12 — Auckland",                "Pacific/Auckland"),
    ("UTC-1  — Azores",                  "Atlantic/Azores"),
    ("UTC-2  — South Georgia",           "Atlantic/South_Georgia"),
    ("UTC-3  — Buenos Aires, Brasília",  "America/Argentina/Buenos_Aires"),
    ("UTC-4  — Halifax, Caracas",        "America/Halifax"),
    ("UTC-5  — New York, Toronto",       "America/New_York"),
    ("UTC-6  — Chicago, Mexico City",    "America/Chicago"),
    ("UTC-7  — Denver, Phoenix",         "America/Denver"),
    ("UTC-8  — Los Angeles, Vancouver",  "America/Los_Angeles"),
    ("UTC-9  — Alaska",                  "America/Anchorage"),
    ("UTC-10 — Honolulu",                "Pacific/Honolulu"),
    ("UTC-12 — Baker Island",            "Etc/GMT+12"),
]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"enabled_realms": ["Elysium", "Arcane", "Cosmic"], "prediction_interval": 30}

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

settings = load_settings()

def load_dungeon_settings() -> dict:
    if os.path.exists(DUNGEON_SETTINGS_FILE):
        with open(DUNGEON_SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"inactivity_minutes": DEFAULT_INACTIVITY_MINUTES}

def save_dungeon_settings(data: dict):
    with open(DUNGEON_SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

dungeon_settings = load_dungeon_settings()

DUNGEON_USER_FILE = "dungeon_users.json"

def load_dungeon_users() -> dict:
    if os.path.exists(DUNGEON_USER_FILE):
        with open(DUNGEON_USER_FILE, "r") as f:
            return json.load(f)
    return {}

def save_dungeon_users(data: dict):
    with open(DUNGEON_USER_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_dungeon_user(user_id: int) -> dict:
    data = load_dungeon_users()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "channel_id": None,
            "no_auto_kick": False,
            "inactivity_minutes": None,
        }
        save_dungeon_users(data)
    return data[uid]

def set_dungeon_user(user_id: int, updates: dict):
    data = load_dungeon_users()
    uid = str(user_id)
    if uid not in data:
        get_dungeon_user(user_id)
        data = load_dungeon_users()
    data[uid].update(updates)
    save_dungeon_users(data)

DUNGEON_CHANNEL_TO_REALM = {cid: realm for cid, (_, realm) in DUNGEON_CONFIG.items()}
DUNGEON_REALM_TO_ROLE = {realm: role_id for _, (role_id, realm) in DUNGEON_CONFIG.items()}
DUNGEON_REALM_TO_CHANNEL = {realm: cid for cid, (_, realm) in DUNGEON_CONFIG.items()}

def get_party(realm: str) -> dict | None:
    """Return the active party for a realm, or None."""
    return dungeon_parties.get(realm)

def create_party(realm: str, user_id: int):
    dungeon_parties[realm] = {
        "members": [user_id],
        "last_activity": datetime.now(timezone.utc),
    }

def add_to_party(realm: str, user_id: int):
    dungeon_parties[realm]["members"].append(user_id)
    dungeon_parties[realm]["last_activity"] = datetime.now(timezone.utc)

def disband_party(realm: str):
    dungeon_parties.pop(realm, None)

def touch_party(realm: str):
    if realm in dungeon_parties:
        dungeon_parties[realm]["last_activity"] = datetime.now(timezone.utc)

def load_schedules() -> dict:
    if os.path.exists(SCHEDULES_FILE):
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_schedules(data: dict):
    with open(SCHEDULES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_data(user_id: int, member=None) -> dict:
    data = load_schedules()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "username": member.name if member else None,
            "channel_id": None,
            "snooze_until": None,
            "sleep_time": None,
            "wake_time": None,
            "timezone": "Europe/London",
            "is_muted": False,
            "muted_realms": [],
            "muted_everyone": False,
            "muted_dungeons": False,
            "muted_pinata": False,
            "schedule_realms": [],
            "schedule_everyone": False,
            "schedule_dungeons": False,
            "schedule_pinata": False,
        }
        save_schedules(data)
    elif member and not data[uid].get("username"):
        data[uid]["username"] = member.name
        save_schedules(data)
    return data[uid]

def set_user_data(user_id: int, updates: dict, member=None):
    data = load_schedules()
    uid = str(user_id)
    if uid not in data:
        get_user_data(user_id, member)
        data = load_schedules()
    if member:
        data[uid]["username"] = member.name
    data[uid].update(updates)
    save_schedules(data)

def parse_duration(raw: str):
    pattern = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?', raw.strip().lower())
    if not pattern or not raw.strip():
        return None
    days  = int(pattern.group(1) or 0)
    hours = int(pattern.group(2) or 0)
    mins  = int(pattern.group(3) or 0)
    total = days * 1440 + hours * 60 + mins
    return total if total > 0 else None

def local_timestamp(dt_utc: datetime, tz_str: str) -> str:
    try:
        tz = pytz.timezone(tz_str)
        local = dt_utc.astimezone(tz)
        local_str = local.strftime("%H:%M %Z")
    except Exception:
        local_str = "UTC"
    return f"<t:{int(dt_utc.timestamp())}:R> ({local_str})"

def format_settings_embed(user_data: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="🔔 Your Ping Settings",
        color=0x2b2d31,
        timestamp=datetime.now(timezone.utc)
    )
    tz_str = user_data.get("timezone", "Europe/London")

    snooze_until = user_data.get("snooze_until")
    if snooze_until and user_data.get("is_muted"):
        dt = datetime.fromisoformat(snooze_until)
        now = datetime.now(timezone.utc)
        if dt > now:
            muted_realms   = user_data.get("muted_realms", [])
            muted_dungeons = user_data.get("muted_dungeons", False)
            muted_pinata   = user_data.get("muted_pinata", False)
            everyone_muted = user_data.get("muted_everyone", False)
            parts = []
            if muted_realms:   parts.append(", ".join(muted_realms))
            if muted_pinata:   parts.append("Pinata (server)")
            if muted_dungeons: parts.append("Dungeon (server)")
            if everyone_muted: parts.append("@everyone")
            scope = " | ".join(parts) if parts else "none"
            snooze_str = (
                f"⏸️ **Snoozed** — resumes {local_timestamp(dt, tz_str)}\n"
                f"Muted: **{scope}**"
            )
        else:
            snooze_str = "✅ Active (snooze expired)"
    else:
        snooze_str = "✅ Active"
    embed.add_field(name="Ping Status", value=snooze_str, inline=False)

    sleep = user_data.get("sleep_time")
    wake  = user_data.get("wake_time")
    if sleep and wake:
        s_realms   = user_data.get("schedule_realms", [])
        s_dungeons = user_data.get("schedule_dungeons", False)
        s_pinata   = user_data.get("schedule_pinata", False)
        s_everyone = user_data.get("schedule_everyone", False)
        parts = []
        if s_realms:   parts.append(", ".join(s_realms))
        if s_pinata:   parts.append("Pinata (server)")
        if s_dungeons: parts.append("Dungeon (server)")
        if s_everyone: parts.append("@everyone")
        scope = " | ".join(parts) if parts else "none"
        try:
            tz_obj = pytz.timezone(tz_str)
            now_local = datetime.now(timezone.utc).astimezone(tz_obj)
            sleep_h, sleep_m = map(int, sleep.split(":"))
            wake_h,  wake_m  = map(int, wake.split(":"))
            next_sleep = now_local.replace(hour=sleep_h, minute=sleep_m, second=0, microsecond=0)
            next_wake  = now_local.replace(hour=wake_h,  minute=wake_m,  second=0, microsecond=0)
            if next_sleep <= now_local:
                next_sleep += timedelta(days=1)
            if next_wake <= now_local:
                next_wake  += timedelta(days=1)
            sleep_ts = f"<t:{int(next_sleep.timestamp())}:R>"
            wake_ts  = f"<t:{int(next_wake.timestamp())}:R>"
        except Exception:
            sleep_ts = wake_ts = ""
        schedule_str = (
            f"😴 **{sleep}** ({sleep_ts}) → ☀️ **{wake}** ({wake_ts}) `({tz_str})`\n"
            f"Affects: **{scope}**"
        )
    else:
        schedule_str = "No schedule set"
    embed.add_field(name="Sleep Schedule", value=schedule_str, inline=False)

    try:
        tz = pytz.timezone(tz_str)
        now_utc = datetime.now(timezone.utc)
        unix_ts = int(now_utc.timestamp())
        tz_display = f"`{tz_str}` — currently <t:{unix_ts}:t>"
    except Exception:
        tz_display = "`Europe/London`"
    embed.add_field(name="Your Timezone", value=tz_display, inline=False)

    embed.set_footer(text=f"Settings for {member.display_name}")
    return embed

def is_in_sleep_window(current, sleep, wake):
    if sleep == wake:
        return False
    if sleep < wake:
        return sleep <= current < wake
    return current >= sleep or current < wake

def log_data(realm, player_count, vote_progress=None):
    now = datetime.now()
    file_exists = os.path.isfile(DATA_FILE)
    v_prog = int(vote_progress) if vote_progress is not None else 0
    with open(DATA_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Timestamp', 'Day', 'Hour', 'Realm', 'Players', 'Vote_Progress'])
        writer.writerow([now.strftime('%Y-%m-%d %H:%M:%S'), now.strftime('%A'), now.hour, realm, player_count, v_prog])

def get_trend_analysis(realm_name):
    if not os.path.isfile(DATA_FILE): return {"avg": 0, "vpm": 0.2}
    now = datetime.now()
    hour = now.hour
    counts, velocity_samples = [], []
    try:
        with open(DATA_FILE, mode='r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            for i, row in enumerate(rows):
                if row['Realm'] != realm_name: continue
                p, v, h = int(row['Players']), int(row['Vote_Progress'] or 0), int(row['Hour'])
                if h in [(hour-1)%24, hour, (hour+1)%24]:
                    counts.append(p)
                if i > 0 and rows[i-1]['Realm'] == realm_name:
                    prev_v = int(rows[i-1]['Vote_Progress'] or 0)
                    if v > prev_v:
                        t1 = datetime.strptime(rows[i-1]['Timestamp'], '%Y-%m-%d %H:%M:%S')
                        t2 = datetime.strptime(row['Timestamp'], '%Y-%m-%d %H:%M:%S')
                        mins = (t2 - t1).total_seconds() / 60
                        if 0 < mins < 120: velocity_samples.append((v - prev_v) / mins)
    except: pass
    avg = sum(counts) // len(counts) if counts else 0
    vpm = sum(velocity_samples) / len(velocity_samples) if velocity_samples else 0.2
    return {"avg": avg, "vpm": max(0.05, vpm)}

class BotControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if child.custom_id in ["Elysium", "Arcane", "Cosmic"]:
                if child.custom_id in settings["enabled_realms"]:
                    child.style = discord.ButtonStyle.green
                    child.label = f"{child.custom_id}: ON"
                else:
                    child.style = discord.ButtonStyle.red
                    child.label = f"{child.custom_id}: OFF"
            if child.custom_id == "interval_label":
                child.label = f"Interval: {settings['prediction_interval']}m"

    @discord.ui.button(label="Elysium: ON", style=discord.ButtonStyle.green, custom_id="Elysium", row=0)
    async def toggle_elysium(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.toggle_realm("Elysium")
        self.update_buttons()
        save_settings()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Arcane: ON", style=discord.ButtonStyle.green, custom_id="Arcane", row=0)
    async def toggle_arcane(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.toggle_realm("Arcane")
        self.update_buttons()
        save_settings()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cosmic: ON", style=discord.ButtonStyle.green, custom_id="Cosmic", row=0)
    async def toggle_cosmic(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.toggle_realm("Cosmic")
        self.update_buttons()
        save_settings()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Interval", style=discord.ButtonStyle.grey, custom_id="interval_label", row=1, disabled=True)
    async def interval_display(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="➖ 5m", style=discord.ButtonStyle.blurple, custom_id="dec_5", row=1)
    async def decrease_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if settings["prediction_interval"] > 5:
            settings["prediction_interval"] -= 5
            self.update_buttons()
            save_settings()
            auto_filler.change_interval(minutes=settings["prediction_interval"])
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Min interval is 5m.", ephemeral=True)

    @discord.ui.button(label="➕ 5m", style=discord.ButtonStyle.blurple, custom_id="inc_5", row=1)
    async def increase_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if settings["prediction_interval"] < 120:
            settings["prediction_interval"] += 5
            self.update_buttons()
            save_settings()
            auto_filler.change_interval(minutes=settings["prediction_interval"])
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Max interval is 120m.", ephemeral=True)

    def toggle_realm(self, realm):
        if realm in settings["enabled_realms"]:
            settings["enabled_realms"].remove(realm)
        else:
            settings["enabled_realms"].append(realm)

class ClearLogsView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Clear Channel Logs", style=discord.ButtonStyle.danger, custom_id="clear_logs_button")
    async def clear_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.guild_permissions.manage_messages:
            await interaction.response.defer(ephemeral=True)
            await interaction.channel.purge(limit=100)
            await interaction.followup.send("Logs cleared!", ephemeral=True)
        else:
            await interaction.response.send_message("No permission.", ephemeral=True)

class TimezoneSelectView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot
        options = [
            discord.SelectOption(label=label, value=tz_value)
            for label, tz_value in TIMEZONE_OPTIONS
        ]
        self.add_item(TimezoneSelect(options, bot))

class TimezoneSelect(discord.ui.Select):
    def __init__(self, options, bot):
        super().__init__(
            placeholder="Select your timezone...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="timezone_select"
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        tz_str = self.values[0]
        set_user_data(interaction.user.id, {"timezone": tz_str}, member=interaction.user)
        try:
            tz = pytz.timezone(tz_str)
            now_local = datetime.now(timezone.utc).astimezone(tz)
            label = next((l for l, v in TIMEZONE_OPTIONS if v == tz_str), tz_str)
            await interaction.response.send_message(
                f"✅ Timezone set to **{label}**\nYour current local time: **{now_local.strftime('%H:%M')}**",
                ephemeral=False,
                delete_after=30
            )
        except Exception:
            await interaction.response.send_message(
                f"✅ Timezone updated to `{tz_str}`.",
                ephemeral=False,
                delete_after=30
            )
        await refresh_settings_panel(interaction.channel, interaction.user, self.bot)

class SnoozeScopeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.selected_realms = []
        self.mute_pinata     = False
        self.mute_dungeon    = False
        self.mute_everyone   = False

    @discord.ui.button(label="Elysium", style=discord.ButtonStyle.grey, custom_id="scope_elysium", row=0)
    async def toggle_elysium(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Elysium", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Arcane", style=discord.ButtonStyle.grey, custom_id="scope_arcane", row=0)
    async def toggle_arcane(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Arcane", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cosmic", style=discord.ButtonStyle.grey, custom_id="scope_cosmic", row=0)
    async def toggle_cosmic(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Cosmic", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Pinata (server): Unmuted", style=discord.ButtonStyle.grey, custom_id="scope_pinata", row=1)
    async def toggle_pinata(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_pinata = not self.mute_pinata
        button.style = discord.ButtonStyle.red if self.mute_pinata else discord.ButtonStyle.grey
        button.label = "Pinata (server): Muted" if self.mute_pinata else "Pinata (server): Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Dungeon (server): Unmuted", style=discord.ButtonStyle.grey, custom_id="scope_dungeon", row=1)
    async def toggle_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_dungeon = not self.mute_dungeon
        button.style = discord.ButtonStyle.red if self.mute_dungeon else discord.ButtonStyle.grey
        button.label = "Dungeon (server): Muted" if self.mute_dungeon else "Dungeon (server): Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="@everyone: Unmuted", style=discord.ButtonStyle.grey, custom_id="scope_everyone", row=1)
    async def toggle_everyone(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_everyone = not self.mute_everyone
        button.style = discord.ButtonStyle.red if self.mute_everyone else discord.ButtonStyle.grey
        button.label = "@everyone: Muted" if self.mute_everyone else "@everyone: Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Next — Set Duration", style=discord.ButtonStyle.green, custom_id="scope_confirm", row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any([self.selected_realms, self.mute_pinata, self.mute_dungeon, self.mute_everyone]):
            await interaction.response.send_message(
                "❌ Please select at least one realm or ping type to snooze.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            SnoozeDurationModal(self.bot, self.selected_realms, self.mute_pinata, self.mute_dungeon, self.mute_everyone)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="scope_cancel", row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    def _toggle_realm(self, realm, button):
        if realm in self.selected_realms:
            self.selected_realms.remove(realm)
            button.style = discord.ButtonStyle.grey
        else:
            self.selected_realms.append(realm)
            button.style = discord.ButtonStyle.blurple

class ScheduleScopeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.selected_realms = []
        self.mute_pinata     = False
        self.mute_dungeon    = False
        self.mute_everyone   = False

    @discord.ui.button(label="Elysium", style=discord.ButtonStyle.grey, custom_id="sched_elysium", row=0)
    async def toggle_elysium(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Elysium", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Arcane", style=discord.ButtonStyle.grey, custom_id="sched_arcane", row=0)
    async def toggle_arcane(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Arcane", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cosmic", style=discord.ButtonStyle.grey, custom_id="sched_cosmic", row=0)
    async def toggle_cosmic(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._toggle_realm("Cosmic", button)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Pinata (server): Unmuted", style=discord.ButtonStyle.grey, custom_id="sched_pinata", row=1)
    async def toggle_pinata(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_pinata = not self.mute_pinata
        button.style = discord.ButtonStyle.red if self.mute_pinata else discord.ButtonStyle.grey
        button.label = "Pinata (server): Muted" if self.mute_pinata else "Pinata (server): Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Dungeon (server): Unmuted", style=discord.ButtonStyle.grey, custom_id="sched_dungeon", row=1)
    async def toggle_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_dungeon = not self.mute_dungeon
        button.style = discord.ButtonStyle.red if self.mute_dungeon else discord.ButtonStyle.grey
        button.label = "Dungeon (server): Muted" if self.mute_dungeon else "Dungeon (server): Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="@everyone: Unmuted", style=discord.ButtonStyle.grey, custom_id="sched_everyone", row=1)
    async def toggle_everyone(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_everyone = not self.mute_everyone
        button.style = discord.ButtonStyle.red if self.mute_everyone else discord.ButtonStyle.grey
        button.label = "@everyone: Muted" if self.mute_everyone else "@everyone: Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Next — Set Times", style=discord.ButtonStyle.green, custom_id="sched_confirm", row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any([self.selected_realms, self.mute_pinata, self.mute_dungeon, self.mute_everyone]):
            await interaction.response.send_message(
                "❌ Please select at least one option.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ScheduleTimesModal(self.bot, self.selected_realms, self.mute_pinata, self.mute_dungeon, self.mute_everyone)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="sched_cancel", row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    def _toggle_realm(self, realm, button):
        if realm in self.selected_realms:
            self.selected_realms.remove(realm)
            button.style = discord.ButtonStyle.grey
        else:
            self.selected_realms.append(realm)
            button.style = discord.ButtonStyle.blurple

class SnoozeDurationModal(discord.ui.Modal, title="⏸️ Snooze Duration"):
    duration = discord.ui.TextInput(
        label="How long? (e.g. 2h, 30m, 1h30m, 2d)",
        placeholder="2h",
        max_length=10
    )

    def __init__(self, bot, realms, mute_pinata, mute_dungeon, mute_everyone):
        super().__init__()
        self.bot = bot
        self.realms = realms
        self.mute_pinata = mute_pinata
        self.mute_dungeon = mute_dungeon
        self.mute_everyone = mute_everyone

    async def on_submit(self, interaction: discord.Interaction):
        minutes = parse_duration(self.duration.value)
        if minutes is None:
            await interaction.response.send_message(
                "❌ Couldn't parse that. Try `2h`, `30m`, `1h30m`, or `2d`.",
                ephemeral=True
            )
            return

        snooze_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        guild = interaction.guild
        muted_realms = []

        for realm in self.realms:
            role_id = REALM_PING_ROLES.get(realm)
            if role_id:
                role = guild.get_role(role_id)
                if role and role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(role, reason="Ping snooze")
                        muted_realms.append(realm)
                    except discord.Forbidden:
                        pass

        if self.mute_dungeon:
            for role_id in DUNGEON_REALM_TO_ROLE.values():
                role = guild.get_role(role_id)
                if role and role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(role, reason="Dungeon ping snooze")
                    except discord.Forbidden:
                        pass

        if (self.mute_pinata or self.mute_everyone) and FAKE_EVERYONE_ROLE_ID:
            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
            if fake_everyone and fake_everyone in interaction.user.roles:
                try:
                    await interaction.user.remove_roles(fake_everyone, reason="Pinata/@everyone snooze")
                except discord.Forbidden:
                    pass

        set_user_data(interaction.user.id, {
            "snooze_until": snooze_until.isoformat(),
            "is_muted": True,
            "muted_realms": muted_realms,
            "muted_dungeons": ["Elysium", "Arcane", "Cosmic"] if self.mute_dungeon else [],
            "muted_pinata": self.mute_pinata,
            "muted_everyone": self.mute_everyone,
        }, member=interaction.user)

        user_data = get_user_data(interaction.user.id)
        tz_str = user_data.get("timezone", "Europe/London")
        parts = []
        if muted_realms:       parts.append(", ".join(muted_realms))
        if self.mute_pinata:   parts.append("Pinata (server)")
        if self.mute_dungeon:  parts.append("Dungeon (server)")
        if self.mute_everyone: parts.append("@everyone")
        scope = " | ".join(parts) if parts else "none"

        await interaction.response.send_message(
            f"✅ Pings snoozed!\n"
            f"**Muted:** {scope}\n"
            f"**Resumes:** {local_timestamp(snooze_until, tz_str)}",
            ephemeral=False,
            delete_after=30
        )
        await refresh_settings_panel(interaction.channel, interaction.user, self.bot)

class ScheduleTimesModal(discord.ui.Modal, title="😴 Sleep Schedule Times"):
    sleep_time = discord.ui.TextInput(
        label="Sleep time (24h, your local timezone)",
        placeholder="23:00",
        max_length=5
    )
    wake_time = discord.ui.TextInput(
        label="Wake time (24h, your local timezone)",
        placeholder="07:00",
        max_length=5
    )

    def __init__(self, bot, realms, mute_pinata, mute_dungeon, mute_everyone):
        super().__init__()
        self.bot = bot
        self.realms = realms
        self.mute_pinata = mute_pinata
        self.mute_dungeon = mute_dungeon
        self.mute_everyone = mute_everyone

    async def on_submit(self, interaction: discord.Interaction):
        sleep = self.sleep_time.value.strip()
        wake  = self.wake_time.value.strip()

        try:
            datetime.strptime(sleep, "%H:%M")
            datetime.strptime(wake, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid time format. Use 24h like `23:00` or `07:30`.", ephemeral=True
            )
            return

        user_data = get_user_data(interaction.user.id)
        tz_str = user_data.get("timezone", "Europe/London")

        set_user_data(interaction.user.id, {
            "sleep_time": sleep,
            "wake_time": wake,
            "schedule_realms": self.realms,
            "schedule_dungeons": self.mute_dungeon,
            "schedule_pinata": self.mute_pinata,
            "schedule_everyone": self.mute_everyone,
        }, member=interaction.user)

        parts = []
        if self.realms:        parts.append(", ".join(self.realms))
        if self.mute_pinata:   parts.append("Pinata (server)")
        if self.mute_dungeon:  parts.append("Dungeon (server)")
        if self.mute_everyone: parts.append("@everyone")
        scope = " | ".join(parts) if parts else "none"

        await interaction.response.send_message(
            f"✅ Schedule set!\n"
            f"😴 **{sleep}** → ☀️ **{wake}** `({tz_str})`\n"
            f"**Affects:** {scope}",
            ephemeral=False,
            delete_after=30
        )
        await refresh_settings_panel(interaction.channel, interaction.user, self.bot)

class OpenSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="⚙️ Manage My Pings",
        style=discord.ButtonStyle.blurple,
        custom_id="open_ping_settings"
    )
    async def open_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild  = interaction.guild
        member = interaction.user
        data   = load_schedules()
        uid    = str(member.id)

        existing_channel_id = data.get(uid, {}).get("channel_id")
        if existing_channel_id:
            existing_channel = guild.get_channel(existing_channel_id)
            if existing_channel:
                await interaction.response.send_message(
                    f"You already have a settings channel: {existing_channel.mention}", ephemeral=True
                )
                return
            set_user_data(member.id, {"channel_id": None}, member=member)

        settings_channel = guild.get_channel(PING_SETTINGS_CHANNEL_ID)
        category = settings_channel.category if settings_channel else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member:             discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if MOD_ROLE_ID:
            mod_role = guild.get_role(MOD_ROLE_ID)
            if mod_role:
                overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        channel_name = f"pings-{member.name}".lower().replace(" ", "-")[:100]
        new_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ping settings for {member}"
        )

        set_user_data(member.id, {"channel_id": new_channel.id}, member=member)

        user_data = get_user_data(member.id)
        embed = format_settings_embed(user_data, member)
        await new_channel.send(
            content=f"👋 Hey {member.mention}! Manage your ping settings below.",
            embed=embed,
            view=UserSettingsView(interaction.client)
        )

        await interaction.response.send_message(
            f"✅ Your private settings channel: {new_channel.mention}", ephemeral=True
        )

class UserSettingsView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⏸️ Snooze Pings", style=discord.ButtonStyle.blurple, custom_id="snooze_pings", row=0)
    async def snooze(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SnoozeScopeView(self.bot)
        await interaction.response.send_message(
            "**Select which pings to snooze**, then click Next:",
            view=view,
            ephemeral=False,
            delete_after=120
        )

    @discord.ui.button(label="▶️ Resume Now", style=discord.ButtonStyle.green, custom_id="resume_pings", row=0)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = get_user_data(interaction.user.id)
        guild     = interaction.guild
        restored  = []

        for realm in user_data.get("muted_realms", []):
            role_id = REALM_PING_ROLES.get(realm)
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Ping resume")
                        restored.append(f"Vote/{realm}")
                    except discord.Forbidden:
                        pass

        if user_data.get("muted_dungeons"):
            for realm, role_id in DUNGEON_REALM_TO_ROLE.items():
                role = guild.get_role(role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Dungeon ping resume")
                        restored.append("Dungeon (server)")
                        break
                    except discord.Forbidden:
                        pass

        needs_everyone = user_data.get("muted_everyone") or user_data.get("muted_pinata")
        if needs_everyone and FAKE_EVERYONE_ROLE_ID:
            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
            if fake_everyone and fake_everyone not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(fake_everyone, reason="Ping resume")
                    if user_data.get("muted_pinata"):   restored.append("Pinata (server)")
                    if user_data.get("muted_everyone"): restored.append("@everyone")
                except discord.Forbidden:
                    pass

        set_user_data(interaction.user.id, {
            "snooze_until": None,
            "is_muted": False,
            "muted_realms": [],
            "muted_dungeons": False,
            "muted_pinata": False,
            "muted_everyone": False,
        }, member=interaction.user)

        msg = f"✅ Pings resumed! Re-enabled: **{', '.join(restored)}**" if restored else "✅ Pings are already active."
        await interaction.response.send_message(msg, ephemeral=not bool(restored), delete_after=30)
        await refresh_settings_panel(interaction.channel, interaction.user, self.bot)

    @discord.ui.button(label="😴 Set Sleep Schedule", style=discord.ButtonStyle.grey, custom_id="set_schedule", row=1)
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ScheduleScopeView(self.bot)
        await interaction.response.send_message(
            "**Select which pings your sleep schedule should affect**, then click Next:",
            view=view,
            ephemeral=False,
            delete_after=120
        )

    @discord.ui.button(label="🗑️ Clear Schedule", style=discord.ButtonStyle.danger, custom_id="clear_schedule", row=1)
    async def clear_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_user_data(interaction.user.id, {
            "sleep_time": None,
            "wake_time": None,
            "schedule_realms": [],
            "schedule_dungeons": [],
            "schedule_pinata": [],
            "schedule_everyone": False,
        }, member=interaction.user)
        await interaction.response.send_message(
            "✅ Sleep schedule cleared.", ephemeral=False, delete_after=30
        )
        await refresh_settings_panel(interaction.channel, interaction.user, self.bot)

    @discord.ui.button(label="🌍 Update Timezone", style=discord.ButtonStyle.grey, custom_id="update_timezone", row=2)
    async def update_timezone(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TimezoneSelectView(self.bot)
        await interaction.response.send_message(
            "**Select your timezone from the dropdown below:**",
            view=view,
            ephemeral=False,
            delete_after=120
        )

    @discord.ui.button(label="❌ Close & Delete Channel", style=discord.ButtonStyle.danger, custom_id="delete_settings_channel", row=3)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_user_data(interaction.user.id, {
            "channel_id": None,
            "snooze_until": None,
            "sleep_time": None,
            "wake_time": None,
            "timezone": "Europe/London",
            "is_muted": False,
            "muted_realms": [],
            "muted_everyone": False,
            "muted_dungeons": False,
            "muted_pinata": False,
            "schedule_realms": [],
            "schedule_everyone": False,
            "schedule_dungeons": False,
            "schedule_pinata": False,
        }, member=interaction.user)
        await interaction.response.send_message("👋 Closing your settings channel...", ephemeral=False)
        await interaction.channel.delete(reason="User closed their ping settings channel")

async def refresh_settings_panel(channel, member, bot):
    user_data = get_user_data(member.id)
    embed = format_settings_embed(user_data, member)
    try:
        async for msg in channel.history(limit=20):
            if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "🔔 Your Ping Settings":
                await msg.delete()
                break
    except Exception:
        pass
    await channel.send(embed=embed, view=UserSettingsView(bot))

async def send_vote_update(channel_id, num, label, is_bot=False, user_mention=None):
    now = datetime.now()
    log_cid, ping_rid, realm = VOTE_CONFIG[channel_id]
    channel = bot.get_channel(channel_id)
    if not channel: return

    channel_data[channel_id] = (num, now)
    bar = "🟩" * round((num/100)*10) + "⬜" * (10 - round((num/100)*10))
    box_color = 0x95a5a6 if is_bot else (0xFF0000 if num >= 70 else 0x3498db)

    should_ping = (
        num >= 90 or
        (70 <= num <= 80 and now >= (channel_cooldowns.get(channel_id, datetime.min) + timedelta(minutes=15))) or
        (95 <= num <= 100)
    )

    if num >= 99:
        display_text = f"🎉 **PINATA STARTING!** 🎉\n{'🟥🟧🟨🟩🟦🟪' * 2}"[:35]
    else:
        display_text = f"**Current Vote Party: {num} / 100**\n{bar}\n`Source: {label}`"

    embed = discord.Embed(description=display_text, color=box_color)

    if 95 <= num <= 100:
        mention = f"<@&{FAKE_EVERYONE_ROLE_ID}>" if FAKE_EVERYONE_ROLE_ID else "@everyone"
    else:
        mention = f"<@&{ping_rid}>" if ping_rid != 0 else None

    await channel.send(content=mention if should_ping else None, embed=embed)

    if 70 <= num <= 80 and should_ping:
        channel_cooldowns[channel_id] = now

    log_chan = bot.get_channel(log_cid)
    if log_chan:
        log_emb = discord.Embed(title="Moderator Log", color=0x2b2d31, timestamp=now)
        log_emb.add_field(name="User", value=user_mention if user_mention else "@Bot", inline=False)
        log_emb.add_field(name="Number", value=str(num), inline=False)
        log_emb.add_field(name="Source", value=f"# {realm}", inline=False)
        await log_chan.send(embed=log_emb, view=ClearLogsView())


def build_party_embed(realm: str, party: dict, party_size: int = PARTY_SIZE) -> discord.Embed:
    """Build an embed showing current party status."""
    members = party["members"]
    filled = len(members)
    slots = "".join([f"<@{uid}>" for uid in members])
    slots += "  ·  🔲" * (party_size - filled)

    if filled >= party_size:
        color = 0x2ecc71
        title = f"⚔️ {realm} Dungeon Party — FULL!"
    else:
        color = 0x3498db
        title = f"⚔️ {realm} Dungeon Party — {filled}/{party_size}"

    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Members", value=slots or "None", inline=False)
    embed.add_field(
        name="Spots Remaining",
        value=f"**{party_size - filled}** open" if filled < party_size else "✅ Party is ready!",
        inline=False,
    )
    embed.set_footer(text="Use /join or /leave in this channel")
    return embed


def format_dungeon_settings_embed(user_data: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ Your Dungeon Settings",
        color=0x2b2d31,
        timestamp=datetime.now(timezone.utc),
    )

    personal_mins = user_data.get("inactivity_minutes")
    server_mins   = dungeon_settings.get("inactivity_minutes", DEFAULT_INACTIVITY_MINUTES)
    if user_data.get("no_auto_kick", False):
        timer_str = "🛡️ **Opted out** — you will never be auto-kicked"
    elif personal_mins is not None:
        timer_str = f"⏱️ **{personal_mins} minutes** *(server default: {server_mins}m)*"
    else:
        timer_str = f"⏱️ **{server_mins} minutes** *(server default)*"
    embed.add_field(name="Inactivity Timer", value=timer_str, inline=False)

    no_kick = user_data.get("no_auto_kick", False)
    embed.add_field(
        name="🛡️ Auto-Kick Opt-Out",
        value="✅ Enabled — you won't be auto-kicked" if no_kick else "❌ Disabled — server/personal timer applies",
        inline=False,
    )

    embed.set_footer(text=f"Settings for {member.display_name}")
    return embed


async def refresh_dungeon_settings_panel(channel, member, bot):
    user_data = get_dungeon_user(member.id)
    embed = format_dungeon_settings_embed(user_data, member)
    try:
        async for msg in channel.history(limit=20):
            if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "⚔️ Your Dungeon Settings":
                await msg.delete()
                break
    except Exception:
        pass
    await channel.send(embed=embed, view=UserDungeonSettingsView(bot))


class DungeonTimerModal(discord.ui.Modal, title="⏱️ Set Your Inactivity Timer"):
    minutes = discord.ui.TextInput(
        label="Minutes before auto-kick (10–480)",
        placeholder="e.g. 30",
        max_length=3,
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.minutes.value.strip())
            if not (10 <= value <= 480):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a whole number between 10 and 480.", ephemeral=True
            )
            return
        set_dungeon_user(interaction.user.id, {"inactivity_minutes": value, "no_auto_kick": False})
        await interaction.response.send_message(
            f"✅ Your personal inactivity timer set to **{value} minutes**.\n"
            f"If nobody joins your party within that time, you'll be kicked automatically.",
            ephemeral=False,
            delete_after=30,
        )
        await refresh_dungeon_settings_panel(interaction.channel, interaction.user, self.bot)


class UserDungeonSettingsView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⏱️ Set My Inactivity Timer", style=discord.ButtonStyle.blurple, custom_id="dset_timer", row=0)
    async def set_timer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DungeonTimerModal(self.bot))

    @discord.ui.button(label="🔄 Use Server Default", style=discord.ButtonStyle.grey, custom_id="dset_timer_reset", row=0)
    async def reset_timer(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_dungeon_user(interaction.user.id, {"inactivity_minutes": None, "no_auto_kick": False})
        server_mins = dungeon_settings.get("inactivity_minutes", DEFAULT_INACTIVITY_MINUTES)
        await interaction.response.send_message(
            f"✅ Reset to server default: **{server_mins} minutes**.",
            ephemeral=False,
            delete_after=20,
        )
        await refresh_dungeon_settings_panel(interaction.channel, interaction.user, self.bot)

    @discord.ui.button(label="🛡️ Toggle Auto-Kick Opt-Out", style=discord.ButtonStyle.grey, custom_id="dset_kick", row=1)
    async def toggle_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = get_dungeon_user(interaction.user.id)
        new_val = not user_data.get("no_auto_kick", False)
        set_dungeon_user(interaction.user.id, {"no_auto_kick": new_val})
        if new_val:
            msg = "🛡️ Auto-kick opt-out **enabled** — you will never be automatically removed from a party."
        else:
            mins = user_data.get("inactivity_minutes") or dungeon_settings.get("inactivity_minutes", DEFAULT_INACTIVITY_MINUTES)
            msg = f"🛡️ Auto-kick opt-out **disabled** — your timer is back to **{mins} minutes**."
        await interaction.response.send_message(msg, ephemeral=False, delete_after=30)
        await refresh_dungeon_settings_panel(interaction.channel, interaction.user, self.bot)

    @discord.ui.button(label="❌ Close & Delete Channel", style=discord.ButtonStyle.danger, custom_id="dset_delete", row=2)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_dungeon_user(interaction.user.id, {
            "channel_id": None,
            "no_auto_kick": False,
            "inactivity_minutes": None,
        })
        await interaction.response.send_message("👋 Closing your dungeon settings channel...", ephemeral=False)
        await interaction.channel.delete(reason="User closed their dungeon settings channel")


class OpenDungeonSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="⚔️ Manage My Dungeon Settings",
        style=discord.ButtonStyle.blurple,
        custom_id="open_dungeon_settings",
    )
    async def open_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild  = interaction.guild
        member = interaction.user
        data   = load_dungeon_users()
        uid    = str(member.id)

        existing_channel_id = data.get(uid, {}).get("channel_id")
        if existing_channel_id:
            existing_channel = guild.get_channel(existing_channel_id)
            if existing_channel:
                await interaction.response.send_message(
                    f"You already have a settings channel: {existing_channel.mention}", ephemeral=True
                )
                return
            set_dungeon_user(member.id, {"channel_id": None})

        settings_channel = guild.get_channel(DUNGEON_SETTINGS_CHANNEL_ID)
        category = settings_channel.category if settings_channel else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member:             discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if MOD_ROLE_ID:
            mod_role = guild.get_role(MOD_ROLE_ID)
            if mod_role:
                overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        channel_name = f"dungeons-{member.name}".lower().replace(" ", "-")[:100]
        new_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Dungeon settings for {member}",
        )

        set_dungeon_user(member.id, {"channel_id": new_channel.id})
        user_data = get_dungeon_user(member.id)
        embed = format_dungeon_settings_embed(user_data, member)

        await new_channel.send(
            content=f"👋 Hey {member.mention}! Manage your dungeon settings below.",
            embed=embed,
            view=UserDungeonSettingsView(interaction.client),
        )
        await interaction.response.send_message(
            f"✅ Your private dungeon settings channel: {new_channel.mention}", ephemeral=True
        )


async def post_dungeon_settings_panel(channel: discord.TextChannel):
    """Post the public entry-point embed in #dungeon-settings — only if not already there."""
    try:
        async for msg in channel.history(limit=20):
            if msg.author == channel.guild.me and msg.embeds and msg.embeds[0].title == "⚔️ Dungeon Settings":
                return
    except Exception:
        pass

    embed = discord.Embed(
        title="⚔️ Dungeon Settings",
        description=(
            "Click the button below to open your **private dungeon settings channel**.\n\n"
            "From there you can:\n"
            "• ⏱️ **Set your personal inactivity timer** — how long before you're auto-kicked if nobody joins your party\n"
            "• 🔄 **Reset to server default** — go back to the server's global timer\n"
            "• 🛡️ **Opt out of auto-kick entirely** — stay in the party no matter how long it takes\n"
            "• ❌ **Close** your settings channel when you're done\n\n"
            "_Your settings are saved even after closing the channel._"
        ),
        color=0x2b2d31,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Your settings are saved even after closing the channel.")
    await channel.send(embed=embed, view=OpenDungeonSettingsView())



intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.tree.command(name="join", description="Join (or create) the dungeon party for this realm.")
async def dungeon_join(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    realm = DUNGEON_CHANNEL_TO_REALM.get(channel_id)

    if realm is None:
        await interaction.response.send_message(
            "❌ This command can only be used in a dungeon channel.", ephemeral=True
        )
        return

    user_id = interaction.user.id
    party = get_party(realm)

    if party and user_id in party["members"]:
        await interaction.response.send_message("❌ You're already in the party!", ephemeral=True)
        return

    if party and len(party["members"]) >= PARTY_SIZE:
        await interaction.response.send_message(
            "❌ The party is already full. Wait for a spot to open!", ephemeral=True
        )
        return

    ping_role_id = DUNGEON_REALM_TO_ROLE.get(realm)
    role_mention = f"<@&{ping_role_id}>" if ping_role_id else ""

    if party is None:
        create_party(realm, user_id)
        embed = build_party_embed(realm, get_party(realm))
        await interaction.response.send_message(
            content=(
                f"{role_mention} ⚔️ **{interaction.user.display_name}** has opened a new "
                f"**{realm} Dungeon Party!** Looking for {PARTY_SIZE - 1} more adventurers."
            ),
            embed=embed,
        )
    else:
        add_to_party(realm, user_id)
        party = get_party(realm)
        embed = build_party_embed(realm, party)
        filled = len(party["members"])

        if filled >= PARTY_SIZE:
            member_mentions = " ".join(f"<@{uid}>" for uid in party["members"])
            await interaction.response.send_message(
                content=(
                    f"{role_mention} 🎉 **{realm} Dungeon Party is FULL and READY!** "
                    f"Good luck, adventurers! {member_mentions}"
                ),
                embed=embed,
            )
            disband_party(realm)
        else:
            await interaction.response.send_message(
                content=(
                    f"{role_mention} ⚔️ **{interaction.user.display_name}** joined the "
                    f"**{realm} Dungeon Party!** Still need {PARTY_SIZE - filled} more."
                ),
                embed=embed,
            )


@bot.tree.command(name="leave", description="Leave the dungeon party for this realm.")
async def dungeon_leave(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    realm = DUNGEON_CHANNEL_TO_REALM.get(channel_id)

    if realm is None:
        await interaction.response.send_message(
            "❌ This command can only be used in a dungeon channel.", ephemeral=True
        )
        return

    user_id = interaction.user.id
    party = get_party(realm)

    if party is None or user_id not in party["members"]:
        await interaction.response.send_message(
            "❌ You're not in a party right now.", ephemeral=True
        )
        return

    if len(party["members"]) == 1:
        disband_party(realm)
        await interaction.response.send_message(
            f"🚪 **{interaction.user.display_name}** has abandoned the **{realm} Dungeon Party**. "
            f"It has been disbanded."
        )
    else:
        party["members"].remove(user_id)
        touch_party(realm)
        embed = build_party_embed(realm, party)
        await interaction.response.send_message(
            content=(
                f"🚪 **{interaction.user.display_name}** left the **{realm} Dungeon Party**. "
                f"Still looking for {PARTY_SIZE - len(party['members'])} more!"
            ),
            embed=embed,
        )


@bot.tree.command(name="party", description="Check the current dungeon party status for this realm.")
async def dungeon_party_status(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    realm = DUNGEON_CHANNEL_TO_REALM.get(channel_id)

    if realm is None:
        await interaction.response.send_message(
            "❌ This command can only be used in a dungeon channel.", ephemeral=True
        )
        return

    party = get_party(realm)
    if party is None:
        await interaction.response.send_message(
            f"No active **{realm}** dungeon party right now. Use `/join` to start one!",
            ephemeral=True,
        )
    else:
        embed = build_party_embed(realm, party)
        await interaction.response.send_message(embed=embed, ephemeral=True)


@tasks.loop(minutes=1)
async def check_dungeon_inactivity():
    """Auto-kick party members whose personal inactivity timer has expired."""
    now = datetime.now(timezone.utc)
    server_default = dungeon_settings.get("inactivity_minutes", DEFAULT_INACTIVITY_MINUTES)

    for realm in list(dungeon_parties.keys()):
        party = dungeon_parties.get(realm)
        if not party:
            continue

        idle_secs = (now - party["last_activity"]).total_seconds()
        channel_id = DUNGEON_REALM_TO_CHANNEL.get(realm)
        channel = bot.get_channel(channel_id) if channel_id else None

        to_kick = []
        for uid in party["members"]:
            udata = get_dungeon_user(uid)
            if udata.get("no_auto_kick", False):
                continue
            personal_mins = udata.get("inactivity_minutes") or server_default
            if idle_secs >= personal_mins * 60:
                to_kick.append((uid, personal_mins))

        if not to_kick:
            continue

        for uid, mins in to_kick:
            party["members"].remove(uid)
            if channel:
                await channel.send(
                    f"⏱️ <@{uid}> was removed from the **{realm} Dungeon Party** "
                    f"due to inactivity ({mins}m personal timer)."
                )

        if not party["members"]:
            disband_party(realm)
            if channel:
                await channel.send(
                    f"⚔️ The **{realm} Dungeon Party** has been disbanded — no members remaining."
                )
        else:
            party["last_activity"] = now



PRICES_FILE  = "item_prices.json"
PENDING_FILE = "pending_prices.json"


def load_prices() -> dict:
    if os.path.exists(PRICES_FILE):
        try:
            with open(PRICES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_prices(data: dict):
    with open(PRICES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_pending() -> dict:
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_pending(data: dict):
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f, indent=2)

def next_submission_id() -> str:
    data = load_pending()
    existing = [int(k) for k in data.keys() if k.isdigit()]
    return str(max(existing, default=0) + 1)


_item_cache: list = []
_item_cache_time: datetime | None = None
_ITEM_FIELDS = [
    "id", "CrateID", "TagPrimary", "TagSecondary", "TagTertiary",
    "TagQuaternary", "TagQuinary", "TagSenary", "TagSeptenary",
    "WinPercentage", "RarityHuman", "RarityHTML",
    "ItemName", "ItemNameHTML", "Notes", "RawData", "ItemHuman", "ItemHTML"
]

async def fetch_items() -> list:
    """Return cached item list, refreshing from API at most once per hour.
    Duplicates (same ItemName, different id) are removed — lowest id wins."""
    global _item_cache, _item_cache_time
    now = datetime.now(timezone.utc)
    if _item_cache and _item_cache_time and (now - _item_cache_time).total_seconds() < 3600:
        return _item_cache
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ITEMS_API_URL,
                headers={"I-INCLUDED-INFO": ";".join(_ITEM_FIELDS)},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                text = await resp.text()
                if not text.strip():
                    print(f"[PriceChecker] API returned empty response (status {resp.status})")
                    return _item_cache
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    print(f"[PriceChecker] API JSON decode error: {e} — body: {text[:200]}")
                    return _item_cache
                raw = data.get("data", [])
                seen = {}
                for item in raw:
                    name = item["ItemName"]
                    if name not in seen or item["id"] < seen[name]["id"]:
                        seen[name] = item
                _item_cache = list(seen.values())
                _item_cache_time = now
    except Exception as e:
        print(f"[PriceChecker] Failed to fetch items: {e}")
    return _item_cache

def find_item(name: str, items: list) -> dict | None:
    """Case-insensitive match against ItemName, stripping decorative symbols."""
    needle = name.strip().lower()
    for item in items:
        clean = item["ItemName"].strip().lower()
        clean_plain = re.sub(r'^[\W_]+|[\W_]+$', '', clean)
        if needle == clean or needle == clean_plain:
            return item
    for item in items:
        if needle in item["ItemName"].lower():
            return item
    return None


async def item_autocomplete(interaction: discord.Interaction, current: str):
    items = await fetch_items()
    current_lower = current.lower()
    matches = [
        i["ItemName"] for i in items
        if current_lower in i["ItemName"].lower()
    ][:25]
    return [discord.app_commands.Choice(name=m, value=m) for m in matches]

async def server_autocomplete(interaction: discord.Interaction, current: str):
    return [
        discord.app_commands.Choice(name=s.capitalize(), value=s)
        for s in VALID_SERVERS
        if current.lower() in s.lower()
    ]


def wrong_channel(interaction: discord.Interaction, expected_channel_id: int) -> bool:
    return interaction.channel_id != expected_channel_id


def has_price_checker_role(member: discord.Member) -> bool:
    if not PRICE_CHECKER_ROLE_ID:
        return False
    role_ids = {r.id for r in member.roles}
    return PRICE_CHECKER_ROLE_ID in role_ids or (MOD_ROLE_ID and MOD_ROLE_ID in role_ids)

def format_pending_embed(sub_id: str, entry: dict) -> discord.Embed:
    status = entry["status"]
    colour = {
        "pending":  0xf0c040,
        "unsure":   0xe07820,
        "approved": 0x43b581,
        "denied":   0xf04747,
    }.get(status, 0x2b2d31)

    embed = discord.Embed(
        title=f"💰 Price Suggestion #{sub_id}",
        colour=colour,
        timestamp=datetime.fromisoformat(entry["timestamp"])
    )
    embed.add_field(name="Item",    value=entry["item_name"], inline=True)
    embed.add_field(name="Server",  value=entry["server"].capitalize(), inline=True)
    embed.add_field(name="Price",   value=f"${entry['price']:,}", inline=True)
    embed.add_field(name="Suggested by", value=f"<@{entry['suggested_by_id']}>", inline=True)
    embed.add_field(name="Status",  value=status.capitalize(), inline=True)

    if status == "unsure":
        agree    = len(entry.get("agree_votes", []))
        disagree = len(entry.get("disagree_votes", []))
        embed.add_field(
            name="Unsure votes",
            value=f"✅ {agree}/{UNSURE_VOTES_NEEDED} agree   ❌ {disagree}/{UNSURE_VOTES_NEEDED} disagree",
            inline=False
        )
    return embed

async def resolve_submission(sub_id: str, entry: dict, approved: bool):
    """Finalise a submission — save price or discard, update review message."""
    entry["status"] = "approved" if approved else "denied"
    pending = load_pending()
    pending[sub_id] = entry
    save_pending(pending)

    if approved:
        prices = load_prices()
        server = entry["server"]
        if server not in prices:
            prices[server] = {}
        prices[server][entry["item_name"]] = entry["price"]
        save_prices(prices)

    review_channel = bot.get_channel(PRICE_REVIEW_CHANNEL_ID)
    if not review_channel:
        try:
            review_channel = await bot.fetch_channel(PRICE_REVIEW_CHANNEL_ID)
        except Exception:
            return

    msg_id = entry.get("review_message_id")
    if msg_id:
        try:
            msg = await review_channel.fetch_message(int(msg_id))
            await msg.edit(embed=format_pending_embed(sub_id, entry), view=None)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"[PriceChecker] Missing permissions to edit review message for #{sub_id}")
        except Exception as e:
            print(f"[PriceChecker] Failed to edit review message for #{sub_id}: {e}")


@bot.tree.command(name="itemprice", description="Suggest a price for an item")
@discord.app_commands.describe(
    item="Item name",
    server="Server (elysium / arcane / cosmic)",
    price="Suggested price"
)
@discord.app_commands.autocomplete(item=item_autocomplete, server=server_autocomplete)
async def cmd_itemprice(
    interaction: discord.Interaction,
    item: str,
    server: str,
    price: int
):
    server_lower = server.lower()
    if server_lower not in VALID_SERVERS:
        await interaction.response.send_message(
            f"❌ Invalid server. Choose from: {', '.join(VALID_SERVERS)}.", ephemeral=True
        )
        return

    if interaction.channel.id != PRICE_PUBLIC_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Please use this command in <#{PRICE_PUBLIC_CHANNEL_ID}>.", ephemeral=True
        )
        return

    if price <= 0:
        await interaction.response.send_message("❌ Price must be a positive number.", ephemeral=True)
        return

    items = await fetch_items()
    if not items:
        await interaction.response.send_message(
            "❌ Couldn't reach the item list API right now. Try again in a moment.", ephemeral=True
        )
        return
    matched = find_item(item, items)
    if not matched:
        await interaction.response.send_message(
            f"❌ Couldn't find an item matching **{item}**. Check the spelling or use the autocomplete.", ephemeral=True
        )
        return

    item_name = matched["ItemName"]
    sub_id    = next_submission_id()
    entry     = {
        "item_name":         item_name,
        "server":            server_lower,
        "price":             price,
        "suggested_by":      interaction.user.name,
        "suggested_by_id":   interaction.user.id,
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "status":            "pending",
        "agree_votes":       [],
        "disagree_votes":    [],
        "voted_by":          [],
        "review_message_id": None,
    }

    review_channel = interaction.guild.get_channel(PRICE_REVIEW_CHANNEL_ID)
    if not review_channel:
        await interaction.response.send_message(
            "❌ Review channel not found. Ask an admin to set `PRICE_REVIEW_CHANNEL_ID`.", ephemeral=True
        )
        return

    embed = format_pending_embed(sub_id, entry)
    msg   = await review_channel.send(embed=embed)
    entry["review_message_id"] = msg.id

    pending = load_pending()
    pending[sub_id] = entry
    save_pending(pending)

    await interaction.response.send_message(
        f"📋 **#{sub_id}** — {item_name} | {server_lower.capitalize()} | ${price:,} — suggested by {interaction.user.mention}"
    )

@bot.tree.command(name="checkprice", description="Check the approved price of an item")
@discord.app_commands.describe(
    item="Item name",
    server="Server (elysium / arcane / cosmic)"
)
@discord.app_commands.autocomplete(item=item_autocomplete, server=server_autocomplete)
async def cmd_checkprice(interaction: discord.Interaction, item: str, server: str):
    if wrong_channel(interaction, PRICE_CHECK_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_CHECK_CHANNEL_ID}>.", ephemeral=True
        )
        return

    server_lower = server.lower()
    if server_lower not in VALID_SERVERS:
        await interaction.response.send_message(
            f"❌ Invalid server. Choose from: {', '.join(VALID_SERVERS)}.", ephemeral=True
        )
        return

    items = await fetch_items()
    matched = find_item(item, items)
    item_name = matched["ItemName"] if matched else item

    prices = load_prices()
    price = prices.get(server_lower, {}).get(item_name)

    if price is None:
        await interaction.response.send_message(
            f"No price data on **{item_name}** for **{server_lower.capitalize()}** yet!",
            delete_after=30
        )
    else:
        await interaction.response.send_message(
            f"💰 **{item_name}** — **{server_lower.capitalize()}**: **${price:,}**"
        )

@bot.tree.command(name="confirmprice", description="Confirm a price suggestion is correct")
@discord.app_commands.describe(submission_id="The submission ID to confirm")
async def cmd_confirmprice(interaction: discord.Interaction, submission_id: str):
    if wrong_channel(interaction, PRICE_REVIEW_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_REVIEW_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not has_price_checker_role(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)
        return

    pending = load_pending()
    entry   = pending.get(submission_id)
    if not entry:
        await interaction.response.send_message(f"❌ No submission found with ID `#{submission_id}`.", ephemeral=True)
        return
    if entry["status"] not in ("pending", "unsure"):
        await interaction.response.send_message(
            f"❌ Submission `#{submission_id}` is already **{entry['status']}**.", ephemeral=True
        )
        return

    await resolve_submission(submission_id, entry, approved=True)
    await interaction.response.send_message(
        f"✅ Price for **{entry['item_name']}** ({entry['server'].capitalize()}) confirmed and saved.", ephemeral=True
    )

@bot.tree.command(name="denyprice", description="Deny a price suggestion as incorrect")
@discord.app_commands.describe(submission_id="The submission ID to deny")
async def cmd_denyprice(interaction: discord.Interaction, submission_id: str):
    if wrong_channel(interaction, PRICE_REVIEW_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_REVIEW_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not has_price_checker_role(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)
        return

    pending = load_pending()
    entry   = pending.get(submission_id)
    if not entry:
        await interaction.response.send_message(f"❌ No submission found with ID `#{submission_id}`.", ephemeral=True)
        return
    if entry["status"] not in ("pending", "unsure"):
        await interaction.response.send_message(
            f"❌ Submission `#{submission_id}` is already **{entry['status']}**.", ephemeral=True
        )
        return

    await resolve_submission(submission_id, entry, approved=False)
    await interaction.response.send_message(
        f"🗑️ Price suggestion `#{submission_id}` for **{entry['item_name']}** denied.", ephemeral=True
    )

@bot.tree.command(name="unsureprice", description="Mark a price suggestion as unsure — requires 2 votes to resolve")
@discord.app_commands.describe(submission_id="The submission ID to mark as unsure")
async def cmd_unsureprice(interaction: discord.Interaction, submission_id: str):
    if wrong_channel(interaction, PRICE_REVIEW_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_REVIEW_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not has_price_checker_role(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)
        return

    pending = load_pending()
    entry   = pending.get(submission_id)
    if not entry:
        await interaction.response.send_message(f"❌ No submission found with ID `#{submission_id}`.", ephemeral=True)
        return
    if entry["status"] not in ("pending", "unsure"):
        await interaction.response.send_message(
            f"❌ Submission `#{submission_id}` is already **{entry['status']}**.", ephemeral=True
        )
        return
    if str(interaction.user.id) in entry.get("voted_by", []):
        await interaction.response.send_message("❌ You've already voted on this submission.", ephemeral=True)
        return

    entry["status"] = "unsure"
    entry.setdefault("agree_votes", [])
    entry.setdefault("disagree_votes", [])
    entry.setdefault("voted_by", [])

    await interaction.response.send_message(
        f"❓ Submission `#{submission_id}` marked as unsure. Now vote with `/agreeprice` or `/disagreeprice`.",
        ephemeral=True
    )

    pending[submission_id] = entry
    save_pending(pending)
    review_channel = interaction.guild.get_channel(PRICE_REVIEW_CHANNEL_ID)
    if review_channel and entry.get("review_message_id"):
        try:
            msg = await review_channel.fetch_message(int(entry["review_message_id"]))
            await msg.edit(embed=format_pending_embed(submission_id, entry))
        except Exception:
            pass

@bot.tree.command(name="agreeprice", description="Vote to agree on an unsure price submission")
@discord.app_commands.describe(submission_id="The submission ID to agree with")
async def cmd_agreeprice(interaction: discord.Interaction, submission_id: str):
    if wrong_channel(interaction, PRICE_REVIEW_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_REVIEW_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not has_price_checker_role(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)
        return

    pending = load_pending()
    entry   = pending.get(submission_id)
    if not entry:
        await interaction.response.send_message(f"❌ No submission found with ID `#{submission_id}`.", ephemeral=True)
        return
    if entry["status"] != "unsure":
        await interaction.response.send_message(
            f"❌ Submission `#{submission_id}` is not in unsure state.", ephemeral=True
        )
        return

    uid = str(interaction.user.id)

    if uid in entry.get("agree_votes", []):
        await interaction.response.send_message("❌ You've already voted agree on this submission.", ephemeral=True)
        return

    switched = uid in entry.get("disagree_votes", [])
    if switched:
        entry["disagree_votes"].remove(uid)
        entry["voted_by"].remove(uid)

    entry["agree_votes"].append(uid)
    entry["voted_by"].append(uid)
    pending[submission_id] = entry
    save_pending(pending)

    if len(entry["agree_votes"]) >= UNSURE_VOTES_NEEDED:
        await resolve_submission(submission_id, entry, approved=True)
        await interaction.response.send_message(
            f"✅ Consensus reached — price for **{entry['item_name']}** approved and saved.", ephemeral=True
        )
    else:
        remaining = UNSURE_VOTES_NEEDED - len(entry["agree_votes"])
        note = " (switched from disagree)" if switched else ""
        await interaction.response.send_message(
            f"✅ Vote recorded{note}. **{remaining}** more agree vote(s) needed to approve.", ephemeral=True
        )
        review_channel = interaction.guild.get_channel(PRICE_REVIEW_CHANNEL_ID)
        if review_channel and entry.get("review_message_id"):
            try:
                msg = await review_channel.fetch_message(int(entry["review_message_id"]))
                await msg.edit(embed=format_pending_embed(submission_id, entry))
            except Exception:
                pass

@bot.tree.command(name="disagreeprice", description="Vote to disagree on an unsure price submission")
@discord.app_commands.describe(submission_id="The submission ID to disagree with")
async def cmd_disagreeprice(interaction: discord.Interaction, submission_id: str):
    if wrong_channel(interaction, PRICE_REVIEW_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{PRICE_REVIEW_CHANNEL_ID}>.", ephemeral=True
        )
        return
    if not has_price_checker_role(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to do this.", ephemeral=True)
        return

    pending = load_pending()
    entry   = pending.get(submission_id)
    if not entry:
        await interaction.response.send_message(f"❌ No submission found with ID `#{submission_id}`.", ephemeral=True)
        return
    if entry["status"] != "unsure":
        await interaction.response.send_message(
            f"❌ Submission `#{submission_id}` is not in unsure state.", ephemeral=True
        )
        return

    uid = str(interaction.user.id)

    if uid in entry.get("disagree_votes", []):
        await interaction.response.send_message("❌ You've already voted disagree on this submission.", ephemeral=True)
        return

    switched = uid in entry.get("agree_votes", [])
    if switched:
        entry["agree_votes"].remove(uid)
        entry["voted_by"].remove(uid)

    entry["disagree_votes"].append(uid)
    entry["voted_by"].append(uid)
    pending[submission_id] = entry
    save_pending(pending)

    if len(entry["disagree_votes"]) >= UNSURE_VOTES_NEEDED:
        await resolve_submission(submission_id, entry, approved=False)
        await interaction.response.send_message(
            f"🗑️ Consensus reached — price suggestion `#{submission_id}` denied.", ephemeral=True
        )
    else:
        remaining = UNSURE_VOTES_NEEDED - len(entry["disagree_votes"])
        note = " (switched from agree)" if switched else ""
        await interaction.response.send_message(
            f"❌ Vote recorded{note}. **{remaining}** more disagree vote(s) needed to deny.", ephemeral=True
        )
        review_channel = interaction.guild.get_channel(PRICE_REVIEW_CHANNEL_ID)
        if review_channel and entry.get("review_message_id"):
            try:
                msg = await review_channel.fetch_message(int(entry["review_message_id"]))
                await msg.edit(embed=format_pending_embed(submission_id, entry))
            except Exception:
                pass


INVENTORIES_FILE = "inventories.json"


def load_inventories() -> dict:
    """
    {
      "user_id": {
        "inventory_name": {
          "server": "arcane",
          "channel_id": 123456,
          "items": ["✦ Excalibur ✦", ...]
        }
      }
    }
    """
    if os.path.exists(INVENTORIES_FILE):
        try:
            with open(INVENTORIES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_inventories(data: dict):
    with open(INVENTORIES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_inventories(user_id: int) -> dict:
    data = load_inventories()
    return data.get(str(user_id), {})

def get_inventory_by_channel(channel_id: int):
    """Returns (user_id_str, inv_name, inv_data) or (None, None, None)."""
    data = load_inventories()
    for uid, inventories in data.items():
        for name, inv in inventories.items():
            if inv.get("channel_id") == channel_id:
                return uid, name, inv
    return None, None, None


async def post_inventory_help(channel):
    """Post the help embed in the inventory channel — only if not already there with identical content."""
    description = (
        "Use the commands below to create a private inventory channel.\n\n"
        "**`/createinventory (server) (name)`**\n"
        "Creates a private channel for that inventory. "
        "You can have multiple inventories per server — just give each one a unique name.\n\n"
        "Once inside your inventory channel:\n"
        "• **`/additem (item)`** — add a single item to this inventory\n"
        "• **`/bulkadd (item1) [item2] ... [item5]`** — add up to 5 items at once\n"
        "• **`/removeitem (item)`** — remove an item from this inventory\n\n"
        f"Then head to <#{NETWORTH_CHANNEL_ID}> and use **`/networth (public/private) (name)`** "
        "to calculate your total value."
    )
    try:
        async for msg in channel.history(limit=20):
            if msg.author == channel.guild.me and msg.embeds:
                e = msg.embeds[0]
                if e.title == "🎒 Inventory System" and e.description == description:
                    return
                if e.title == "🎒 Inventory System":
                    await msg.delete()
                    break
    except Exception:
        pass
    embed = discord.Embed(title="🎒 Inventory System", description=description, color=0x2b2d31)
    await channel.send(embed=embed)


@bot.tree.command(name="createinventory", description="Create a private inventory channel")
@discord.app_commands.describe(
    server="Server this inventory is for (elysium / arcane / cosmic)",
    inventoryname="A unique name for this inventory"
)
@discord.app_commands.autocomplete(server=server_autocomplete)
async def cmd_createinventory(interaction: discord.Interaction, server: str, inventoryname: str):
    if wrong_channel(interaction, INVENTORY_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ Please use this command in <#{INVENTORY_CHANNEL_ID}>.", ephemeral=True
        )
        return

    server_lower = server.lower()
    if server_lower not in VALID_SERVERS:
        await interaction.response.send_message(
            f"❌ Invalid server. Choose from: {', '.join(VALID_SERVERS)}.",
            ephemeral=True, delete_after=30
        )
        return

    inv_name = inventoryname.strip()
    if not inv_name:
        await interaction.response.send_message(
            "❌ Inventory name cannot be empty.", ephemeral=True, delete_after=30
        )
        return

    data = load_inventories()
    uid  = str(interaction.user.id)
    user_invs = data.get(uid, {})

    if inv_name in user_invs:
        existing_channel_id = user_invs[inv_name].get("channel_id")
        existing_channel = interaction.guild.get_channel(existing_channel_id) if existing_channel_id else None
        if existing_channel:
            await interaction.response.send_message(
                f"❌ You already have an inventory called **{inv_name}**: {existing_channel.mention}",
                ephemeral=True, delete_after=30
            )
            return
        del user_invs[inv_name]

    guild    = interaction.guild
    category = guild.get_channel(INVENTORY_CATEGORY_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=False),
        guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    if MOD_ROLE_ID:
        mod_role = guild.get_role(MOD_ROLE_ID)
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

    safe_name = inv_name.lower().replace(" ", "-")[:50]
    channel_name = f"inv-{interaction.user.name}-{safe_name}"[:100]
    new_channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Inventory '{inv_name}' for {interaction.user}"
    )

    if uid not in data:
        data[uid] = {}
    data[uid][inv_name] = {
        "server":     server_lower,
        "channel_id": new_channel.id,
        "items":      [],
        "username":   interaction.user.name,
    }
    save_inventories(data)

    embed = discord.Embed(
        title=f"🎒 {inv_name}",
        description=(
            f"**Server:** {server_lower.capitalize()}\n"
            f"**Owner:** {interaction.user.mention}\n\n"
            f"Use `/additem` to add items, `/removeitem` to remove them.\n"
            f"Use `/networth` in <#{NETWORTH_CHANNEL_ID}> to calculate your total value."
        ),
        color=0x2b2d31,
    )
    await new_channel.send(embed=embed)

    await interaction.response.send_message(
        f"✅ Inventory **{inv_name}** created: {new_channel.mention}",
        ephemeral=True, delete_after=30
    )


@bot.tree.command(name="additem", description="Add an item to this inventory (use inside your inventory channel)")
@discord.app_commands.describe(item="Item to add")
@discord.app_commands.autocomplete(item=item_autocomplete)
async def cmd_additem(interaction: discord.Interaction, item: str):
    uid, inv_name, inv = get_inventory_by_channel(interaction.channel_id)
    if not inv:
        await interaction.response.send_message(
            "❌ This command must be used inside one of your inventory channels.", ephemeral=True
        )
        return

    items = await fetch_items()
    matched = find_item(item, items)
    if not matched:
        await interaction.response.send_message(
            f"❌ Couldn't find an item matching **{item}**.", ephemeral=True
        )
        return

    if uid != str(interaction.user.id):
        await interaction.response.send_message("❌ This isn't your inventory.", ephemeral=True)
        return

    item_name = matched["ItemName"]
    data = load_inventories()
    data[uid][inv_name]["items"].append(item_name)
    save_inventories(data)

    await interaction.response.send_message(f"✅ Added **{item_name}** to **{inv_name}**.")


@bot.tree.command(name="removeitem", description="Remove an item from this inventory (use inside your inventory channel)")
@discord.app_commands.describe(item="Item to remove")
@discord.app_commands.autocomplete(item=item_autocomplete)
async def cmd_removeitem(interaction: discord.Interaction, item: str):
    uid, inv_name, inv = get_inventory_by_channel(interaction.channel_id)
    if not inv:
        await interaction.response.send_message(
            "❌ This command must be used inside one of your inventory channels.", ephemeral=True
        )
        return

    if uid != str(interaction.user.id):
        await interaction.response.send_message("❌ This isn't your inventory.", ephemeral=True)
        return

    items = await fetch_items()
    matched = find_item(item, items)
    item_name = matched["ItemName"] if matched else item.strip()

    data = load_inventories()
    inv_items = data[uid][inv_name]["items"]
    if item_name not in inv_items:
        await interaction.response.send_message(
            f"❌ **{item_name}** isn't in this inventory.", ephemeral=True
        )
        return

    inv_items.remove(item_name)
    save_inventories(data)
    await interaction.response.send_message(f"✅ Removed **{item_name}** from **{inv_name}**.")


@bot.tree.command(name="bulkadd", description="Add up to 5 items to this inventory at once (use inside your inventory channel)")
@discord.app_commands.describe(
    item1="Item to add",
    item2="Item to add (optional)",
    item3="Item to add (optional)",
    item4="Item to add (optional)",
    item5="Item to add (optional)",
)
@discord.app_commands.autocomplete(
    item1=item_autocomplete,
    item2=item_autocomplete,
    item3=item_autocomplete,
    item4=item_autocomplete,
    item5=item_autocomplete,
)
async def cmd_bulkadd(
    interaction: discord.Interaction,
    item1: str,
    item2: str = None,
    item3: str = None,
    item4: str = None,
    item5: str = None,
):
    uid, inv_name, inv = get_inventory_by_channel(interaction.channel_id)
    if not inv:
        await interaction.response.send_message(
            "❌ This command must be used inside one of your inventory channels.", ephemeral=True
        )
        return

    if uid != str(interaction.user.id):
        await interaction.response.send_message("❌ This isn't your inventory.", ephemeral=True)
        return

    items_api = await fetch_items()
    inputs = [i for i in [item1, item2, item3, item4, item5] if i]

    added   = []
    skipped = []
    for raw in inputs:
        matched = find_item(raw, items_api)
        if matched:
            added.append(matched["ItemName"])
        else:
            skipped.append(raw)

    if added:
        data = load_inventories()
        data[uid][inv_name]["items"].extend(added)
        save_inventories(data)

    lines = []
    if added:
        lines.append("✅ **Added:**\n" + "\n".join(f"• {n}" for n in added))
    if skipped:
        lines.append("❌ **Not found:**\n" + "\n".join(f"• {n}" for n in skipped))

    await interaction.response.send_message("\n\n".join(lines))

@bot.tree.command(name="networth", description="Calculate the total value of an inventory")
@discord.app_commands.describe(
    visibility="public — everyone sees it, private — only you see it",
    inventoryname="The name of your inventory"
)
@discord.app_commands.choices(visibility=[
    discord.app_commands.Choice(name="public",  value="public"),
    discord.app_commands.Choice(name="private", value="private"),
])
async def cmd_networth(interaction: discord.Interaction, visibility: str, inventoryname: str):
    if wrong_channel(interaction, NETWORTH_CHANNEL_ID):
        await interaction.response.send_message(
            f"❌ Please use this command in <#{NETWORTH_CHANNEL_ID}>.", ephemeral=True
        )
        return

    uid  = str(interaction.user.id)
    data = load_inventories()
    user_invs = data.get(uid, {})

    if inventoryname not in user_invs:
        await interaction.response.send_message(
            f"❌ You don't have an inventory called **{inventoryname}**.", ephemeral=True
        )
        return

    inv     = user_invs[inventoryname]
    server  = inv["server"]
    inv_items = inv["items"]
    prices  = load_prices()
    server_prices = prices.get(server, {})

    total        = 0
    priced_items = []
    missing      = []

    for item_name in inv_items:
        price = server_prices.get(item_name)
        if price is not None:
            total += price
            priced_items.append((item_name, price))
        else:
            missing.append(item_name)

    ephemeral = (visibility == "private")

    embed = discord.Embed(
        title=f"💰 Networth — {inventoryname}",
        color=0x43b581 if not missing else 0xf0c040,
    )
    embed.add_field(name="Server",     value=server.capitalize(), inline=True)
    embed.add_field(name="Owner",      value=interaction.user.mention, inline=True)
    embed.add_field(name="Total Value", value=f"${total:,}", inline=True)

    if priced_items:
        item_lines = "\n".join(f"• {name} — ${price:,}" for name, price in priced_items)
        if len(item_lines) > 1024:
            item_lines = item_lines[:1020] + "\n..."
        embed.add_field(name="Items", value=item_lines, inline=False)

    if missing:
        embed.set_footer(text=f"⚠️ {len(missing)} item(s) excluded — no price data for {server.capitalize()}")

    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    if missing:
        inv_channel = interaction.guild.get_channel(inv["channel_id"])
        inv_mention = inv_channel.mention if inv_channel else f"your **{inventoryname}** channel"

        await interaction.followup.send(
            f"⚠️ **{len(missing)} item{'s' if len(missing) != 1 else ''}** "
            f"do not currently have a value for **{server.capitalize()}**, "
            f"and so will not be added to your networth. "
            f"See which items have been ignored here: {inv_mention}",
            ephemeral=True,
            delete_after=30
        )

        if inv_channel:
            missing_lines = "\n".join(f"• {name}" for name in missing)
            missing_embed = discord.Embed(
                title="⚠️ Items excluded from networth",
                description=(
                    f"The following items were not included in your last networth calculation "
                    f"because they have no price set for **{server.capitalize()}**:\n\n{missing_lines}"
                ),
                color=0xf04747,
            )
            await inv_channel.send(embed=missing_embed)


@tasks.loop(minutes=30)
async def auto_filler():
    now = datetime.now()
    for channel_id, config in VOTE_CONFIG.items():
        log_cid, ping_rid, realm = config
        if realm not in settings["enabled_realms"]: continue
        last_entry = channel_data.get(channel_id)
        if last_entry:
            last_num, last_time = last_entry
            if (now - last_time) >= timedelta(minutes=settings["prediction_interval"]):
                await send_vote_update(channel_id, min(98, last_num + 1), "Bot Prediction Report", is_bot=True)

@tasks.loop(minutes=1)
async def check_ping_schedules():
    now_utc = datetime.now(timezone.utc)
    data    = load_schedules()
    changed = False

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    for uid, user_data in data.items():
        try:
            member = guild.get_member(int(uid))
            if not member:
                continue

            tz_str       = user_data.get("timezone", "Europe/London")
            snooze_until = user_data.get("snooze_until")
            is_muted     = user_data.get("is_muted", False)

            if snooze_until and is_muted:
                dt = datetime.fromisoformat(snooze_until)
                if now_utc >= dt:
                    restored = []
                    for realm in user_data.get("muted_realms", []):
                        role_id = REALM_PING_ROLES.get(realm)
                        if role_id:
                            role = guild.get_role(role_id)
                            if role:
                                try:
                                    await member.add_roles(role, reason="Snooze expired")
                                    restored.append(f"Vote/{realm}")
                                except discord.Forbidden:
                                    pass
                    if user_data.get("muted_dungeons"):
                        added_dungeon = False
                        for role_id in DUNGEON_REALM_TO_ROLE.values():
                            role = guild.get_role(role_id)
                            if role:
                                try:
                                    await member.add_roles(role, reason="Snooze expired")
                                    if not added_dungeon:
                                        restored.append("Dungeon (server)")
                                        added_dungeon = True
                                except discord.Forbidden:
                                    pass
                    needs_everyone = user_data.get("muted_everyone") or user_data.get("muted_pinata")
                    if needs_everyone and FAKE_EVERYONE_ROLE_ID:
                        fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                        if fake_everyone and fake_everyone not in member.roles:
                            try:
                                await member.add_roles(fake_everyone, reason="Snooze expired")
                                if user_data.get("muted_pinata"):   restored.append("Pinata (server)")
                                if user_data.get("muted_everyone"): restored.append("@everyone")
                            except discord.Forbidden:
                                pass

                    data[uid].update({
                        "snooze_until": None,
                        "is_muted": False,
                        "muted_realms": [],
                        "muted_dungeons": False,
                        "muted_pinata": False,
                        "muted_everyone": False,
                    })
                    changed = True
                    snooze_until = None

                    channel_id = user_data.get("channel_id")
                    if channel_id:
                        ch = bot.get_channel(channel_id)
                        if ch:
                            await ch.send(
                                f"🔔 {member.mention} Your snooze has ended — pings restored! "
                                f"({', '.join(restored)})",
                                delete_after=30
                            )

            sleep_time = user_data.get("sleep_time")
            wake_time  = user_data.get("wake_time")

            if sleep_time and wake_time and not snooze_until:
                try:
                    tz = pytz.timezone(tz_str)
                    local_now    = now_utc.astimezone(tz)
                    current_hhmm = local_now.strftime("%H:%M")
                    in_window    = is_in_sleep_window(current_hhmm, sleep_time, wake_time)

                    s_realms   = user_data.get("schedule_realms", [])
                    s_dungeons = user_data.get("schedule_dungeons", False)
                    s_pinata   = user_data.get("schedule_pinata", False)
                    s_everyone = user_data.get("schedule_everyone", False)

                    if in_window and not is_muted:
                        muted_realms = []

                        for realm in s_realms:
                            role_id = REALM_PING_ROLES.get(realm)
                            if role_id:
                                role = guild.get_role(role_id)
                                if role and role in member.roles:
                                    try:
                                        await member.remove_roles(role, reason="Sleep schedule")
                                        muted_realms.append(realm)
                                    except discord.Forbidden:
                                        pass

                        if s_dungeons:
                            for role_id in DUNGEON_REALM_TO_ROLE.values():
                                role = guild.get_role(role_id)
                                if role and role in member.roles:
                                    try:
                                        await member.remove_roles(role, reason="Sleep schedule dungeon")
                                    except discord.Forbidden:
                                        pass

                        needs_remove_everyone = s_everyone or s_pinata
                        if needs_remove_everyone and FAKE_EVERYONE_ROLE_ID:
                            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                            if fake_everyone and fake_everyone in member.roles:
                                try:
                                    await member.remove_roles(fake_everyone, reason="Sleep schedule")
                                except discord.Forbidden:
                                    pass

                        data[uid].update({
                            "is_muted": True,
                            "muted_realms": muted_realms,
                            "muted_dungeons": s_dungeons,
                            "muted_pinata": s_pinata,
                            "muted_everyone": s_everyone,
                        })
                        changed = True

                        channel_id = user_data.get("channel_id")
                        if channel_id:
                            ch = bot.get_channel(channel_id)
                            if ch:
                                await ch.send(
                                    f"😴 {member.mention} Sleep schedule active — pings paused until **{wake_time}** `({tz_str})`.",
                                    delete_after=30
                                )

                    elif not in_window and is_muted and not snooze_until:
                        restored = []
                        for realm in data[uid].get("muted_realms", []):
                            role_id = REALM_PING_ROLES.get(realm)
                            if role_id:
                                role = guild.get_role(role_id)
                                if role:
                                    try:
                                        await member.add_roles(role, reason="Wake schedule")
                                        restored.append(realm)
                                    except discord.Forbidden:
                                        pass

                        if data[uid].get("muted_dungeons"):
                            added = False
                            for role_id in DUNGEON_REALM_TO_ROLE.values():
                                role = guild.get_role(role_id)
                                if role:
                                    try:
                                        await member.add_roles(role, reason="Wake schedule")
                                        if not added:
                                            restored.append("Dungeon (server)")
                                            added = True
                                    except discord.Forbidden:
                                        pass

                        needs_everyone = data[uid].get("muted_everyone") or data[uid].get("muted_pinata")
                        if needs_everyone and FAKE_EVERYONE_ROLE_ID:
                            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                            if fake_everyone and fake_everyone not in member.roles:
                                try:
                                    await member.add_roles(fake_everyone, reason="Wake schedule")
                                    if data[uid].get("muted_pinata"):   restored.append("Pinata (server)")
                                    if data[uid].get("muted_everyone"): restored.append("@everyone")
                                except discord.Forbidden:
                                    pass

                        data[uid].update({
                            "is_muted": False,
                            "muted_realms": [],
                            "muted_dungeons": False,
                            "muted_pinata": False,
                            "muted_everyone": False,
                        })
                        changed = True

                        channel_id = user_data.get("channel_id")
                        if channel_id:
                            ch = bot.get_channel(channel_id)
                            if ch:
                                await ch.send(
                                    f"☀️ {member.mention} Good morning! Pings re-enabled. ({', '.join(restored)})",
                                    delete_after=30
                                )
                except Exception:
                    pass

        except Exception:
            continue

    if changed:
        save_schedules(data)

@bot.event
async def on_ready():
    bot.add_view(ClearLogsView())
    bot.add_view(BotControlView())
    bot.add_view(OpenSettingsView())
    bot.add_view(UserSettingsView(bot))
    bot.add_view(OpenDungeonSettingsView())
    bot.add_view(UserDungeonSettingsView(bot))
    if not auto_filler.is_running():
        auto_filler.change_interval(minutes=settings["prediction_interval"])
        auto_filler.start()
    if not check_ping_schedules.is_running():
        check_ping_schedules.start()
    if not check_dungeon_inactivity.is_running():
        check_dungeon_inactivity.start()
    await bot.tree.sync()
    channel = bot.get_channel(CONTROL_CHANNEL_ID)
    if channel:
        try: await channel.purge(limit=10, check=lambda m: m.author == bot.user)
        except: pass
        await channel.send(embed=discord.Embed(title="🛠️ Control Panel", color=0x2b2d31), view=BotControlView())

    ping_channel = bot.get_channel(PING_SETTINGS_CHANNEL_ID)
    if ping_channel:
        ping_description = (
            "Click the button below to open your **private ping settings channel**.\n\n"
            "From there you can:\n"
            "• ⏸️ **Snooze** specific realm pings and/or @everyone — for a set duration\n"
            "• 😴 **Set a sleep schedule** to auto-disable pings overnight\n"
            "• ▶️ **Resume** pings instantly at any time\n"
            "• 🌍 **Set your timezone** from a dropdown list\n"
            "• ❌ **Close** your settings channel when you're done"
        )
        already_exists = False
        try:
            async for msg in ping_channel.history(limit=20):
                if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "🔔 Ping Settings":
                    if msg.embeds[0].description == ping_description:
                        already_exists = True
                    else:
                        await msg.delete()
                    break
        except Exception:
            pass
        if not already_exists:
            embed = discord.Embed(title="🔔 Ping Settings", description=ping_description, color=0x2b2d31)
            embed.set_footer(text="Your settings are saved even after closing the channel.")
            await ping_channel.send(embed=embed, view=OpenSettingsView())

    dungeon_settings_channel = bot.get_channel(DUNGEON_SETTINGS_CHANNEL_ID)
    if dungeon_settings_channel:
        dungeon_description = (
            "Click the button below to open your **private dungeon settings channel**.\n\n"
            "From there you can:\n"
            "• ⏱️ **Set your personal inactivity timer** — how long before you're auto-kicked if nobody joins your party\n"
            "• 🔄 **Reset to server default** — go back to the server's global timer\n"
            "• 🛡️ **Opt out of auto-kick entirely** — stay in the party no matter how long it takes\n"
            "• ❌ **Close** your settings channel when you're done\n\n"
            "_Your settings are saved even after closing the channel._"
        )
        already_exists = False
        try:
            async for msg in dungeon_settings_channel.history(limit=20):
                if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "⚔️ Dungeon Settings":
                    if msg.embeds[0].description == dungeon_description:
                        already_exists = True
                    else:
                        await msg.delete()
                    break
        except Exception:
            pass
        if not already_exists:
            embed = discord.Embed(title="⚔️ Dungeon Settings", description=dungeon_description, color=0x2b2d31)
            embed.set_footer(text="Your settings are saved even after closing the channel.")
            await dungeon_settings_channel.send(embed=embed, view=OpenDungeonSettingsView())

    inventory_channel = bot.get_channel(INVENTORY_CHANNEL_ID)
    if inventory_channel:
        await post_inventory_help(inventory_channel)

    print(f'Logged in as {bot.user}')

@bot.event
async def on_guild_channel_delete(channel):
    """If a user's private settings channel is deleted, wipe their settings back to defaults."""
    data = load_schedules()
    changed = False
    for uid, user_data in data.items():
        if user_data.get("channel_id") == channel.id:
            data[uid] = {
                "channel_id": None,
                "snooze_until": None,
                "sleep_time": None,
                "wake_time": None,
                "timezone": "Europe/London",
                "is_muted": False,
                "muted_realms": [],
                "muted_everyone": False,
                "muted_dungeons": False,
                "muted_pinata": False,
                "schedule_realms": [],
                "schedule_everyone": False,
                "schedule_dungeons": False,
                "schedule_pinata": False,
            }
            changed = True
            break
    if changed:
        save_schedules(data)

    ddata = load_dungeon_users()
    dchanged = False
    for uid, user_data in ddata.items():
        if user_data.get("channel_id") == channel.id:
            ddata[uid] = {
                "channel_id": None,
                "no_auto_kick": False,
                "inactivity_minutes": None,
            }
            dchanged = True
            break
    if dchanged:
        save_dungeon_users(ddata)

    inv_data = load_inventories()
    inv_changed = False
    for uid, inventories in inv_data.items():
        for inv_name, inv in list(inventories.items()):
            if inv.get("channel_id") == channel.id:
                del inv_data[uid][inv_name]
                inv_changed = True
    if inv_changed:
        save_inventories(inv_data)

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    now = datetime.now()
    if message.channel.id in STATS_CONFIG:
        try:
            count = int(message.content.strip())
            log_cid, realm = STATS_CONFIG[message.channel.id]
            await message.delete()
            log_data(realm, count)
            last_manual_stats[realm] = {"count": count, "time": now}
            await message.channel.send(embed=discord.Embed(description=f"👤 **{realm}: {count}**", color=0x2ecc71, timestamp=now))
        except: pass
    if message.channel.id in VOTE_CONFIG:
        try:
            num = int(message.content.strip())
            if 0 <= num <= 100:
                await message.delete()
                realm_data = VOTE_CONFIG[message.channel.id]
                realm = realm_data
                manual = last_manual_stats.get(realm)
                p_count = manual["count"] if manual and (now - manual["time"]) <= timedelta(minutes=30) else get_trend_analysis(realm)['avg']
                log_data(realm, p_count, vote_progress=num)
                await send_vote_update(message.channel.id, num, "Player Report", user_mention=message.author.mention)
        except: pass
    await bot.process_commands(message)

if TOKEN:
    bot.run(TOKEN)
else:
    print("'token.txt' not found")
