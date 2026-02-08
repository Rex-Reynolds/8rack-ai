"""Core game state models."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..cards.models import CardDefinition


class Zone(str, Enum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    STACK = "stack"
    COMMAND = "command"  # for sideboard during games


class Phase(str, Enum):
    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    MAIN_1 = "main_1"
    BEGIN_COMBAT = "begin_combat"
    DECLARE_ATTACKERS = "declare_attackers"
    DECLARE_BLOCKERS = "declare_blockers"
    COMBAT_DAMAGE = "combat_damage"
    END_COMBAT = "end_combat"
    MAIN_2 = "main_2"
    END_STEP = "end_step"
    CLEANUP = "cleanup"


PHASE_ORDER = list(Phase)

MAIN_PHASES = {Phase.MAIN_1, Phase.MAIN_2}


class CardInstance(BaseModel):
    """A specific instance of a card in a game."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    definition: CardDefinition
    zone: Zone = Zone.LIBRARY
    owner: str = ""  # player id
    controller: str = ""  # player id (can differ from owner)
    tapped: bool = False
    sick: bool = False  # summoning sickness
    counters: dict[str, int] = Field(default_factory=dict)
    attached_to: Optional[str] = None  # id of card this is attached to
    damage_marked: int = 0
    revealed_to: list[str] = Field(default_factory=list)  # player ids who can see this

    @property
    def name(self) -> str:
        return self.definition.name

    def reset_for_turn(self) -> None:
        """Reset per-turn state."""
        self.damage_marked = 0


class ManaPool(BaseModel):
    """Mana available to a player."""

    white: int = 0
    blue: int = 0
    black: int = 0
    red: int = 0
    green: int = 0
    colorless: int = 0

    def total(self) -> int:
        return self.white + self.blue + self.black + self.red + self.green + self.colorless

    def can_pay(self, cost: str) -> bool:
        """Check if this pool can pay a mana cost string like '{1}{B}{B}'."""
        required = parse_mana_cost(cost)
        pool = self.model_copy()
        # Pay colored first
        for color, attr in [("W", "white"), ("U", "blue"), ("B", "black"), ("R", "red"), ("G", "green")]:
            needed = required.get(color, 0)
            available = getattr(pool, attr)
            if available < needed:
                return False
            setattr(pool, attr, available - needed)
        # Pay generic with remaining
        generic = required.get("generic", 0)
        return pool.total() >= generic

    def pay(self, cost: str) -> None:
        """Pay a mana cost, removing mana from the pool."""
        required = parse_mana_cost(cost)
        for color, attr in [("W", "white"), ("U", "blue"), ("B", "black"), ("R", "red"), ("G", "green")]:
            needed = required.get(color, 0)
            current = getattr(self, attr)
            setattr(self, attr, current - needed)
        generic = required.get("generic", 0)
        # Pay generic from colorless first, then any color
        take = min(self.colorless, generic)
        self.colorless -= take
        generic -= take
        for attr in ["black", "red", "green", "white", "blue"]:
            if generic <= 0:
                break
            take = min(getattr(self, attr), generic)
            setattr(self, attr, getattr(self, attr) - take)
            generic -= take

    def empty(self) -> None:
        self.white = self.blue = self.black = self.red = self.green = self.colorless = 0


def parse_mana_cost(cost: str) -> dict[str, int]:
    """Parse a mana cost string like '{1}{B}{B}' into component parts."""
    result: dict[str, int] = {"generic": 0}
    if not cost:
        return result

    i = 0
    while i < len(cost):
        if cost[i] == "{":
            end = cost.index("}", i)
            symbol = cost[i + 1 : end]
            if symbol.isdigit():
                result["generic"] += int(symbol)
            elif symbol == "X":
                pass  # X costs handled separately
            else:
                result[symbol] = result.get(symbol, 0) + 1
            i = end + 1
        else:
            i += 1
    return result


