# ─────────────────────────────────────────────
#  config.py — all server IDs go here
# ─────────────────────────────────────────────

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
