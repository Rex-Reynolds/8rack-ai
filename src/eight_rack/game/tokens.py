"""Token creation utility for the game engine."""

from __future__ import annotations

from ..cards.models import CardDefinition, CardType, Color
from .state import CardInstance, Zone


def create_token(
    controller_id: str,
    name: str,
    type_line: str,
    card_types: list[CardType],
    subtypes: list[str] | None = None,
    power: str = "0",
    toughness: str = "0",
    oracle_text: str = "",
    keywords: list[str] | None = None,
    colors: list[Color] | None = None,
    counters: dict[str, int] | None = None,
) -> CardInstance:
    """Create a token on the battlefield.

    Returns a CardInstance with a synthetic CardDefinition.
    Caller must append to player.cards.
    """
    token_def = CardDefinition(
        name=name,
        type_line=type_line,
        card_types=card_types,
        subtypes=subtypes or [],
        power=power,
        toughness=toughness,
        oracle_text=oracle_text,
        keywords=keywords or [],
        colors=colors or [],
    )
    token = CardInstance(
        definition=token_def,
        zone=Zone.BATTLEFIELD,
        owner=controller_id,
        controller=controller_id,
        sick=CardType.CREATURE in card_types,
    )
    if counters:
        token.counters.update(counters)
    return token


def create_treasure_token(controller_id: str) -> CardInstance:
    """Create a Treasure token artifact.

    Treasures can be sacrificed to add one mana of any color.
    Caller must append to player.cards.
    """
    return create_token(
        controller_id=controller_id,
        name="Treasure",
        type_line="Token Artifact — Treasure",
        card_types=[CardType.ARTIFACT],
        subtypes=["Treasure"],
        oracle_text="{T}, Sacrifice this artifact: Add one mana of any color.",
    )
