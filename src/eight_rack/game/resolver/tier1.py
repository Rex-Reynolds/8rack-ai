"""Tier 1 (deterministic) resolution: phases, combat, mana production."""

from __future__ import annotations

import logging

from ..actions import Action, ActionResult, ActionType
from ..state import CardInstance, GameState, Phase, PlayerState, Zone
from .helpers import (
    BASIC_TYPE_LANDS,
    DUAL_LAND_COLORS,
    FETCH_TARGETS,
    _effective_power,
    _effective_toughness,
    _is_creature,
)

logger = logging.getLogger(__name__)


class Tier1Mixin:
    """Mixin providing Tier 1 (deterministic) resolution methods."""

    # --- Phase resolution ---

    def resolve_untap_step(self, state: GameState) -> list[str]:
        """Untap all permanents of the active player."""
        changes = []
        for card in state.active_player.battlefield:
            # Skip untap for lands marked by Bontu's Last Reckoning etc.
            if card.counters.get("skip_untap"):
                card.counters.pop("skip_untap")
                changes.append(f"{card.name} doesn't untap (skip_untap)")
                continue
            if card.tapped:
                card.tapped = False
                changes.append(f"Untapped {card.name}")
            if card.sick and card.definition.is_creature:
                card.sick = False
                changes.append(f"{card.name} no longer has summoning sickness")
        state.active_player.land_drops_remaining = state.active_player.land_drops_per_turn
        return changes

    def resolve_draw_step(self, state: GameState) -> list[str]:
        """Active player draws a card (skipped on T1 for first player)."""
        if state.turn_number == 1 and state.active_player_index == 0:
            return ["First player skips draw on turn 1"]
        drawn = state.active_player.draw(1)
        if drawn:
            return [f"{state.active_player.name} draws a card"]
        return [f"{state.active_player.name} cannot draw - library empty"]

    def resolve_upkeep_triggers(self, state: GameState) -> list[str]:
        """Resolve beginning-of-upkeep triggers (Rack effects, etc.)."""
        changes = []
        for player in state.players:
            for card in player.battlefield:
                if card.name == "The Rack":
                    opponent = state.opponent_of(card.controller)
                    hand_size = opponent.hand_size
                    if hand_size < 3:
                        damage = 3 - hand_size
                        opponent.life -= damage
                        changes.append(
                            f"The Rack deals {damage} damage to {opponent.name} "
                            f"(hand size: {hand_size})"
                        )
                elif card.name == "Shrieking Affliction":
                    opponent = state.opponent_of(card.controller)
                    if opponent.hand_size <= 1:
                        opponent.life -= 3
                        changes.append(
                            f"Shrieking Affliction deals 3 damage to {opponent.name} "
                            f"(hand size: {opponent.hand_size})"
                        )
        return changes

    def resolve_cleanup_step(self, state: GameState) -> list[str]:
        """Discard to hand size and clear damage."""
        changes = []
        player = state.active_player
        max_hand_size = 7
        while player.hand_size > max_hand_size:
            card = player.discard_random()
            if card:
                changes.append(f"{player.name} discards {card.name} to hand size")
        # Clear damage from creatures and reset temporary effects
        for p in state.players:
            for card in p.battlefield:
                card.damage_marked = 0
                card.counters.pop("animated", None)
                card.counters.pop("loyalty_used", None)
                # Clear all end-of-turn temp counters
                card.counters.pop("m1m1_temp", None)
                card.counters.pop("pump_power_temp", None)
                card.counters.pop("pump_toughness_temp", None)
        # Empty mana pools
        for p in state.players:
            p.mana_pool.empty()
        return changes

    # --- Core actions ---

    def _resolve_play_land(self, state: GameState, action: Action) -> ActionResult:
        player = state.get_player(action.player_id)
        card = player.find_card(action.card_id)
        if not card:
            return ActionResult(success=False, message="Card not found")
        if not card.definition.is_land:
            return ActionResult(success=False, message=f"{card.name} is not a land")
        if player.land_drops_remaining <= 0:
            return ActionResult(success=False, message="No land drops remaining")
        if card.zone != Zone.HAND:
            return ActionResult(success=False, message="Card not in hand")

        card.zone = Zone.BATTLEFIELD
        card.controller = player.id
        player.land_drops_remaining -= 1

        state_changes = [f"{card.name} enters the battlefield"]

        # Saga ETB: add first lore counter
        if card.definition.is_saga:
            card.counters["lore"] = 1
            state_changes.append(f"{card.name} gets lore counter 1")

        return ActionResult(
            success=True,
            message=f"{player.name} plays {card.name}",
            state_changes=state_changes,
            tier_used=1,
        )

    def _resolve_discard(self, state: GameState, action: Action) -> ActionResult:
        player = state.get_player(action.player_id)
        card = player.discard(action.card_id)
        if not card:
            return ActionResult(success=False, message="Cannot discard - card not in hand")
        return ActionResult(
            success=True,
            message=f"{player.name} discards {card.name}",
            state_changes=[f"{card.name} goes to graveyard"],
            tier_used=1,
        )

    def _resolve_attack(self, state: GameState, action: Action) -> ActionResult:
        """Declare a creature as an attacker."""
        player = state.get_player(action.player_id)
        card = player.find_card(action.card_id)
        if not card:
            return ActionResult(success=False, message="Attacker not found")

        has_haste = self._has_keyword(card, "Haste")
        has_vigilance = self._has_keyword(card, "Vigilance")

        if card.tapped:
            return ActionResult(success=False, message=f"{card.name} is tapped")
        if card.sick and not has_haste:
            return ActionResult(success=False, message=f"{card.name} has summoning sickness")

        if not has_vigilance:
            card.tapped = True

        state.combat.attackers.append(card.id)

        power = _effective_power(card)
        toughness = _effective_toughness(card)
        return ActionResult(
            success=True,
            message=f"{card.name} attacks ({power}/{toughness})",
            state_changes=[f"{card.name} declared as attacker"],
            tier_used=1,
        )

    def _resolve_block(self, state: GameState, action: Action) -> ActionResult:
        """Declare a creature as a blocker for a specific attacker."""
        player = state.get_player(action.player_id)
        card = player.find_card(action.card_id)
        if not card:
            return ActionResult(success=False, message="Blocker not found")
        if card.tapped:
            return ActionResult(success=False, message=f"{card.name} is tapped")

        attacker_id = action.targets[0] if action.targets else None
        if not attacker_id or attacker_id not in state.combat.attackers:
            return ActionResult(success=False, message="Invalid attacker target")

        opponent = state.opponent_of(action.player_id)
        attacker = opponent.find_card(attacker_id)
        if not attacker:
            return ActionResult(success=False, message="Attacker not found")

        if self._has_keyword(attacker, "Flying") and not self._has_keyword(card, "Flying") and not self._has_keyword(card, "Reach"):
            return ActionResult(success=False, message=f"{card.name} can't block {attacker.name} (flying)")

        if self._has_keyword(attacker, "Menace"):
            existing_blockers = [bid for bid, aid in state.combat.blockers.items() if aid == attacker_id]
            if len(existing_blockers) == 0:
                pass  # Allow it, but combat damage will check

        state.combat.blockers[card.id] = attacker_id

        return ActionResult(
            success=True,
            message=f"{card.name} blocks {attacker.name}",
            state_changes=[f"{card.name} declared as blocker"],
            tier_used=1,
        )

    def _has_keyword(self, card: CardInstance, keyword: str) -> bool:
        """Check if a card has a keyword ability."""
        if keyword in card.definition.keywords:
            return True
        oracle = card.definition.oracle_text.lower()
        return keyword.lower() in oracle

    # --- Combat resolution ---

    def resolve_combat_damage(self, state: GameState) -> list[str]:
        """Resolve combat damage: first strike, then regular, with keyword handling."""
        changes = []
        if not state.combat.attackers:
            return changes

        active_player = state.active_player
        defending_player = state.non_active_player

        first_strikers = []
        regular_attackers = []
        for atk_id in state.combat.attackers:
            card = active_player.find_card(atk_id)
            if not card:
                continue
            has_fs = self._has_keyword(card, "First Strike") or self._has_keyword(card, "Double Strike")
            if has_fs:
                first_strikers.append(card)
            else:
                regular_attackers.append(card)

        if first_strikers:
            fs_changes = self._deal_combat_damage(
                state, first_strikers, active_player, defending_player, is_first_strike=True
            )
            changes.extend(fs_changes)
            sba = state.check_state_based_actions()
            changes.extend(sba)

        all_regular = list(regular_attackers)
        for card in first_strikers:
            if self._has_keyword(card, "Double Strike") and card.zone == Zone.BATTLEFIELD:
                all_regular.append(card)

        if all_regular:
            reg_changes = self._deal_combat_damage(
                state, all_regular, active_player, defending_player, is_first_strike=False
            )
            changes.extend(reg_changes)

        for blocker_id, attacker_id in state.combat.blockers.items():
            blocker = defending_player.find_card(blocker_id)
            attacker = active_player.find_card(attacker_id)
            if blocker and attacker and blocker.zone == Zone.BATTLEFIELD and attacker.zone == Zone.BATTLEFIELD:
                blocker_power = _effective_power(blocker)
                if blocker_power > 0:
                    attacker.damage_marked += blocker_power
                    if self._has_keyword(blocker, "Deathtouch"):
                        attacker.counters["deathtouch_damage"] = 1
                    if self._has_keyword(blocker, "Lifelink"):
                        defending_player.life += blocker_power
                        changes.append(f"{defending_player.name} gains {blocker_power} life (lifelink from {blocker.name})")
                    changes.append(f"{blocker.name} deals {blocker_power} damage to {attacker.name}")

        return changes

    def _deal_combat_damage(
        self,
        state: GameState,
        attackers: list[CardInstance],
        attacking_player: PlayerState,
        defending_player: PlayerState,
        is_first_strike: bool,
    ) -> list[str]:
        """Deal damage from a set of attackers to blockers/player."""
        changes = []

        for attacker in attackers:
            if attacker.zone != Zone.BATTLEFIELD:
                continue

            power = _effective_power(attacker)
            if power <= 0:
                continue

            has_deathtouch = self._has_keyword(attacker, "Deathtouch")
            has_trample = self._has_keyword(attacker, "Trample")
            has_lifelink = self._has_keyword(attacker, "Lifelink")

            blocker_ids = [bid for bid, aid in state.combat.blockers.items() if aid == attacker.id]
            blockers = [defending_player.find_card(bid) for bid in blocker_ids]
            blockers = [b for b in blockers if b and b.zone == Zone.BATTLEFIELD]

            if not blockers:
                defending_player.life -= power
                changes.append(f"{attacker.name} deals {power} damage to {defending_player.name}")
                if has_lifelink:
                    attacking_player.life += power
                    changes.append(f"{attacking_player.name} gains {power} life (lifelink)")
            else:
                remaining_damage = power
                for blocker in blockers:
                    blocker_toughness = _effective_toughness(blocker)
                    lethal = 1 if has_deathtouch else max(0, blocker_toughness - blocker.damage_marked)

                    damage_to_blocker = min(remaining_damage, lethal)
                    blocker.damage_marked += damage_to_blocker
                    if has_deathtouch and damage_to_blocker > 0:
                        blocker.counters["deathtouch_damage"] = 1
                    remaining_damage -= damage_to_blocker
                    changes.append(f"{attacker.name} deals {damage_to_blocker} damage to {blocker.name}")

                if has_trample and remaining_damage > 0:
                    defending_player.life -= remaining_damage
                    changes.append(f"{attacker.name} tramples {remaining_damage} damage to {defending_player.name}")

                if has_lifelink:
                    total_dealt = power - remaining_damage + (remaining_damage if has_trample else 0)
                    if total_dealt > 0:
                        attacking_player.life += total_dealt
                        changes.append(f"{attacking_player.name} gains {total_dealt} life (lifelink)")

        return changes

    def get_legal_blocks(self, state: GameState, player_id: str) -> list[Action]:
        """Enumerate legal blocker assignments for the defending player."""
        player = state.get_player(player_id)
        actions: list[Action] = []

        if not state.combat.attackers:
            return actions

        opponent = state.opponent_of(player_id)

        for card in player.battlefield:
            if not _is_creature(card) or card.tapped:
                continue
            if card.id in state.combat.blockers:
                continue

            for attacker_id in state.combat.attackers:
                attacker = opponent.find_card(attacker_id)
                if not attacker:
                    continue

                if self._has_keyword(attacker, "Flying"):
                    if not self._has_keyword(card, "Flying") and not self._has_keyword(card, "Reach"):
                        continue

                actions.append(Action(
                    type=ActionType.BLOCK,
                    player_id=player_id,
                    card_id=card.id,
                    card_name=card.name,
                    targets=[attacker_id],
                    description=f"Block {attacker.name} with {card.name}",
                ))

        return actions

    # --- Mana production ---

    def tap_land_for_mana(self, state: GameState, player_id: str, card_id: str) -> ActionResult:
        """Tap a land to produce mana."""
        player = state.get_player(player_id)
        card = player.find_card(card_id)
        if not card or card.tapped or card.zone != Zone.BATTLEFIELD:
            return ActionResult(success=False, message="Cannot tap for mana")

        card.tapped = True
        mana = self._get_land_mana(card, state)
        for color, amount in mana.items():
            current = getattr(player.mana_pool, color, 0)
            setattr(player.mana_pool, color, current + amount)

        return ActionResult(
            success=True,
            message=f"Tap {card.name} for mana",
            tier_used=1,
        )

    def _get_land_mana(self, card: CardInstance, state: GameState) -> dict[str, int]:
        """Determine what mana a land produces.

        Blood Moon: nonbasic lands become Mountains (only red).
        Urborg: all lands also produce black (in addition to their normal mana).
        """
        name = card.name
        is_basic = name in ("Swamp", "Plains", "Mountain", "Island", "Forest")

        # Blood Moon: nonbasic lands become Mountains (only tap for red)
        blood_moon_in_play = any(
            c.name == "Blood Moon" and c.zone == Zone.BATTLEFIELD
            for p in state.players
            for c in p.cards
        )
        if blood_moon_in_play and card.definition.is_land and not is_basic:
            return {"red": 1}

        urborg_in_play = any(
            c.name == "Urborg, Tomb of Yawgmoth"
            for p in state.players
            for c in p.battlefield
        )

        # Get base mana production
        mana: dict[str, int] = {}

        if name == "Swamp":
            mana = {"black": 1}
        elif name == "Urborg, Tomb of Yawgmoth":
            mana = {"black": 1}
        elif name == "Castle Locthwain":
            mana = {"black": 1}
        elif name == "Mishra's Factory":
            mana = {"colorless": 1}
        elif name == "Urza's Saga":
            mana = {"colorless": 1}
        elif name == "Plains":
            mana = {"white": 1}
        elif name == "Mountain":
            mana = {"red": 1}
        elif name == "Island":
            mana = {"blue": 1}
        elif name == "Forest":
            mana = {"green": 1}
        elif name in DUAL_LAND_COLORS:
            color1, _ = DUAL_LAND_COLORS[name]
            mana = {color1: 1}
        elif name in FETCH_TARGETS:
            mana = {}
        else:
            oracle = card.definition.oracle_text.lower()
            if "{w}" in oracle:
                mana = {"white": 1}
            elif "{r}" in oracle:
                mana = {"red": 1}
            elif "{b}" in oracle:
                mana = {"black": 1}
            elif "{u}" in oracle:
                mana = {"blue": 1}
            elif "{g}" in oracle:
                mana = {"green": 1}
            elif card.definition.is_land:
                mana = {"colorless": 1}

        return mana

    def auto_tap_lands(self, state: GameState, player_id: str, cost: str) -> bool:
        """Auto-tap lands to pay a mana cost. Returns True if successful."""
        from ..state import parse_mana_cost

        player = state.get_player(player_id)
        required = parse_mana_cost(cost)

        urborg_in_play = any(
            c.name == "Urborg, Tomb of Yawgmoth"
            for p in state.players
            for c in p.battlefield
        )

        untapped_lands = [
            c for c in player.battlefield
            if c.definition.is_land and not c.tapped
        ]

        basics = []
        duals = []
        for land in untapped_lands:
            if land.name in DUAL_LAND_COLORS:
                duals.append(land)
            else:
                basics.append(land)

        tapped_ids: set[str] = set()

        for color_symbol, attr in [("B", "black"), ("W", "white"), ("U", "blue"), ("R", "red"), ("G", "green")]:
            needed = required.get(color_symbol, 0)
            if needed <= 0:
                continue
            for land in basics:
                if needed <= 0:
                    break
                if land.id in tapped_ids:
                    continue
                mana = self._get_land_mana(land, state)
                # Urborg: all lands can produce black
                can_produce = mana.get(attr, 0) > 0
                if not can_produce and attr == "black" and urborg_in_play:
                    can_produce = True
                if can_produce:
                    tapped_ids.add(land.id)
                    needed -= 1

            if needed > 0:
                for land in duals:
                    if needed <= 0:
                        break
                    if land.id in tapped_ids:
                        continue
                    color1, color2 = DUAL_LAND_COLORS[land.name]
                    can_produce = (color1 == attr or color2 == attr)
                    if not can_produce and attr == "black" and urborg_in_play:
                        can_produce = True
                    if can_produce:
                        tapped_ids.add(land.id)
                        needed -= 1

            if needed > 0:
                return False

        generic = required.get("generic", 0)
        for land in basics + duals:
            if generic <= 0:
                break
            if land.id in tapped_ids:
                continue
            mana = self._get_land_mana(land, state)
            if sum(mana.values()) > 0:
                tapped_ids.add(land.id)
                generic -= 1

        if generic > 0:
            return False

        for land in untapped_lands:
            if land.id in tapped_ids:
                self.tap_land_for_mana(state, player_id, land.id)

        return True

    def _can_pay_cost(self, state: GameState, player: PlayerState, cost: str) -> bool:
        """Check if a player can pay a mana cost with available lands."""
        from ..state import parse_mana_cost
        required = parse_mana_cost(cost)

        urborg_in_play = any(
            c.name == "Urborg, Tomb of Yawgmoth"
            for p in state.players
            for c in p.battlefield
        )

        available_mana = {"black": 0, "white": 0, "blue": 0, "red": 0, "green": 0, "colorless": 0}
        dual_lands: list[tuple[str, str]] = []
        total_land_count = 0

        for card in player.battlefield:
            if card.definition.is_land and not card.tapped:
                if card.name in DUAL_LAND_COLORS:
                    dual_lands.append(DUAL_LAND_COLORS[card.name])
                    total_land_count += 1
                else:
                    mana = self._get_land_mana(card, state)
                    # Urborg: non-black-producing lands become duals (normal + black)
                    if urborg_in_play and mana.get("black", 0) == 0 and sum(mana.values()) > 0:
                        primary = next(iter(mana.keys()))
                        dual_lands.append((primary, "black"))
                        total_land_count += 1
                    else:
                        for k, v in mana.items():
                            available_mana[k] = available_mana.get(k, 0) + v
                        if sum(mana.values()) > 0:
                            total_land_count += 1

        color_map = {"B": "black", "W": "white", "U": "blue", "R": "red", "G": "green"}
        remaining_duals = list(dual_lands)
        for symbol, attr in color_map.items():
            needed = required.get(symbol, 0)
            if needed <= 0:
                continue
            from_basics = min(available_mana.get(attr, 0), needed)
            available_mana[attr] -= from_basics
            needed -= from_basics

            for i, (c1, c2) in enumerate(remaining_duals):
                if needed <= 0:
                    break
                if c1 == attr or c2 == attr:
                    needed -= 1
                    remaining_duals[i] = (None, None)

            if needed > 0:
                return False

        generic = required.get("generic", 0)
        remaining_basics = sum(available_mana.values())
        remaining_dual_count = sum(1 for c1, c2 in remaining_duals if c1 is not None)
        return remaining_basics + remaining_dual_count >= generic
