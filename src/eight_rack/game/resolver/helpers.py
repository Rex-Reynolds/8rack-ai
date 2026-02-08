"""Shared constants and utility functions for the resolver package."""

from __future__ import annotations

from ...cards.models import CardDefinition, CardType
from ..state import CardInstance


# Modal spells: card_name → list of (mode_key, description)
MODAL_SPELLS: dict[str, list[tuple[str, str]]] = {
    "Funeral Charm": [
        ("discard", "Funeral Charm: Target player discards a card"),
        ("pump", "Funeral Charm: Target creature gets +2/-1"),
        ("shrink", "Funeral Charm: Target creature gets -1/-1"),
    ],
    "Sheoldred's Edict": [
        ("creature", "Sheoldred's Edict: Opponent sacrifices a creature"),
        ("planeswalker", "Sheoldred's Edict: Opponent sacrifices a planeswalker"),
    ],
}

# Targeted removal spells that need explicit target selection
TARGETED_REMOVAL: set[str] = {
    "Fatal Push",
    "Bloodchief's Thirst",
    "Lightning Bolt",
    "Dismember",
    "Galvanic Discharge",
}

# Fetchland → list of basic land types it can find
FETCH_TARGETS: dict[str, list[str]] = {
    "Arid Mesa": ["Mountain", "Plains"],
    "Bloodstained Mire": ["Swamp", "Mountain"],
    "Flooded Strand": ["Plains", "Island"],
    "Marsh Flats": ["Plains", "Swamp"],
    "Misty Rainforest": ["Forest", "Island"],
    "Polluted Delta": ["Island", "Swamp"],
    "Scalding Tarn": ["Island", "Mountain"],
    "Verdant Catacombs": ["Swamp", "Forest"],
    "Windswept Heath": ["Forest", "Plains"],
    "Wooded Foothills": ["Mountain", "Forest"],
}

# Basic land type → land names that have that type (for shock land fetching)
BASIC_TYPE_LANDS: dict[str, list[str]] = {
    "Plains": ["Plains", "Hallowed Fountain", "Sacred Foundry", "Temple Garden", "Godless Shrine"],
    "Island": ["Island", "Hallowed Fountain", "Steam Vents", "Breeding Pool", "Watery Grave"],
    "Swamp": ["Swamp", "Blood Crypt", "Overgrown Tomb", "Watery Grave", "Godless Shrine"],
    "Mountain": ["Mountain", "Sacred Foundry", "Steam Vents", "Blood Crypt", "Stomping Ground"],
    "Forest": ["Forest", "Temple Garden", "Overgrown Tomb", "Breeding Pool", "Stomping Ground"],
}

# Dual/shock land → (color1, color2) — both colors the land can produce
DUAL_LAND_COLORS: dict[str, tuple[str, str]] = {
    "Sacred Foundry": ("white", "red"),
    "Hallowed Fountain": ("white", "blue"),
    "Steam Vents": ("blue", "red"),
    "Blood Crypt": ("black", "red"),
    "Overgrown Tomb": ("black", "green"),
    "Stomping Ground": ("red", "green"),
    "Temple Garden": ("white", "green"),
    "Watery Grave": ("blue", "black"),
    "Godless Shrine": ("white", "black"),
    "Breeding Pool": ("blue", "green"),
}


def scry(state, player_id: str, n: int, agent=None) -> list[str]:
    """Scry N: look at top N cards, choose which to keep on top and which to put on bottom.

    If no agent or no choose_scry method, use heuristic:
    keep lands if < 4 lands on battlefield, otherwise keep non-lands.
    Returns log descriptions.
    """
    from ..state import Zone
    player = state.get_player(player_id)
    lib = player.library
    if not lib:
        return ["Scry: library empty"]

    top_cards = lib[:n]
    if not top_cards:
        return ["Scry: no cards to look at"]

    # Ask agent for scry choices
    keep_on_top = []
    put_on_bottom = []

    if agent and hasattr(agent, "choose_scry"):
        choices = agent.choose_scry(top_cards, n)
        if choices:
            keep_ids = set(choices.get("top", []))
            for card in top_cards:
                if card.id in keep_ids:
                    keep_on_top.append(card)
                else:
                    put_on_bottom.append(card)

    if not keep_on_top and not put_on_bottom:
        # Heuristic: keep non-lands on top if we have enough lands
        land_count = sum(1 for c in player.battlefield if c.definition.is_land)
        for card in top_cards:
            if card.definition.is_land and land_count >= 4:
                put_on_bottom.append(card)
            elif not card.definition.is_land and land_count < 2:
                put_on_bottom.append(card)
            else:
                keep_on_top.append(card)

    # Rearrange library: keep_on_top first, then rest of library, then put_on_bottom
    remaining = [c for c in lib if c not in top_cards]
    new_lib_order = keep_on_top + remaining + put_on_bottom
    # Update zone order by reassigning indices (library is a computed property)
    # We need to manipulate the underlying cards list
    lib_set = set(c.id for c in player.library)
    non_lib = [c for c in player.cards if c.id not in lib_set]
    player.cards = non_lib + new_lib_order

    changes = [f"Scry {n}: {len(keep_on_top)} on top, {len(put_on_bottom)} on bottom"]
    return changes


def destroy_all_creatures(state) -> list[str]:
    """Destroy all creatures on the battlefield. Returns descriptions.

    Respects indestructible.
    """
    from ..state import Zone
    changes = []
    for player in state.players:
        for card in player.battlefield[:]:
            if card.definition.is_creature:
                is_indestructible = "Indestructible" in card.definition.keywords
                if not is_indestructible:
                    card.zone = Zone.GRAVEYARD
                    changes.append(f"{card.name} destroyed")
                else:
                    changes.append(f"{card.name} survives (indestructible)")
    return changes


# Evoke costs: card_name → evoke mana cost
# These creatures can be cast for their evoke cost; they ETB, trigger fires, then sacrifice
EVOKE_COSTS: dict[str, str] = {
    "Solitude": "{W}",      # Exile creature, gain life (pitch a white card)
    "Endurance": "{G}",     # Shuffle graveyard into library (pitch a green card)
    "Grief": "{B}",         # Thoughtseize on ETB (pitch a black card)
    "Fury": "{R}{R}",       # Deal 4 divided damage (pitch a red card)
    "Subtlety": "{U}{U}",   # Aether Gust creature/PW (pitch a blue card)
}


def _is_creature(card: CardInstance) -> bool:
    """Check if a card is currently a creature (by definition or animation)."""
    if card.definition.is_creature:
        return True
    # Mishra's Factory animated into a 2/2 Assembly-Worker
    if card.counters.get("animated"):
        return True
    return False


def _effective_power(card: CardInstance) -> int:
    """Return effective power accounting for counters, temp effects, and animation."""
    if card.counters.get("animated") and not card.definition.is_creature:
        base = 2  # Mishra's Factory is a 2/2 when animated
    else:
        base = int(card.definition.power or "0")
    base += card.counters.get("p1p1", 0)
    base -= card.counters.get("m1m1_temp", 0)
    base += card.counters.get("pump_power_temp", 0)
    return base


def _effective_toughness(card: CardInstance) -> int:
    """Return effective toughness accounting for counters, temp effects, and animation."""
    if card.counters.get("animated") and not card.definition.is_creature:
        base = 2  # Mishra's Factory is a 2/2 when animated
    else:
        base = int(card.definition.toughness or "0")
    base += card.counters.get("p1p1", 0)
    base -= card.counters.get("m1m1_temp", 0)
    base += card.counters.get("pump_toughness_temp", 0)
    return base
