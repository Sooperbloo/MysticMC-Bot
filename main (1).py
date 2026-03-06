import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import csv
import os
import json
import asyncio
import re
import pytz
from config import (
    CONTROL_CHANNEL_ID,
    VOTE_CONFIG,
    STATS_CONFIG,
    PING_SETTINGS_CHANNEL_ID,
    MOD_ROLE_ID,
    FAKE_EVERYONE_ROLE_ID,
)

# --- CONFIGURATION ---
if os.path.exists('token.txt'):
    with open('token.txt', 'r') as f:
        TOKEN = f.read().strip()
else:
    print("Error: token.txt not found. Please create it and paste your token inside.")
    TOKEN = None

DATA_FILE = "player_trends.csv"
SETTINGS_FILE = "bot_settings.json"
channel_data = {}
channel_cooldowns = {}
last_manual_stats = {}

# Derived: realm name → ping role ID
REALM_PING_ROLES = {realm: ping_rid for _, (_, ping_rid, realm) in VOTE_CONFIG.items()}

SCHEDULES_FILE = "ping_schedules.json"

# Common timezones shown in the dropdown (max 25 for Discord)
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

# --- LOAD/SAVE SETTINGS ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"enabled_realms": ["Elysium", "Arcane", "Cosmic"], "prediction_interval": 30}

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

settings = load_settings()

# --- PING SCHEDULE DATA HELPERS ---
def load_schedules() -> dict:
    if os.path.exists(SCHEDULES_FILE):
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_schedules(data: dict):
    with open(SCHEDULES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_data(user_id: int) -> dict:
    data = load_schedules()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "channel_id": None,
            "snooze_until": None,
            "sleep_time": None,
            "wake_time": None,
            "timezone": "Europe/London",
            "is_muted": False,
            "muted_realms": [],
            "muted_everyone": False,
            "schedule_realms": [],
            "schedule_everyone": False,
        }
        save_schedules(data)
    return data[uid]

def set_user_data(user_id: int, updates: dict):
    data = load_schedules()
    uid = str(user_id)
    if uid not in data:
        get_user_data(user_id)
        data = load_schedules()
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
            muted_realms = user_data.get("muted_realms", [])
            everyone_muted = user_data.get("muted_everyone", False)
            scope = ", ".join(muted_realms) if muted_realms else "none"
            if everyone_muted:
                scope += " + @everyone"
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
        s_everyone = user_data.get("schedule_everyone", False)
        scope = ", ".join(s_realms) if s_realms else "none"
        if s_everyone:
            scope += " + @everyone"
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
        now_local = datetime.now(timezone.utc).astimezone(tz)
        tz_display = f"`{tz_str}` — currently **{now_local.strftime('%H:%M')}**"
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

# --- DATA HELPERS ---
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

# --- ORIGINAL VIEWS ---
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

# --- PING SCHEDULE VIEWS ---
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
        set_user_data(interaction.user.id, {"timezone": tz_str})
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
        self.mute_everyone = False

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

    @discord.ui.button(label="@everyone: Unmuted", style=discord.ButtonStyle.grey, custom_id="scope_everyone", row=1)
    async def toggle_everyone(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_everyone = not self.mute_everyone
        button.style = discord.ButtonStyle.red if self.mute_everyone else discord.ButtonStyle.grey
        button.label = "@everyone: Muted" if self.mute_everyone else "@everyone: Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Next — Set Duration", style=discord.ButtonStyle.green, custom_id="scope_confirm", row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_realms and not self.mute_everyone:
            await interaction.response.send_message(
                "❌ Please select at least one realm or enable @everyone mute.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            SnoozeDurationModal(self.bot, self.selected_realms, self.mute_everyone)
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
        self.mute_everyone = False

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

    @discord.ui.button(label="@everyone: Unmuted", style=discord.ButtonStyle.grey, custom_id="sched_everyone", row=1)
    async def toggle_everyone(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute_everyone = not self.mute_everyone
        button.style = discord.ButtonStyle.red if self.mute_everyone else discord.ButtonStyle.grey
        button.label = "@everyone: Muted" if self.mute_everyone else "@everyone: Unmuted"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Next — Set Times", style=discord.ButtonStyle.green, custom_id="sched_confirm", row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_realms and not self.mute_everyone:
            await interaction.response.send_message(
                "❌ Please select at least one option.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ScheduleTimesModal(self.bot, self.selected_realms, self.mute_everyone)
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

# --- PING SCHEDULE MODALS ---
class SnoozeDurationModal(discord.ui.Modal, title="⏸️ Snooze Duration"):
    duration = discord.ui.TextInput(
        label="How long? (e.g. 2h, 30m, 1h30m, 2d)",
        placeholder="2h",
        max_length=10
    )

    def __init__(self, bot, realms, mute_everyone):
        super().__init__()
        self.bot = bot
        self.realms = realms
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

        if self.mute_everyone and FAKE_EVERYONE_ROLE_ID:
            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
            if fake_everyone and fake_everyone in interaction.user.roles:
                try:
                    await interaction.user.remove_roles(fake_everyone, reason="Snooze @everyone")
                except discord.Forbidden:
                    pass

        set_user_data(interaction.user.id, {
            "snooze_until": snooze_until.isoformat(),
            "is_muted": True,
            "muted_realms": muted_realms,
            "muted_everyone": self.mute_everyone,
        })

        user_data = get_user_data(interaction.user.id)
        tz_str = user_data.get("timezone", "Europe/London")
        scope = ", ".join(muted_realms) if muted_realms else "none"
        if self.mute_everyone:
            scope += " + @everyone"

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

    def __init__(self, bot, realms, mute_everyone):
        super().__init__()
        self.bot = bot
        self.realms = realms
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
            "schedule_everyone": self.mute_everyone,
        })

        scope = ", ".join(self.realms) if self.realms else "none"
        if self.mute_everyone:
            scope += " + @everyone"

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
            set_user_data(member.id, {"channel_id": None})

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

        set_user_data(member.id, {"channel_id": new_channel.id})

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
                        restored.append(realm)
                    except discord.Forbidden:
                        pass

        if user_data.get("muted_everyone") and FAKE_EVERYONE_ROLE_ID:
            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
            if fake_everyone and fake_everyone not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(fake_everyone, reason="Ping resume")
                    restored.append("@everyone")
                except discord.Forbidden:
                    pass

        set_user_data(interaction.user.id, {
            "snooze_until": None,
            "is_muted": False,
            "muted_realms": [],
            "muted_everyone": False,
        })

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
            "schedule_everyone": False,
        })
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
        set_user_data(interaction.user.id, {"channel_id": None})
        await interaction.response.send_message("👋 Closing your settings channel...", ephemeral=False)
        await interaction.channel.delete(reason="User closed their ping settings channel")

