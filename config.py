# ─────────────────────────────────────────────
#  config.py — all server IDs go here
# ─────────────────────────────────────────────

# ── Guild ──
GUILD_ID = 1464894485657030689  # ← your server's guild ID

# Control panel channel
CONTROL_CHANNEL_ID = 1465006743833804853

# ── Vote channels ──
# Each entry: channel_id → (log_channel_id, ping_role_id, realm_name)
VOTE_CONFIG = {
    1464899189040349225: (1465011973497552896, 1464897712729231631, "Elysium"),
    1464899087550906388: (1465012077990117408, 1464897407023321159, "Arcane"),
    1464899132195082412: (1465012113343905865, 1464897604147216426, "Cosmic")
}

# ── Stats channels ──
# Each entry: channel_id → (log_channel_id, realm_name)
STATS_CONFIG = {
    1467319663502561370: (1467321751095742586, "Elysium"),
    1467319703289729065: (1467321844276138127, "Arcane"),
    1467319685249765580: (1467321781139411225, "Cosmic")
}

# ── Ping schedule ──
PING_SETTINGS_CHANNEL_ID = 1479290979793109126  # ← your #ping-settings channel ID
MOD_ROLE_ID               = 1464981865088811292  # ← your mod role ID
FAKE_EVERYONE_ROLE_ID     = 1479296920328470689  # ← your "Everyone Pings" role ID

# ── Dungeons ──
# Each entry: channel_id → (dungeon_ping_role_id, realm_name)
# Replace the placeholder IDs with your actual dungeon channel/role IDs
DUNGEON_CONFIG = {
    1464929084936032361: (1464991288603578388, "Elysium"),   # ← Elysium dungeon channel → (ping role, realm)
    1464928862713680002: (1464991532372332626, "Arcane"),    # ← Arcane dungeon channel  → (ping role, realm)
    1464928925317726219: (1464991516656140532, "Cosmic"),    # ← Cosmic dungeon channel  → (ping role, realm)
}

# Channel where mods can configure dungeon settings (inactivity timeout, etc.)
DUNGEON_SETTINGS_CHANNEL_ID = 1479593242008883200  # ← your #dungeon-settings channel ID

PARTY_SIZE = 3          # Number of players needed to fill a party
DEFAULT_INACTIVITY_MINUTES = 60  # Default minutes before an inactive party is disbanded

# ── Price checker ──
PRICE_PUBLIC_CHANNEL_ID  = 1479923499085725797  # ← public channel where users run /itemprice
PRICE_REVIEW_CHANNEL_ID  = 1479923768238276629  # ← private channel where mods review submissions
PRICE_CHECK_CHANNEL_ID   = 1479969730197721118  # ← public channel where users run /checkprice
PRICE_CHECKER_ROLE_ID    = 1479923531814015076  # ← role that can confirm/deny/unsure prices
ITEMS_API_URL            = "https://www.mystic.atn.gg/api/items"
UNSURE_VOTES_NEEDED      = 2   # votes needed to reach consensus when marked unsure
VALID_SERVERS            = ["elysium", "arcane", "cosmic"]

# ── Inventory ──
INVENTORY_CHANNEL_ID  = 1479972971383754875  # ← channel where users run /createinventory
NETWORTH_CHANNEL_ID   = 1479977608874692843  # ← channel where users run /networth
INVENTORY_CATEGORY_ID = 1479923274476683474  # ← category to create inventory channels under
