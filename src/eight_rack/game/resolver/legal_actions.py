"""Legal action enumeration for the resolver."""

from __future__ import annotations

from ..actions import Action, ActionType
from ..state import CardInstance, GameState, Phase, Zone
from .helpers import (
    EVOKE_COSTS,
    FETCH_TARGETS,
    MODAL_SPELLS,
    TARGETED_REMOVAL,
    _effective_power,
    _effective_toughness,
    _is_creature,
)


class LegalActionsMixin:
    """Mixin providing legal action enumeration."""

    def get_legal_actions(self, state: GameState, player_id: str) -> list[Action]:
        """Enumerate all legal actions for a player given the current state."""
        player = state.get_player(player_id)
        actions: list[Action] = []

        # Always can pass priority
        actions.append(Action(
            type=ActionType.PASS_PRIORITY,
            player_id=player_id,
            description="Pass priority",
        ))

        is_active = state.active_player.id == player_id
        is_main = state.phase in (Phase.MAIN_1, Phase.MAIN_2)
        stack_empty = len(state.stack) == 0

        # Play lands (main phase, active player, empty stack)
        if is_active and is_main and stack_empty:
            if player.land_drops_remaining > 0:
                for card in player.hand:
                    if card.definition.is_land:
                        actions.append(Action(
                            type=ActionType.PLAY_LAND,
                            player_id=player_id,
                            card_id=card.id,
                            card_name=card.name,
                            description=f"Play {card.name}",
                        ))

        # Cast spells
        for card in player.hand:
            if card.definition.is_land:
                continue

            is_sorcery_speed = card.definition.is_sorcery or card.definition.is_creature or \
                               card.definition.is_enchantment or card.definition.is_artifact or \
                               card.definition.is_planeswalker
            is_instant_speed = card.definition.is_instant or "Flash" in card.definition.keywords

            can_cast = False
            if is_instant_speed:
                can_cast = True
            elif is_sorcery_speed and is_active and is_main and stack_empty:
                can_cast = True

            # Evoke: alternate cast for evoke creatures (checked before mana gate)
            if can_cast and card.name in EVOKE_COSTS:
                evoke_cost = EVOKE_COSTS[card.name]
                if self._can_pay_cost(state, player, evoke_cost):
                    actions.append(Action(
                        type=ActionType.CAST_SPELL,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        choices={"evoke": "true"},
                        description=f"Evoke {card.name} ({evoke_cost})",
                    ))

            if can_cast and card.definition.mana_cost:
                if not self._can_pay_cost(state, player, card.definition.mana_cost):
                    can_cast = False
            elif not can_cast:
                continue

            if not can_cast:
                continue

            # Modal spells
            if card.name in MODAL_SPELLS:
                for mode_key, mode_desc in MODAL_SPELLS[card.name]:
                    if card.name == "Funeral Charm" and mode_key in ("pump", "shrink"):
                        for p in state.players:
                            for target in p.battlefield:
                                if target.definition.is_creature:
                                    owner_label = "" if p.id == player_id else f" ({p.name}'s)"
                                    actions.append(Action(
                                        type=ActionType.CAST_SPELL,
                                        player_id=player_id,
                                        card_id=card.id,
                                        card_name=card.name,
                                        choices={"mode": mode_key},
                                        targets=[target.id],
                                        description=f"{mode_desc} — {target.name}{owner_label}",
                                    ))
                    else:
                        actions.append(Action(
                            type=ActionType.CAST_SPELL,
                            player_id=player_id,
                            card_id=card.id,
                            card_name=card.name,
                            choices={"mode": mode_key},
                            description=mode_desc,
                        ))
            # Targeted removal
            elif card.name in TARGETED_REMOVAL:
                target_actions = self._enumerate_targeted_spell(
                    state, player_id, card
                )
                actions.extend(target_actions)
            else:
                actions.append(Action(
                    type=ActionType.CAST_SPELL,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    description=f"Cast {card.name}",
                ))

        # Activate abilities on battlefield permanents
        for card in player.battlefield:
            if card.name == "Liliana of the Veil" and is_active and is_main and stack_empty and not card.counters.get("loyalty_used"):
                loyalty = card.counters.get("loyalty", 0)
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "+1"},
                    description="Liliana +1: Each player discards",
                ))
                if loyalty >= 2:
                    actions.append(Action(
                        type=ActionType.ACTIVATE_ABILITY,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        choices={"mode": "-2"},
                        description="Liliana -2: Opponent sacrifices creature",
                    ))
                if loyalty >= 6:
                    actions.append(Action(
                        type=ActionType.ACTIVATE_ABILITY,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        choices={"mode": "-6"},
                        description="Liliana -6: Opponent separates permanents",
                    ))

            # Mishra's Factory: animate (instant speed — can block with it)
            if (card.name == "Mishra's Factory" and not card.tapped
                    and not card.counters.get("animated")):
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "animate"},
                    description="Activate Mishra's Factory (become 2/2)",
                ))

            # Castle Locthwain: {1}{B}, {T}, Pay life equal to cards in hand: Draw a card
            if (card.name == "Castle Locthwain" and not card.tapped
                    and self._can_pay_cost(state, player, "{1}{B}")):
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "draw"},
                    description=f"Castle Locthwain: Pay {player.hand_size} life, draw a card",
                ))

            # Urza's Saga: {2}, {T}: Create a Construct token
            if (card.name == "Urza's Saga" and not card.tapped
                    and card.counters.get("lore", 0) >= 2
                    and self._can_pay_cost(state, player, "{2}")):
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "construct"},
                    description="Urza's Saga: Create a Construct token ({2}, {T})",
                ))

        # Attack with creatures (declare attackers step)
        if is_active and state.phase == Phase.DECLARE_ATTACKERS:
            # Ensnaring Bridge: creatures with power > controller's hand size can't attack
            bridge_hand_size = 999
            for p in state.players:
                for c in p.cards:
                    if c.name == "Ensnaring Bridge" and c.zone == Zone.BATTLEFIELD:
                        bridge_hand_size = min(bridge_hand_size, state.get_player(c.controller).hand_size)

            for card in player.battlefield:
                if not _is_creature(card) or card.tapped:
                    continue
                if card.id in state.combat.attackers:
                    continue
                has_haste = self._has_keyword(card, "Haste")
                if card.sick and not has_haste:
                    continue

                power = _effective_power(card)
                toughness = _effective_toughness(card)
                if power <= bridge_hand_size:
                    actions.append(Action(
                        type=ActionType.ATTACK,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        description=f"Attack with {card.name} ({power}/{toughness})",
                    ))

        # Treasure token sacrifice (instant speed, any time with priority)
        for card in player.battlefield:
            if card.name == "Treasure" and not card.tapped:
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "sacrifice_treasure"},
                    description="Sacrifice Treasure for mana",
                ))

        # Fetchland activations (instant speed)
        for card in player.battlefield:
            if card.name in FETCH_TARGETS and not card.tapped:
                actions.append(Action(
                    type=ActionType.ACTIVATE_ABILITY,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    choices={"mode": "fetch"},
                    description=f"Crack {card.name} (fetch a land)",
                ))

        return actions

    def _enumerate_targeted_spell(
        self, state: GameState, player_id: str, card: CardInstance
    ) -> list[Action]:
        """Create cast actions with explicit targets for targeted spells."""
        actions: list[Action] = []
        opponent = state.opponent_of(player_id)

        if card.name == "Thoughtseize":
            nonlands = [c for c in opponent.hand if not c.definition.is_land]
            if nonlands:
                for target in nonlands:
                    actions.append(Action(
                        type=ActionType.CAST_SPELL,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        targets=[target.id],
                        description=f"Thoughtseize: take {target.name}",
                    ))
            else:
                actions.append(Action(
                    type=ActionType.CAST_SPELL,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    description="Thoughtseize (opponent has no nonland cards)",
                ))

        elif card.name == "Inquisition of Kozilek":
            nonlands_3 = [
                c for c in opponent.hand
                if not c.definition.is_land and c.definition.cmc <= 3
            ]
            if nonlands_3:
                for target in nonlands_3:
                    actions.append(Action(
                        type=ActionType.CAST_SPELL,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        targets=[target.id],
                        description=f"Inquisition: take {target.name}",
                    ))
            else:
                actions.append(Action(
                    type=ActionType.CAST_SPELL,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    description="Inquisition of Kozilek (no valid target)",
                ))

        elif card.name in ("Fatal Push", "Bloodchief's Thirst", "Dismember", "Galvanic Discharge"):
            for target in opponent.battlefield:
                if target.definition.is_creature:
                    actions.append(Action(
                        type=ActionType.CAST_SPELL,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        targets=[target.id],
                        description=f"{card.name} targeting {target.name} ({target.definition.power}/{target.definition.toughness})",
                    ))
                elif target.definition.is_planeswalker and card.name == "Bloodchief's Thirst":
                    actions.append(Action(
                        type=ActionType.CAST_SPELL,
                        player_id=player_id,
                        card_id=card.id,
                        card_name=card.name,
                        targets=[target.id],
                        description=f"{card.name} targeting {target.name}",
                    ))
            if not actions:
                actions.append(Action(
                    type=ActionType.CAST_SPELL,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    description=f"Cast {card.name} (no valid targets)",
                ))

        elif card.name == "Lightning Bolt":
            actions.append(Action(
                type=ActionType.CAST_SPELL,
                player_id=player_id,
                card_id=card.id,
                card_name=card.name,
                targets=[f"player:{opponent.id}"],
                description=f"Lightning Bolt {opponent.name}'s face",
            ))
            for p in state.players:
                for target in p.battlefield:
                    if target.definition.is_creature or target.definition.is_planeswalker:
                        actions.append(Action(
                            type=ActionType.CAST_SPELL,
                            player_id=player_id,
                            card_id=card.id,
                            card_name=card.name,
                            targets=[target.id],
                            description=f"Lightning Bolt {target.name} ({target.definition.power}/{target.definition.toughness})",
                        ))

        else:
            actions.append(Action(
                type=ActionType.CAST_SPELL,
                player_id=player_id,
                card_id=card.id,
                card_name=card.name,
                description=f"Cast {card.name}",
            ))

        return actions
