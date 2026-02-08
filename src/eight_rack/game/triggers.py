"""Trigger system: registry-based trigger detection and stack item creation."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable, Optional

from ..cards.models import CardType
from .actions import ActionResult
from .state import CardInstance, GameState, StackItem, Zone
from .tokens import create_token

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    UPKEEP = "upkeep"
    ETB = "etb"
    DIES = "dies"
    ATTACK = "attack"
    DRAW_CARD = "draw_card"
    CAST_SPELL = "cast_spell"
    DEALS_DAMAGE = "deals_damage"
    LEAVES_BATTLEFIELD = "leaves_battlefield"


# Handler signature: (state, source_card, **context) → StackItem | None
TriggerHandler = Callable[..., Optional[StackItem]]

# Resolution handler: (state, stack_item) → ActionResult
TriggerResolver = Callable[[GameState, StackItem], ActionResult]


class TriggerRegistry:
    """Maps (card_name, trigger_type) → handler that creates StackItems."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, TriggerType], TriggerHandler] = {}
        self._resolvers: dict[str, TriggerResolver] = {}
        self._register_defaults()

    def register(
        self,
        card_name: str,
        trigger_type: TriggerType,
        handler: TriggerHandler,
        resolver: TriggerResolver | None = None,
    ) -> None:
        self._handlers[(card_name, trigger_type)] = handler
        if resolver:
            self._resolvers[card_name] = resolver

    def check_triggers(
        self,
        state: GameState,
        trigger_type: TriggerType,
        source_card: CardInstance | None = None,
        **context,
    ) -> list[StackItem]:
        """Check all permanents for triggers of the given type. Returns StackItems to put on stack."""
        items: list[StackItem] = []

        if trigger_type == TriggerType.ETB and source_card:
            # Only check the card that just entered
            key = (source_card.name, trigger_type)
            handler = self._handlers.get(key)
            if handler:
                item = handler(state, source_card, **context)
                if item:
                    items.append(item)
            return items

        # For upkeep and other global triggers, scan all permanents
        for player in state.players:
            for card in player.battlefield:
                key = (card.name, trigger_type)
                handler = self._handlers.get(key)
                if handler:
                    item = handler(state, card, **context)
                    if item:
                        items.append(item)

        return items

    def get_handler(self, card_name: str, item: StackItem) -> TriggerResolver | None:
        """Get the resolution handler for a triggered ability."""
        return self._resolvers.get(card_name)

    def _register_defaults(self) -> None:
        """Register default trigger handlers for known cards."""
        # The Rack: upkeep trigger
        self.register(
            "The Rack",
            TriggerType.UPKEEP,
            handler=_the_rack_trigger,
            resolver=_resolve_the_rack,
        )

        # Shrieking Affliction: upkeep trigger
        self.register(
            "Shrieking Affliction",
            TriggerType.UPKEEP,
            handler=_shrieking_affliction_trigger,
            resolver=_resolve_shrieking_affliction,
        )

        # Orcish Bowmasters: draw trigger
        self.register(
            "Orcish Bowmasters",
            TriggerType.DRAW_CARD,
            handler=_bowmasters_draw_trigger,
            resolver=_resolve_bowmasters_trigger,
        )

        # Orcish Bowmasters: ETB trigger
        self.register(
            "Orcish Bowmasters",
            TriggerType.ETB,
            handler=_bowmasters_etb_trigger,
            resolver=_resolve_bowmasters_trigger,
        )


# --- Trigger Handlers (create StackItems) ---


def _the_rack_trigger(state: GameState, card: CardInstance, **ctx) -> StackItem | None:
    """The Rack triggers at beginning of each opponent's upkeep."""
    opponent = state.opponent_of(card.controller)
    # Only triggers during the opponent's upkeep
    if state.active_player.id != opponent.id:
        return None
    hand_size = opponent.hand_size
    if hand_size >= 3:
        return None
    damage = 3 - hand_size
    return StackItem(
        source_card_id=card.id,
        source_card_name="The Rack",
        controller=card.controller,
        description=f"The Rack deals {damage} to {opponent.name} (hand size: {hand_size})",
        targets=[f"player:{opponent.id}"],
        is_ability=True,
    )