class PlayerState(BaseModel):
    """State of a single player in the game."""

    id: str
    name: str
    life: int = 20
    mana_pool: ManaPool = Field(default_factory=ManaPool)
    land_drops_remaining: int = 1
    land_drops_per_turn: int = 1
    cards: list[CardInstance] = Field(default_factory=list)
    has_drawn_for_turn: bool = False
    has_lost: bool = False
    poison_counters: int = 0

    def zone(self, zone: Zone) -> list[CardInstance]:
        """Get all cards in a given zone for this player."""
        return [c for c in self.cards if c.zone == zone]

    @property
    def hand(self) -> list[CardInstance]:
        return self.zone(Zone.HAND)

    @property
    def library(self) -> list[CardInstance]:
        return self.zone(Zone.LIBRARY)

    @property
    def battlefield(self) -> list[CardInstance]:
        return self.zone(Zone.BATTLEFIELD)

    @property
    def graveyard(self) -> list[CardInstance]:
        return self.zone(Zone.GRAVEYARD)

    @property
    def hand_size(self) -> int:
        return len(self.hand)

    def find_card(self, card_id: str) -> CardInstance | None:
        for c in self.cards:
            if c.id == card_id:
                return c
        return None

    def draw(self, n: int = 1) -> list[CardInstance]:
        """Draw n cards from the library. Returns drawn cards."""
        drawn = []
        lib = self.library
        for _ in range(n):
            if not lib:
                self.has_lost = True  # decked
                break
            card = lib.pop(0)  # top of library
            card.zone = Zone.HAND
            drawn.append(card)
            lib = self.library  # refresh reference
        return drawn

    def discard(self, card_id: str) -> CardInstance | None:
        """Discard a specific card from hand to graveyard."""
        card = self.find_card(card_id)
        if card and card.zone == Zone.HAND:
            card.zone = Zone.GRAVEYARD
            return card
        return None

    def discard_random(self) -> CardInstance | None:
        """Discard a random card from hand."""
        import random
        hand = self.hand
        if not hand:
            return None
        card = random.choice(hand)
        card.zone = Zone.GRAVEYARD
        return card


