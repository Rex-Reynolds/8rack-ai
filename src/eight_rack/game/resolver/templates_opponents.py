"""Tier 2 templates for opponent deck cards + generics."""

from __future__ import annotations

import random

from ..actions import Action, ActionResult
from ..state import CardInstance, GameState, Zone


class OpponentTemplatesMixin:
    """Templates for opponent deck cards and generic fallbacks."""

    def _register_opponent_templates(self) -> None:
        # Boros Energy / common opponent cards
        self._templates["Ragavan, Nimble Pilferer"] = self._resolve_generic_creature
        self._templates["Guide of Souls"] = self._resolve_generic_creature
        self._templates["Ocelot Pride"] = self._resolve_generic_creature
        self._templates["Ajani, Nacatl Pariah"] = self._resolve_generic_creature
        self._templates["Phlage, Titan of Fire's Fury"] = self._resolve_phlage
        self._templates["Seasoned Pyromancer"] = self._resolve_seasoned_pyromancer
        self._templates["Galvanic Discharge"] = self._resolve_galvanic_discharge
        self._templates["Goblin Bombardment"] = self._resolve_generic_permanent
        self._templates["Blood Moon"] = self._resolve_generic_permanent
        self._templates["Orcish Bowmasters"] = self._resolve_orcish_bowmasters
        # Ruby Storm
        self._templates["Ruby Medallion"] = self._resolve_generic_permanent
        self._templates["Desperate Ritual"] = self._resolve_ritual
        self._templates["Pyretic Ritual"] = self._resolve_ritual
        self._templates["Manamorphose"] = self._resolve_manamorphose
        self._templates["Grapeshot"] = self._resolve_grapeshot
        self._templates["Past in Flames"] = self._resolve_generic_permanent
        self._templates["Wish"] = self._resolve_generic_spell
        self._templates["Strike It Rich"] = self._resolve_generic_spell
        self._templates["Reckless Impulse"] = self._resolve_generic_spell
        self._templates["Wrenn's Resolve"] = self._resolve_generic_spell
        self._templates["Glimpse the Impossible"] = self._resolve_generic_spell
        # Eldrazi Tron
        self._templates["Thought-Knot Seer"] = self._resolve_thought_knot_seer
        self._templates["Walking Ballista"] = self._resolve_generic_creature
        self._templates["Chalice of the Void"] = self._resolve_generic_permanent
        self._templates["Mind Stone"] = self._resolve_generic_permanent
        self._templates["Expedition Map"] = self._resolve_generic_permanent
        self._templates["All Is Dust"] = self._resolve_all_is_dust
        self._templates["Karn, the Great Creator"] = self._resolve_karn_great_creator
        self._templates["Ulamog, the Ceaseless Hunger"] = self._resolve_generic_creature
        # Jeskai Blink / Control
        self._templates["Teferi, Time Raveler"] = self._resolve_teferi_time_raveler
        self._templates["Solitude"] = self._resolve_solitude
        self._templates["Ephemerate"] = self._resolve_generic_spell
        self._templates["Ice-Fang Coatl"] = self._resolve_ice_fang
        self._templates["Psychic Frog"] = self._resolve_generic_creature
        # Domain Zoo
        self._templates["Territorial Kavu"] = self._resolve_generic_creature
        self._templates["Scion of Draco"] = self._resolve_generic_creature
        self._templates["Leyline Binding"] = self._resolve_leyline_binding
        self._templates["Prismatic Ending"] = self._resolve_prismatic_ending
        self._templates["Stubborn Denial"] = self._resolve_generic_spell
        # Yawgmoth
        self._templates["Yawgmoth, Thran Physician"] = self._resolve_generic_creature
        self._templates["Young Wolf"] = self._resolve_generic_creature
        self._templates["Strangleroot Geist"] = self._resolve_generic_creature
        self._templates["Grist, the Hunger Tide"] = self._resolve_generic_permanent
        self._templates["Eldritch Evolution"] = self._resolve_generic_spell
        # Amulet Titan
        self._templates["Amulet of Vigor"] = self._resolve_generic_permanent
        self._templates["Primeval Titan"] = self._resolve_generic_creature
        self._templates["Arboreal Grazer"] = self._resolve_generic_creature
        self._templates["Summoner's Pact"] = self._resolve_generic_spell
        # Affinity
        self._templates["Mox Opal"] = self._resolve_generic_permanent
        self._templates["Arcbound Ravager"] = self._resolve_generic_creature
        self._templates["Emry, Lurker of the Loch"] = self._resolve_generic_creature
        self._templates["Kappa Cannoneer"] = self._resolve_generic_creature
        self._templates["Metallic Rebuke"] = self._resolve_generic_spell
        self._templates["Aether Spellbomb"] = self._resolve_generic_permanent
        self._templates["Shadowspear"] = self._resolve_generic_permanent
        # Goryo's Vengeance
        self._templates["Goryo's Vengeance"] = self._resolve_generic_spell
        self._templates["Griselbrand"] = self._resolve_generic_creature
        self._templates["Atraxa, Grand Unifier"] = self._resolve_generic_creature
        # Neobrand
        self._templates["Neoform"] = self._resolve_generic_spell
        self._templates["Allosaurus Rider"] = self._resolve_generic_creature
        # Multi-deck
        self._templates["Endurance"] = self._resolve_generic_creature
        self._templates["Thoughtseize"] = self._resolve_thoughtseize  # opponent can also cast this
        self._templates["Fable of the Mirror-Breaker"] = self._resolve_generic_permanent
        self._templates["Veil of Summer"] = self._resolve_generic_spell
        self._templates["Pithing Needle"] = self._resolve_generic_permanent
        self._templates["Engineered Explosives"] = self._resolve_generic_permanent
        # Generic fallback keys
        self._templates["_generic_creature"] = self._resolve_generic_creature
        self._templates["_generic_permanent"] = self._resolve_generic_permanent

    # --- Generic templates ---

    def _resolve_generic_creature(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True
        return ActionResult(
            success=True,
            message=f"{card.name} enters the battlefield",
            state_changes=[f"{card.name} ETB ({card.definition.power}/{card.definition.toughness})"],
            tier_used=2,
        )

    def _resolve_generic_permanent(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
        return ActionResult(
            success=True,
            message=f"{card.name} enters the battlefield",
            state_changes=[f"{card.name} ETB"],
            tier_used=2,
        )

    def _resolve_generic_spell(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        return ActionResult(
            success=True,
            message=f"{card.name} resolves",
            tier_used=2,
        )

    # --- Specific opponent card templates ---

    def _resolve_phlage(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        player = state.get_player(action.player_id)
        opponent = state.opponent_of(action.player_id)
        changes = []

        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True

        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD:
                    target.damage_marked += 3
                    changes.append(f"Phlage deals 3 to {target.name}")
                    break
            else:
                opponent.life -= 3
                changes.append(f"Phlage deals 3 to {opponent.name}")
        else:
            opponent.life -= 3
            changes.append(f"Phlage deals 3 to {opponent.name}")

        player.life += 3
        changes.append(f"{player.name} gains 3 life ({player.life})")

        return ActionResult(
            success=True,
            message="Phlage enters the battlefield",
            state_changes=changes,
            tier_used=2,
        )

    def _resolve_seasoned_pyromancer(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        player = state.get_player(action.player_id)
        changes = []

        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True

        discarded = 0
        for _ in range(2):
            d = player.discard_random()
            if d:
                changes.append(f"{player.name} discards {d.name}")
                discarded += 1
        if discarded > 0:
            drawn = player.draw(2)
            changes.append(f"{player.name} draws {len(drawn)} cards")
        else:
            changes.append(f"{player.name} creates two 1/1 Elemental tokens (simplified)")

        return ActionResult(
            success=True,
            message="Seasoned Pyromancer enters the battlefield",
            state_changes=changes,
            tier_used=2,
        )

    def _resolve_galvanic_discharge(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD:
                    target.damage_marked += 2
                    toughness = int(target.definition.toughness or "0")
                    if target.damage_marked >= toughness:
                        target.zone = Zone.GRAVEYARD
                        return ActionResult(
                            success=True,
                            message=f"Galvanic Discharge deals 2 to {target.name} (destroyed)",
                            state_changes=[f"{target.name} destroyed"],
                            tier_used=2,
                        )
                    return ActionResult(
                        success=True,
                        message=f"Galvanic Discharge deals 2 to {target.name}",
                        tier_used=2,
                    )
        return ActionResult(success=True, message="Galvanic Discharge (no target)", tier_used=2)

    def _resolve_ritual(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        player = state.get_player(action.player_id)
        player.mana_pool.red += 3
        return ActionResult(
            success=True,
            message=f"{card.name}: add RRR",
            state_changes=[f"{player.name} gains RRR"],
            tier_used=2,
        )

    def _resolve_manamorphose(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        player = state.get_player(action.player_id)
        player.mana_pool.red += 2
        player.draw(1)
        return ActionResult(
            success=True,
            message="Manamorphose: add RR, draw 1",
            state_changes=[f"{player.name} draws a card"],
            tier_used=2,
        )

    def _resolve_grapeshot(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        opponent = state.opponent_of(action.player_id)
        storm_count = state.spells_cast_this_turn
        opponent.life -= storm_count
        return ActionResult(
            success=True,
            message=f"Grapeshot: {storm_count} copies deal {storm_count} damage to {opponent.name}",
            state_changes=[f"{opponent.name} life: {opponent.life}"],
            tier_used=2,
        )

    def _resolve_thought_knot_seer(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True
        opponent = state.opponent_of(action.player_id)
        nonlands = [c for c in opponent.hand if not c.definition.is_land]
        if nonlands:
            target = random.choice(nonlands)
            target.zone = Zone.EXILE
            return ActionResult(
                success=True,
                message=f"Thought-Knot Seer exiles {target.name} from {opponent.name}'s hand",
                state_changes=[f"{target.name} exiled"],
                tier_used=2,
            )
        return ActionResult(
            success=True,
            message="Thought-Knot Seer enters (no nonland to exile)",
            tier_used=2,
        )

    def _resolve_all_is_dust(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        changes = []
        for player in state.players:
            for c in player.battlefield[:]:
                if c.definition.colors:
                    c.zone = Zone.GRAVEYARD
                    changes.append(f"{player.name} sacrifices {c.name}")
        return ActionResult(
            success=True,
            message="All Is Dust resolves",
            state_changes=changes,
            tier_used=2,
        )

    def _resolve_solitude(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True
        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD and target.definition.is_creature:
                    power = int(target.definition.power or "0")
                    p.life += power
                    target.zone = Zone.EXILE
                    return ActionResult(
                        success=True,
                        message=f"Solitude exiles {target.name}, {p.name} gains {power} life",
                        state_changes=[f"{target.name} exiled", f"{p.name} life: {p.life}"],
                        tier_used=2,
                    )
        return ActionResult(success=True, message="Solitude enters the battlefield", tier_used=2)

    def _resolve_ice_fang(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if card.zone != Zone.BATTLEFIELD:
            card.zone = Zone.BATTLEFIELD
            card.controller = action.player_id
            card.sick = True
        player = state.get_player(action.player_id)
        player.draw(1)
        return ActionResult(
            success=True,
            message=f"Ice-Fang Coatl enters, {player.name} draws a card",
            state_changes=[f"{player.name} draws a card"],
            tier_used=2,
        )

    def _resolve_leyline_binding(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        card.zone = Zone.BATTLEFIELD
        card.controller = action.player_id
        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD and not target.definition.is_land:
                    target.zone = Zone.EXILE
                    return ActionResult(
                        success=True,
                        message=f"Leyline Binding exiles {target.name}",
                        state_changes=[f"{target.name} exiled"],
                        tier_used=2,
                    )
        return ActionResult(success=True, message="Leyline Binding enters (no target)", tier_used=2)

    def _resolve_prismatic_ending(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD and not target.definition.is_land:
                    target.zone = Zone.EXILE
                    return ActionResult(
                        success=True,
                        message=f"Prismatic Ending exiles {target.name}",
                        state_changes=[f"{target.name} exiled"],
                        tier_used=2,
                    )
        return ActionResult(success=True, message="Prismatic Ending (no target)", tier_used=2)

    def _resolve_orcish_bowmasters(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        return ActionResult(
            success=True,
            message="Orcish Bowmasters enters the battlefield",
            state_changes=["Orcish Bowmasters ETB trigger goes on the stack"],
            tier_used=2,
        )

    def _resolve_teferi_time_raveler(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Teferi, Time Raveler: +1 draw/discard, -3 bounce, passive (opponent sorcery speed only)."""
        mode = action.choices.get("mode")
        if mode:
            loyalty = card.counters.get("loyalty", 4)
            card.counters["loyalty_used"] = 1

            if mode == "+1":
                card.counters["loyalty"] = loyalty + 1
                player = state.get_player(action.player_id)
                drawn = player.draw(1)
                discarded = player.discard_random()
                changes = []
                if drawn:
                    changes.append(f"{player.name} draws a card")
                if discarded:
                    changes.append(f"{player.name} discards {discarded.name}")
                return ActionResult(
                    success=True,
                    message="Teferi +1: Draw a card, then discard a card",
                    state_changes=changes,
                    tier_used=2,
                )
            elif mode == "-3":
                if loyalty < 3:
                    return ActionResult(success=False, message="Not enough loyalty")
                card.counters["loyalty"] = loyalty - 3
                opponent = state.opponent_of(action.player_id)
                # Bounce a nonland permanent
                nonlands = [c for c in opponent.battlefield if not c.definition.is_land]
                if nonlands:
                    target = random.choice(nonlands)
                    target.zone = Zone.HAND
                    return ActionResult(
                        success=True,
                        message=f"Teferi -3: Bounce {target.name}",
                        state_changes=[f"{target.name} returned to hand"],
                        tier_used=2,
                    )
                return ActionResult(
                    success=True,
                    message="Teferi -3: Nothing to bounce",
                    tier_used=2,
                )
        # ETB
        return ActionResult(
            success=True,
            message=f"Teferi, Time Raveler enters with {card.counters.get('loyalty', 4)} loyalty",
            state_changes=["Opponent can only cast spells at sorcery speed"],
            tier_used=2,
        )

    def _resolve_karn_great_creator(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Karn, the Great Creator: +1 animate artifact, -2 fetch from exile/sideboard."""
        mode = action.choices.get("mode")
        if mode:
            loyalty = card.counters.get("loyalty", 5)
            card.counters["loyalty_used"] = 1

            if mode == "+1":
                card.counters["loyalty"] = loyalty + 1
                return ActionResult(
                    success=True,
                    message="Karn +1: Animated artifacts are 0/0 creatures until your next turn",
                    tier_used=2,
                )
            elif mode == "-2":
                if loyalty < 2:
                    return ActionResult(success=False, message="Not enough loyalty")
                card.counters["loyalty"] = loyalty - 2
                player = state.get_player(action.player_id)
                # Search exile for an artifact
                exiled_artifacts = [c for c in player.cards if c.zone == Zone.EXILE and c.definition.is_artifact]
                if exiled_artifacts:
                    chosen = exiled_artifacts[0]
                    chosen.zone = Zone.HAND
                    return ActionResult(
                        success=True,
                        message=f"Karn -2: Return {chosen.name} from exile to hand",
                        state_changes=[f"{chosen.name} returned to hand"],
                        tier_used=2,
                    )
                return ActionResult(
                    success=True,
                    message="Karn -2: No artifacts in exile",
                    tier_used=2,
                )
        # ETB
        return ActionResult(
            success=True,
            message=f"Karn, the Great Creator enters with {card.counters.get('loyalty', 5)} loyalty",
            state_changes=["Activated abilities of opponent's artifacts can't be activated"],
            tier_used=2,
        )