# --- PING SCHEDULE HELPERS ---
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

# --- ORIGINAL VOTE LOGIC ---
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

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- BACKGROUND TASKS ---
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

    guild = None
    for cid in VOTE_CONFIG:
        ch = bot.get_channel(cid)
        if ch:
            guild = ch.guild
            break
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

            # ── Snooze expiry ──
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
                                    restored.append(realm)
                                except discord.Forbidden:
                                    pass
                    if user_data.get("muted_everyone") and FAKE_EVERYONE_ROLE_ID:
                        fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                        if fake_everyone and fake_everyone not in member.roles:
                            try:
                                await member.add_roles(fake_everyone, reason="Snooze expired")
                                restored.append("@everyone")
                            except discord.Forbidden:
                                pass

                    data[uid].update({
                        "snooze_until": None,
                        "is_muted": False,
                        "muted_realms": [],
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

            # ── Sleep schedule ──
            sleep_time = user_data.get("sleep_time")
            wake_time  = user_data.get("wake_time")

            if sleep_time and wake_time and not snooze_until:
                try:
                    tz = pytz.timezone(tz_str)
                    local_now    = now_utc.astimezone(tz)
                    current_hhmm = local_now.strftime("%H:%M")
                    in_window    = is_in_sleep_window(current_hhmm, sleep_time, wake_time)

                    s_realms   = user_data.get("schedule_realms", [])
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
                        if s_everyone and FAKE_EVERYONE_ROLE_ID:
                            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                            if fake_everyone and fake_everyone in member.roles:
                                try:
                                    await member.remove_roles(fake_everyone, reason="Sleep schedule")
                                    muted_realms.append("@everyone")
                                except discord.Forbidden:
                                    pass

                        data[uid].update({
                            "is_muted": True,
                            "muted_realms": [r for r in muted_realms if r != "@everyone"],
                            "muted_everyone": "@everyone" in muted_realms,
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
                        if data[uid].get("muted_everyone") and FAKE_EVERYONE_ROLE_ID:
                            fake_everyone = guild.get_role(FAKE_EVERYONE_ROLE_ID)
                            if fake_everyone and fake_everyone not in member.roles:
                                try:
                                    await member.add_roles(fake_everyone, reason="Wake schedule")
                                    restored.append("@everyone")
                                except discord.Forbidden:
                                    pass

                        data[uid].update({
                            "is_muted": False,
                            "muted_realms": [],
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

# --- EVENTS ---
@bot.event
async def on_ready():
    bot.add_view(ClearLogsView())
    bot.add_view(BotControlView())
    bot.add_view(OpenSettingsView())
    bot.add_view(UserSettingsView(bot))
    if not auto_filler.is_running():
        auto_filler.change_interval(minutes=settings["prediction_interval"])
        auto_filler.start()
    if not check_ping_schedules.is_running():
        check_ping_schedules.start()
    channel = bot.get_channel(CONTROL_CHANNEL_ID)
    if channel:
        try: await channel.purge(limit=10, check=lambda m: m.author == bot.user)
        except: pass
        await channel.send(embed=discord.Embed(title="🛠️ Control Panel", color=0x2b2d31), view=BotControlView())

    ping_channel = bot.get_channel(PING_SETTINGS_CHANNEL_ID)
    if ping_channel:
        already_exists = False
        try:
            async for msg in ping_channel.history(limit=20):
                if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "🔔 Ping Settings":
                    already_exists = True
                    break
        except Exception:
            pass
        if not already_exists:
            embed = discord.Embed(
                title="🔔 Ping Settings",
                description=(
                    "Click the button below to open your **private ping settings channel**.\n\n"
                    "From there you can:\n"
                    "• ⏸️ **Snooze** specific realm pings and/or @everyone — for a set duration\n"
                    "• 😴 **Set a sleep schedule** to auto-disable pings overnight\n"
                    "• ▶️ **Resume** pings instantly at any time\n"
                    "• 🌍 **Set your timezone** from a dropdown list\n"
                    "• ❌ **Close** your settings channel when you're done"
                ),
                color=0x2b2d31
            )
            embed.set_footer(text="Your settings are saved even after closing the channel.")
            await ping_channel.send(embed=embed, view=OpenSettingsView())

    print(f'Logged in as {bot.user}')

@bot.event
async def on_guild_channel_delete(channel):
    """If a user's private settings channel is manually deleted, clear it from their data."""
    data = load_schedules()
    changed = False
    for uid, user_data in data.items():
        if user_data.get("channel_id") == channel.id:
            data[uid]["channel_id"] = None
            changed = True
            break
    if changed:
        save_schedules(data)

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