"""Card definition models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CardType(str, Enum):
    CREATURE = "creature"
    INSTANT = "instant"
    SORCERY = "sorcery"
    ENCHANTMENT = "enchantment"
    ARTIFACT = "artifact"
    PLANESWALKER = "planeswalker"
    LAND = "land"


class Color(str, Enum):
    WHITE = "W"
    BLUE = "U"
    BLACK = "B"
    RED = "R"
    GREEN = "G"
    COLORLESS = "C"


class CardDefinition(BaseModel):
    """A card definition from Scryfall, cached locally."""

    name: str
    mana_cost: str = ""
    cmc: float = 0.0
    type_line: str = ""
    oracle_text: str = ""
    power: Optional[str] = None
    toughness: Optional[str] = None
    loyalty: Optional[str] = None
    colors: list[Color] = Field(default_factory=list)
    color_identity: list[Color] = Field(default_factory=list)
    card_types: list[CardType] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    scryfall_id: str = ""
    legalities: dict[str, str] = Field(default_factory=dict)

    @property
    def is_creature(self) -> bool:
        return CardType.CREATURE in self.card_types

    @property
    def is_land(self) -> bool:
        return CardType.LAND in self.card_types

    @property
    def is_instant(self) -> bool:
        return CardType.INSTANT in self.card_types

    @property
    def is_sorcery(self) -> bool:
        return CardType.SORCERY in self.card_types

    @property
    def is_planeswalker(self) -> bool:
        return CardType.PLANESWALKER in self.card_types

    @property
    def is_artifact(self) -> bool:
        return CardType.ARTIFACT in self.card_types

    @property
    def is_enchantment(self) -> bool:
        return CardType.ENCHANTMENT in self.card_types

    @property
    def is_saga(self) -> bool:
        return "Saga" in self.subtypes

    @property
    def is_legendary(self) -> bool:
        return "Legendary" in self.type_line

    @classmethod
    def from_scryfall(cls, data: dict) -> CardDefinition:
        """Parse a Scryfall API response into a CardDefinition.

        Handles DFCs/MDFCs/split cards by using front face data when
        top-level fields are missing (Scryfall puts per-face data in card_faces).
        """
        # For DFCs/MDFCs, Scryfall puts oracle_text, mana_cost, etc. on card_faces
        faces = data.get("card_faces", [])
        front = faces[0] if faces else {}

        # Use front face data as fallback for missing top-level fields
        type_line = data.get("type_line", front.get("type_line", ""))
        oracle_text = data.get("oracle_text", front.get("oracle_text", ""))
        mana_cost = data.get("mana_cost", front.get("mana_cost", ""))
        power = data.get("power", front.get("power"))
        toughness = data.get("toughness", front.get("toughness"))
        loyalty = data.get("loyalty", front.get("loyalty"))
        colors = data.get("colors", front.get("colors", []))

        card_types = []
        type_lower = type_line.lower()
        for ct in CardType:
            if ct.value in type_lower:
                card_types.append(ct)

        subtypes = []
        if " — " in type_line:
            subtypes = [s.strip() for s in type_line.split(" — ")[1].split()]

        parsed_colors = [Color(c) for c in colors]
        color_identity = [Color(c) for c in data.get("color_identity", [])]

        return cls(
            name=data["name"],
            mana_cost=mana_cost,
            cmc=data.get("cmc", 0.0),
            type_line=type_line,
            oracle_text=oracle_text,
            power=power,
            toughness=toughness,
            loyalty=loyalty,
            colors=parsed_colors,
            color_identity=color_identity,
            card_types=card_types,
            subtypes=subtypes,
            keywords=data.get("keywords", []),
            scryfall_id=data.get("id", ""),
            legalities=data.get("legalities", {}),
        )
