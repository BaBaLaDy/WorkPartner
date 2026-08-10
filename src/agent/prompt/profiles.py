"""Profile definitions for PromptAssembler.

Each profile is an ordered list of section renderer names.
The assembler enforces cache-aware ordering: stable sections first,
volatile sections last, regardless of profile definition order.
"""

# Stable sections: high cache hit, placed at the prefix
_STABLE = {
    "role_header",
    "base_rules",
    "role_presence",
    "skills",
    "subagent_rules",
    "thinking_protocol",
    "team_delegation",
    "supervisor_rules",
}

# Volatile sections: low cache hit, placed at the suffix
_VOLATILE = {
    "conversation_mode",
    "memory",
    "role_memory",
    "runtime",
    "daily_log",
    "insights",
    "action_items",
    "user_prefs",
}


PROFILES: dict[str, list[str]] = {
    # Interactive sessions (CLI + web UI direct chat)
    "interactive": [
        "role_header",
        "base_rules",
        "role_presence",
        "skills",
        "conversation_mode",
        "memory",
        "runtime",
    ],

    # Managed sessions (background todo tasks)
    "managed": [
        "role_header",
        "base_rules",
        "role_presence",
        "team_delegation",
        "memory",
        "runtime",
    ],

    # SubAgent sessions (tasks delegated via subagent_batch tool)
    "subagent": [
        "role_header",
        "role_presence",
        "role_memory",
        "subagent_rules",
        "thinking_protocol",
        "runtime",
    ],

    # Supervisor sessions (global observer / daily reports)
    "supervisor": [
        "supervisor_rules",
        "daily_log",
        "insights",
        "action_items",
        "user_prefs",
        "skills",
        "conversation_mode",
        "runtime",
    ],
}


def get_ordered_sections(profile: str) -> list[str]:
    """Return sections in cache-aware order: stable first, volatile last."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    profile_sections = PROFILES[profile]
    stable = [s for s in profile_sections if s in _STABLE]
    volatile = [s for s in profile_sections if s in _VOLATILE]
    return stable + volatile


def is_stable(section: str) -> bool:
    """Check if a section is considered stable (high cache hit)."""
    return section in _STABLE
