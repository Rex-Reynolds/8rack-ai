"""Tier 2 templates for 8 Rack deck cards."""

from __future__ import annotations

import random

from ..actions import Action, ActionResult
from ..state import CardInstance, GameState, Zone


class EightRackTemplatesMixin:
    """Templates for 8 Rack primary cards."""

    def _register_eight_rack_templates(self) -> None:
        self._templates["The Rack"] = self._resolve_the_rack_trigger
        self._templates["Shrieking Affliction"] = self._resolve_shrieking_affliction_trigger
        self._templates["Thoughtseize"] = self._resolve_thoughtseize
        self._templates["Inquisition of Kozilek"] = self._resolve_inquisition
        self._templates["Raven's Crime"] = self._resolve_ravens_crime
        self._templates["Wrench Mind"] = self._resolve_wrench_mind
        self._templates["Funeral Charm"] = self._resolve_funeral_charm
        self._templates["Smallpox"] = self._resolve_smallpox
        self._templates["Liliana of the Veil"] = self._resolve_liliana
        self._templates["Nihil Spellbomb"] = self._resolve_nihil_spellbomb
        self._templates["Ensnaring Bridge"] = self._resolve_ensnaring_bridge
        self._templates["Castle Locthwain"] = self._resolve_castle_locthwain
        self._templates["Leyline of the Void"] = self._resolve_leyline_of_the_void
        self._templates["Bontu's Last Reckoning"] = self._resolve_bontus_last_reckoning

    def _resolve_the_rack_trigger(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        return ActionResult(
            success=True,
            message="The Rack enters the battlefield",
            state_changes=["The Rack will deal damage during opponent's upkeep"],
            tier_used=2,
        )

    def _resolve_shrieking_affliction_trigger(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        return ActionResult(
            success=True,
            message="Shrieking Affliction enters the battlefield",
            state_changes=["Shrieking Affliction will deal damage during opponent's upkeep"],
            tier_used=2,
        )

    def _resolve_thoughtseize(self, state: GameState, action: Action, card: CardInstance, **kwargs) -> ActionResult:
        """Thoughtseize: Look at target opponent's hand, choose a nonland card, they discard it. You lose 2 life."""
        player = state.get_player(action.player_id)
        opponent = state.opponent_of(action.player_id)
        player.life -= 2

        nonlands = [c for c in opponent.hand if not c.definition.is_land]
        if not nonlands:
            return ActionResult(
                success=True,
                message=f"Thoughtseize: {opponent.name}'s hand is empty. {player.name} loses 2 life.",
                state_changes=[f"{player.name} life: {player.life}"],
                tier_used=2,
            )

        target_id = action.targets[0] if action.targets else None

        if not target_id:
            agent = kwargs.get("agent")
            if agent and hasattr(agent, "choose_discard_target"):
                target_id = agent.choose_discard_target(state, nonlands)
            if not target_id:
                nonlands.sort(key=lambda c: c.definition.cmc, reverse=True)
                target_id = nonlands[0].id

        discarded = opponent.discard(target_id)
        if discarded:
            return ActionResult(
                success=True,
                message=f"Thoughtseize: {opponent.name} discards {discarded.name}. {player.name} loses 2 life.",
                state_changes=[f"{discarded.name} discarded", f"{player.name} life: {player.life}"],
                tier_used=2,
            )
        return ActionResult(
            success=True,
            message=f"Thoughtseize: no valid target. {player.name} loses 2 life.",
            state_changes=[f"{player.name} life: {player.life}"],
            tier_used=2,
        )

    def _resolve_inquisition(self, state: GameState, action: Action, card: CardInstance, **kwargs) -> ActionResult:
        """Inquisition of Kozilek: Target opponent reveals hand, you choose a nonland with CMC <= 3."""
        opponent = state.opponent_of(action.player_id)

        valid_targets = [
            c for c in opponent.hand
            if not c.definition.is_land and c.definition.cmc <= 3
        ]
        if not valid_targets:
            return ActionResult(
                success=True,
                message=f"Inquisition of Kozilek: no valid target in {opponent.name}'s hand",
                tier_used=2,
            )

        target_id = action.targets[0] if action.targets else None

        if not target_id:
            agent = kwargs.get("agent")
            if agent and hasattr(agent, "choose_discard_target"):
                target_id = agent.choose_discard_target(state, valid_targets)
            if not target_id:
                valid_targets.sort(key=lambda c: c.definition.cmc, reverse=True)
                target_id = valid_targets[0].id

        discarded = opponent.discard(target_id)
        if discarded:
            return ActionResult(
                success=True,
                message=f"Inquisition of Kozilek: {opponent.name} discards {discarded.name}",
                state_changes=[f"{discarded.name} discarded"],
                tier_used=2,
            )
        return ActionResult(
            success=True,
            message="Inquisition of Kozilek: failed to discard",
            tier_used=2,
        )

    def _resolve_ravens_crime(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        opponent = state.opponent_of(action.player_id)
        if action.targets:
            discarded = opponent.discard(action.targets[0])
            if discarded:
                return ActionResult(
                    success=True,
                    message=f"Raven's Crime: {opponent.name} discards {discarded.name}",
                    state_changes=[f"{discarded.name} discarded"],
                    tier_used=2,
                )
        discarded = opponent.discard_random()
        if discarded:
            return ActionResult(
                success=True,
                message=f"Raven's Crime: {opponent.name} discards {discarded.name}",
                state_changes=[f"{discarded.name} discarded"],
                tier_used=2,
            )
        return ActionResult(
            success=True,
            message=f"Raven's Crime: {opponent.name} has no cards to discard",
            tier_used=2,
        )

    def _resolve_wrench_mind(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        opponent = state.opponent_of(action.player_id)
        discarded_names = []
        for _ in range(2):
            d = opponent.discard_random()
            if d:
                discarded_names.append(d.name)
        return ActionResult(
            success=True,
            message=f"Wrench Mind: {opponent.name} discards {', '.join(discarded_names) or 'nothing'}",
            state_changes=[f"{n} discarded" for n in discarded_names],
            tier_used=2,
        )

    def _resolve_funeral_charm(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Funeral Charm: Choose one - target player discards, creature gets +2/-1, creature gets -1/-1."""
        mode = action.choices.get("mode", "discard")
        if mode == "discard":
            opponent = state.opponent_of(action.player_id)
            discarded = opponent.discard_random()
            if discarded:
                return ActionResult(
                    success=True,
                    message=f"Funeral Charm: {opponent.name} discards {discarded.name}",
                    state_changes=[f"{discarded.name} discarded"],
                    tier_used=2,
                )
            return ActionResult(success=True, message="Funeral Charm: no card to discard", tier_used=2)
        elif mode == "pump":
            if action.targets:
                for p in state.players:
                    target = p.find_card(action.targets[0])
                    if target and target.zone == Zone.BATTLEFIELD:
                        target.counters["pump_power_temp"] = target.counters.get("pump_power_temp", 0) + 2
                        target.counters["pump_toughness_temp"] = target.counters.get("pump_toughness_temp", 0) - 1
                        return ActionResult(
                            success=True,
                            message=f"Funeral Charm: {target.name} gets +2/-1 until end of turn",
                            state_changes=[f"{target.name} gets +2/-1"],
                            tier_used=2,
                        )
            return ActionResult(success=True, message="Funeral Charm: no valid target", tier_used=2)
        elif mode == "shrink":
            if action.targets:
                for p in state.players:
                    target = p.find_card(action.targets[0])
                    if target and target.zone == Zone.BATTLEFIELD:
                        target.counters["m1m1_temp"] = target.counters.get("m1m1_temp", 0) + 1
                        return ActionResult(
                            success=True,
                            message=f"Funeral Charm: {target.name} gets -1/-1 until end of turn",
                            state_changes=[f"{target.name} gets -1/-1"],
                            tier_used=2,
                        )
            return ActionResult(success=True, message="Funeral Charm: no valid target", tier_used=2)
        return ActionResult(success=False, message="Invalid mode for Funeral Charm", tier_used=2)

    def _resolve_smallpox(self, state: GameState, action: Action, card: CardInstance, agents: dict | None = None) -> ActionResult:
        changes = []
        for player in state.players:
            player.life -= 1
            changes.append(f"{player.name} loses 1 life ({player.life})")

            agent = agents.get(player.id) if agents else None
            hand = player.hand
            if hand:
                if agent and hasattr(agent, "choose_discard_from_hand"):
                    card_id = agent.choose_discard_from_hand(state, hand)
                    d = player.discard(card_id) if card_id else player.discard_random()
                else:
                    d = player.discard_random()
                if d:
                    changes.append(f"{player.name} discards {d.name}")

            creatures = [c for c in player.battlefield if c.definition.is_creature]
            if creatures:
                if agent and hasattr(agent, "choose_sacrifice"):
                    sac_id = agent.choose_sacrifice(state, creatures)
                    sac = next((c for c in creatures if c.id == sac_id), random.choice(creatures))
                else:
                    sac = random.choice(creatures)
                sac.zone = Zone.GRAVEYARD
                changes.append(f"{player.name} sacrifices {sac.name}")

            lands = [c for c in player.battlefield if c.definition.is_land]
            if lands:
                if agent and hasattr(agent, "choose_sacrifice"):
                    sac_id = agent.choose_sacrifice(state, lands)
                    sac = next((c for c in lands if c.id == sac_id), random.choice(lands))
                else:
                    sac = random.choice(lands)
                sac.zone = Zone.GRAVEYARD
                changes.append(f"{player.name} sacrifices {sac.name}")

        return ActionResult(
            success=True,
            message="Smallpox resolves",
            state_changes=changes,
            tier_used=2,
        )

    def _resolve_liliana(self, state: GameState, action: Action, card: CardInstance, agents: dict | None = None) -> ActionResult:
        mode = action.choices.get("mode")
        if mode:
            loyalty = card.counters.get("loyalty", 3)
            card.counters["loyalty_used"] = 1

            if mode == "+1":
                card.counters["loyalty"] = loyalty + 1
                changes = []
                for p in state.players:
                    hand = p.hand
                    if not hand:
                        continue
                    agent = agents.get(p.id) if agents else None
                    card_id = None
                    if agent and hasattr(agent, "choose_discard_from_hand"):
                        card_id = agent.choose_discard_from_hand(state, hand)
                    if card_id:
                        d = p.discard(card_id)
                    else:
                        d = p.discard_random()
                    if d:
                        changes.append(f"{p.name} discards {d.name}")
                return ActionResult(
                    success=True,
                    message="Liliana of the Veil +1: Each player discards a card",
                    state_changes=changes,
                    tier_used=2,
                )
            elif mode == "-2":
                if loyalty < 2:
                    return ActionResult(success=False, message="Not enough loyalty")
                card.counters["loyalty"] = loyalty - 2
                opponent = state.opponent_of(action.player_id)
                creatures = [c for c in opponent.battlefield if c.definition.is_creature]
                if creatures:
                    sac = random.choice(creatures)
                    sac.zone = Zone.GRAVEYARD
                    return ActionResult(
                        success=True,
                        message=f"Liliana -2: {opponent.name} sacrifices {sac.name}",
                        state_changes=[f"{sac.name} sacrificed"],
                        tier_used=2,
                    )
                return ActionResult(
                    success=True,
                    message="Liliana -2: No creatures to sacrifice",
                    tier_used=2,
                )
            elif mode == "-6":
                if loyalty < 6:
                    return ActionResult(success=False, message="Not enough loyalty")
                card.counters["loyalty"] = loyalty - 6
                changes = []
                for p in state.players:
                    perms = p.battlefield[:]
                    if not perms:
                        continue
                    sac_count = (len(perms) + 1) // 2
                    for perm in perms[:sac_count]:
                        perm.zone = Zone.GRAVEYARD
                        changes.append(f"{p.name} sacrifices {perm.name}")
                return ActionResult(
                    success=True,
                    message="Liliana -6: each player sacrifices permanents",
                    state_changes=changes,
                    tier_used=2,
                )
        else:
            return ActionResult(
                success=True,
                message=f"Liliana of the Veil enters the battlefield with {card.counters.get('loyalty', 3)} loyalty",
                tier_used=2,
            )

    def _resolve_nihil_spellbomb(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone == Zone.BATTLEFIELD:
            opponent = state.opponent_of(action.player_id)
            exiled = []
            for c in opponent.graveyard[:]:
                c.zone = Zone.EXILE
                exiled.append(c.name)
            card.zone = Zone.GRAVEYARD
            player = state.get_player(action.player_id)
            player.draw(1)
            return ActionResult(
                success=True,
                message=f"Nihil Spellbomb exiles {len(exiled)} cards from {opponent.name}'s graveyard",
                state_changes=[f"Exiled {len(exiled)} cards", f"{player.name} draws a card"],
                tier_used=2,
            )
        return ActionResult(success=True, message="Nihil Spellbomb enters the battlefield", tier_used=2)

    def _resolve_ensnaring_bridge(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        return ActionResult(
            success=True,
            message="Ensnaring Bridge enters the battlefield",
            state_changes=["Creatures with power > your hand size can't attack"],
            tier_used=2,
        )

    def _resolve_castle_locthwain(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Castle Locthwain activated ability: {1}{B}, {T}, Pay life = hand size → draw a card."""
        mode = action.choices.get("mode")
        if mode == "draw":
            player = state.get_player(action.player_id)
            life_cost = player.hand_size
            # Tap Castle and pay {1}{B} (auto-tap handles mana)
            if not self.auto_tap_lands(state, player.id, "{1}{B}"):
                return ActionResult(success=False, message="Cannot pay {1}{B}")
            player.mana_pool.pay("{1}{B}")
            card.tapped = True
            player.life -= life_cost
            drawn = player.draw(1)
            drawn_name = drawn[0].name if drawn else "nothing"
            return ActionResult(
                success=True,
                message=f"Castle Locthwain: {player.name} pays {life_cost} life, draws {drawn_name}",
                state_changes=[f"{player.name} loses {life_cost} life ({player.life})", f"{player.name} draws a card"],
                tier_used=2,
            )
        # ETB (just enters as a land)
        return ActionResult(
            success=True,
            message="Castle Locthwain enters the battlefield",
            tier_used=2,
        )

    def _resolve_leyline_of_the_void(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Leyline of the Void enters the battlefield."""
        return ActionResult(
            success=True,
            message="Leyline of the Void enters the battlefield",
            state_changes=["Opponent's cards that would go to graveyard are exiled instead"],
            tier_used=2,
        )

    def _resolve_bontus_last_reckoning(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Bontu's Last Reckoning: Destroy all creatures. Lands don't untap next turn."""
        changes = []
        for player in state.players:
            for c in player.battlefield[:]:
                if c.definition.is_creature:
                    is_indestructible = "Indestructible" in c.definition.keywords
                    if not is_indestructible:
                        c.zone = Zone.GRAVEYARD
                        changes.append(f"{c.name} destroyed")
                    else:
                        changes.append(f"{c.name} survives (indestructible)")
        # Mark caster's lands to not untap next turn
        caster = state.get_player(action.player_id)
        for c in caster.battlefield:
            if c.definition.is_land:
                c.counters["skip_untap"] = 1
        changes.append(f"{caster.name}'s lands don't untap during next untap step")
        return ActionResult(
            success=True,
            message="Bontu's Last Reckoning resolves",
            state_changes=changes,
            tier_used=2,
        )