class StackItem(BaseModel):
    """An item on the stack (spell or ability)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_card_id: str | None = None
    source_card_name: str = ""
    controller: str = ""
    description: str = ""
    targets: list[str] = Field(default_factory=list)  # card_ids or "player:<id>"
    is_ability: bool = False
    # For spells: the card instance on the stack
    card_instance: CardInstance | None = None
    # The pending action for deferred resolution (stored as dict to avoid circular import)
    action_data: Optional[dict] = None


class CombatState(BaseModel):
    """Tracks combat state during the combat phase."""

    attackers: list[str] = Field(default_factory=list)  # card_ids
    blockers: dict[str, str] = Field(default_factory=dict)  # blocker_id → attacker_id


class GameState(BaseModel):
    """Complete state of a game in progress."""

    players: list[PlayerState]
    active_player_index: int = 0
    priority_player_index: int = 0
    phase: Phase = Phase.UNTAP
    turn_number: int = 1
    stack: list[StackItem] = Field(default_factory=list)
    combat: CombatState = Field(default_factory=CombatState)
    spells_cast_this_turn: int = 0
    game_over: bool = False
    winner: str | None = None
    game_log: list[str] = Field(default_factory=list)

    @property
    def active_player(self) -> PlayerState:
        return self.players[self.active_player_index]

    @property
    def priority_player(self) -> PlayerState:
        return self.players[self.priority_player_index]

    @property
    def non_active_player(self) -> PlayerState:
        return self.players[1 - self.active_player_index]

    def get_player(self, player_id: str) -> PlayerState:
        for p in self.players:
            if p.id == player_id:
                return p
        raise ValueError(f"Player not found: {player_id}")

    def opponent_of(self, player_id: str) -> PlayerState:
        for p in self.players:
            if p.id != player_id:
                return p
        raise ValueError(f"No opponent found for: {player_id}")

    def log(self, message: str) -> None:
        self.game_log.append(f"T{self.turn_number} {self.phase.value}: {message}")

    def graveyard_destination(self, card_owner_id: str) -> Zone:
        """Return where a card should go when it would be put into a graveyard.

        Leyline of the Void: if opponent controls one, cards go to exile instead.
        """
        for p in self.players:
            if p.id == card_owner_id:
                continue  # Leyline only affects opponent's cards
            for c in p.battlefield:
                if c.name == "Leyline of the Void":
                    return Zone.EXILE
        return Zone.GRAVEYARD

    def check_state_based_actions(self) -> list[str]:
        """Check and apply state-based actions. Returns descriptions of what happened."""
        actions = []
        for p in self.players:
            if p.life <= 0 and not p.has_lost:
                p.has_lost = True
                actions.append(f"{p.name} loses (life <= 0)")
            if p.has_lost and not self.game_over:
                self.game_over = True
                self.winner = self.opponent_of(p.id).id
                actions.append(f"Game over. Winner: {self.winner}")

            # Creature with 0 or less toughness or lethal damage
            for card in p.battlefield:
                if card.definition.is_creature:
                    # Indestructible creatures survive damage-based destruction
                    is_indestructible = "Indestructible" in card.definition.keywords
                    base_toughness = int(card.definition.toughness or "0")
                    # Account for +1/+1, -1/-1 temp, and pump_toughness_temp
                    toughness = (
                        base_toughness
                        + card.counters.get("p1p1", 0)
                        - card.counters.get("m1m1_temp", 0)
                        + card.counters.get("pump_toughness_temp", 0)
                    )
                    if toughness <= 0:
                        card.zone = Zone.GRAVEYARD
                        actions.append(f"{card.name} dies (0 toughness)")
                    elif card.damage_marked >= toughness and not is_indestructible:
                        card.zone = Zone.GRAVEYARD
                        actions.append(f"{card.name} dies (lethal damage)")
                    elif card.counters.get("deathtouch_damage") and not is_indestructible:
                        card.zone = Zone.GRAVEYARD
                        card.counters.pop("deathtouch_damage", None)
                        actions.append(f"{card.name} dies (deathtouch)")

            # Saga with final chapter reached
            for card in p.battlefield:
                if card.definition.is_saga and card.counters.get("lore", 0) >= 3:
                    card.zone = Zone.GRAVEYARD
                    actions.append(f"SBA: {card.name} sacrificed (final chapter)")

            # Planeswalker with 0 loyalty
            for card in p.battlefield:
                if card.definition.is_planeswalker:
                    loyalty = card.counters.get("loyalty", 0)
                    if loyalty <= 0:
                        card.zone = Zone.GRAVEYARD
                        actions.append(f"{card.name} goes to graveyard (0 loyalty)")

            # Legend rule: if multiple legendaries with same name, keep newest (last in list)
            legendary_names: dict[str, list[CardInstance]] = {}
            for card in p.battlefield:
                if card.definition.is_legendary:
                    legendary_names.setdefault(card.name, []).append(card)
            for name, legends in legendary_names.items():
                if len(legends) > 1:
                    # Keep the last one (newest), send the rest to graveyard
                    for card in legends[:-1]:
                        card.zone = Zone.GRAVEYARD
                        actions.append(f"Legend rule: {card.name} goes to graveyard")

        return actions


class VisibleGameState(BaseModel):
    """Game state visible to a specific player (hides opponent's hand)."""

    viewer_id: str
    viewer_life: int
    viewer_hand: list[str]  # card names
    viewer_hand_ids: list[str]  # card instance ids (for action targeting)
    viewer_battlefield: list[dict]  # simplified card info
    viewer_graveyard: list[str]
    viewer_library_size: int
    viewer_mana_pool: ManaPool
    viewer_land_drops: int
    opponent_life: int
    opponent_hand_size: int
    opponent_battlefield: list[dict]
    opponent_graveyard: list[str]
    opponent_library_size: int
    phase: Phase
    turn_number: int
    active_player: str
    stack: list[dict]

    @classmethod
    def from_game_state(cls, state: GameState, viewer_id: str) -> VisibleGameState:
        viewer = state.get_player(viewer_id)
        opponent = state.opponent_of(viewer_id)

        def card_info(card: CardInstance) -> dict:
            return {
                "id": card.id,
                "name": card.name,
                "tapped": card.tapped,
                "counters": card.counters,
                "power": card.definition.power,
                "toughness": card.definition.toughness,
                "type_line": card.definition.type_line,
            }

        return cls(
            viewer_id=viewer_id,
            viewer_life=viewer.life,
            viewer_hand=[c.name for c in viewer.hand],
            viewer_hand_ids=[c.id for c in viewer.hand],
            viewer_battlefield=[card_info(c) for c in viewer.battlefield],
            viewer_graveyard=[c.name for c in viewer.graveyard],
            viewer_library_size=len(viewer.library),
            viewer_mana_pool=viewer.mana_pool,
            viewer_land_drops=viewer.land_drops_remaining,
            opponent_life=opponent.life,
            opponent_hand_size=opponent.hand_size,
            opponent_battlefield=[card_info(c) for c in opponent.battlefield],
            opponent_graveyard=[c.name for c in opponent.graveyard],
            opponent_library_size=len(opponent.library),
            phase=state.phase,
            turn_number=state.turn_number,
            active_player=state.active_player.id,
            stack=[
                {"id": s.id, "description": s.description, "controller": s.controller}
                for s in state.stack
            ],
        )