def _shrieking_affliction_trigger(state: GameState, card: CardInstance, **ctx) -> StackItem | None:
    """Shrieking Affliction triggers at beginning of each opponent's upkeep if hand <= 1."""
    opponent = state.opponent_of(card.controller)
    if state.active_player.id != opponent.id:
        return None
    if opponent.hand_size > 1:
        return None
    return StackItem(
        source_card_id=card.id,
        source_card_name="Shrieking Affliction",
        controller=card.controller,
        description=f"Shrieking Affliction deals 3 to {opponent.name} (hand size: {opponent.hand_size})",
        targets=[f"player:{opponent.id}"],
        is_ability=True,
    )


def _bowmasters_draw_trigger(state: GameState, card: CardInstance, **ctx) -> StackItem | None:
    """Orcish Bowmasters triggers when an opponent draws a card (except first each turn)."""
    drawing_player_id = ctx.get("drawing_player_id")
    if not drawing_player_id or drawing_player_id == card.controller:
        return None
    opponent = state.opponent_of(card.controller)
    return StackItem(
        source_card_id=card.id,
        source_card_name="Orcish Bowmasters",
        controller=card.controller,
        description=f"Orcish Bowmasters triggers (opponent drew a card)",
        targets=[f"player:{opponent.id}"],
        is_ability=True,
    )


def _bowmasters_etb_trigger(state: GameState, card: CardInstance, **ctx) -> StackItem | None:
    """Orcish Bowmasters ETB: deal 1 damage, amass Orcs 1."""
    opponent = state.opponent_of(card.controller)
    return StackItem(
        source_card_id=card.id,
        source_card_name="Orcish Bowmasters",
        controller=card.controller,
        description=f"Orcish Bowmasters ETB: deal 1 to {opponent.name}",
        targets=[f"player:{opponent.id}"],
        is_ability=True,
    )


# --- Trigger Resolvers ---


def _resolve_the_rack(state: GameState, item: StackItem) -> ActionResult:
    """Resolve The Rack trigger — deal damage based on opponent's hand size."""
    if not item.targets:
        return ActionResult(success=True, message="The Rack trigger fizzles (no target)")
    target_id = item.targets[0].replace("player:", "")
    target = state.get_player(target_id)
    hand_size = target.hand_size
    if hand_size >= 3:
        return ActionResult(success=True, message="The Rack: no damage (hand size >= 3)")
    damage = 3 - hand_size
    target.life -= damage
    return ActionResult(
        success=True,
        message=f"The Rack deals {damage} to {target.name} (hand size: {hand_size})",
        state_changes=[f"{target.name} takes {damage} damage (life: {target.life})"],
        tier_used=2,
    )


def _resolve_shrieking_affliction(state: GameState, item: StackItem) -> ActionResult:
    """Resolve Shrieking Affliction trigger — deal 3 if hand <= 1."""
    if not item.targets:
        return ActionResult(success=True, message="Shrieking Affliction fizzles")
    target_id = item.targets[0].replace("player:", "")
    target = state.get_player(target_id)
    if target.hand_size > 1:
        return ActionResult(success=True, message="Shrieking Affliction: no damage (hand > 1)")
    target.life -= 3
    return ActionResult(
        success=True,
        message=f"Shrieking Affliction deals 3 to {target.name} (hand size: {target.hand_size})",
        state_changes=[f"{target.name} takes 3 damage (life: {target.life})"],
        tier_used=2,
    )


def _resolve_bowmasters_trigger(state: GameState, item: StackItem) -> ActionResult:
    """Resolve Orcish Bowmasters trigger — deal 1, amass Orcs 1."""
    if not item.targets:
        return ActionResult(success=True, message="Bowmasters trigger fizzles")
    target_id = item.targets[0].replace("player:", "")
    target = state.get_player(target_id)
    target.life -= 1
    changes = [f"{target.name} takes 1 damage (life: {target.life})"]

    # Amass Orcs 1: find existing Army or create a 0/0 Orc Army token
    controller = state.get_player(item.controller)
    army = next(
        (c for c in controller.battlefield if "Army" in c.definition.subtypes),
        None,
    )
    if army:
        army.counters["p1p1"] = army.counters.get("p1p1", 0) + 1
        changes.append(f"Amass: +1/+1 counter on {army.name} (now {army.counters['p1p1']})")
    else:
        token = create_token(
            controller_id=item.controller,
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
            power="0",
            toughness="0",
            counters={"p1p1": 1},
        )
        controller.cards.append(token)
        changes.append("Amass: created 0/0 Orc Army token with +1/+1 counter")

    return ActionResult(
        success=True,
        message=f"Orcish Bowmasters deals 1 to {target.name}, amass Orcs 1",
        state_changes=changes,
        tier_used=2,
    )
