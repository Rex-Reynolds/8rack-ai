"""Stack management: put_spell_on_stack, resolve_top_of_stack, triggered abilities."""

from __future__ import annotations

import logging

from ...cards.models import CardType
from ..actions import Action, ActionResult, ActionType
from ..state import CardInstance, GameState, StackItem, Zone
from ..tokens import create_token

logger = logging.getLogger(__name__)


class StackMixin:
    """Mixin providing spell stack management."""

    def put_spell_on_stack(self, state: GameState, action: Action) -> ActionResult:
        """Pay mana, move card to stack, create StackItem for deferred resolution."""
        player = state.get_player(action.player_id)
        card = player.find_card(action.card_id)
        if not card:
            return ActionResult(success=False, message="Card not found")

        # Pay mana cost (evoke uses alternate cost)
        is_evoked = action.choices.get("evoke") == "true"
        if is_evoked:
            from .helpers import EVOKE_COSTS
            evoke_cost = EVOKE_COSTS.get(card.name, card.definition.mana_cost)
            if not self.auto_tap_lands(state, player.id, evoke_cost):
                return ActionResult(success=False, message=f"Cannot pay evoke cost {evoke_cost}")
            player.mana_pool.pay(evoke_cost)
        elif card.definition.mana_cost:
            if not self.auto_tap_lands(state, player.id, card.definition.mana_cost):
                return ActionResult(success=False, message=f"Cannot pay {card.definition.mana_cost}")
            player.mana_pool.pay(card.definition.mana_cost)

        # Move card to stack zone
        card.zone = Zone.STACK
        state.spells_cast_this_turn += 1

        # Prowess: when a noncreature spell is cast, prowess creatures get +1/+1
        if not card.definition.is_creature:
            player = state.get_player(action.player_id)
            for creature in player.battlefield:
                if creature.definition.is_creature and (
                    "Prowess" in creature.definition.keywords
                    or "prowess" in creature.definition.oracle_text.lower()
                ):
                    creature.counters["pump_power_temp"] = creature.counters.get("pump_power_temp", 0) + 1
                    creature.counters["pump_toughness_temp"] = creature.counters.get("pump_toughness_temp", 0) + 1

        # Create stack item with the action data for deferred resolution
        item = StackItem(
            source_card_id=card.id,
            source_card_name=card.name,
            controller=action.player_id,
            description=f"{card.name} (spell)",
            targets=action.targets,
            is_ability=False,
            card_instance=card,
            action_data=action.model_dump(),
        )
        state.stack.append(item)

        return ActionResult(
            success=True,
            message=f"{card.name} is put on the stack",
            state_changes=[f"{card.name} goes on the stack"],
            tier_used=1,
        )

    def resolve_top_of_stack(self, state: GameState, agent=None, agents: dict | None = None) -> ActionResult:
        """Pop and resolve the top item on the stack."""
        if not state.stack:
            return ActionResult(success=False, message="Stack is empty")

        item = state.stack.pop()

        # Resolve triggered abilities
        if item.is_ability:
            return self._resolve_triggered_ability(state, item, agent=agent)

        # Resolve spell — reconstruct the action from stored data
        action = Action(**item.action_data)
        card = item.card_instance

        if not card:
            player = state.get_player(item.controller)
            card = player.find_card(item.source_card_id) if item.source_card_id else None

        if not card:
            return ActionResult(success=False, message=f"Card for {item.source_card_name} not found")

        # Fizzle check: validate targets still exist
        if item.targets and self._targets_invalid(state, item.targets):
            card.zone = Zone.GRAVEYARD
            return ActionResult(
                success=True,
                message=f"{card.name} fizzles (all targets invalid)",
                state_changes=[f"{card.name} goes to graveyard (fizzled)"],
                tier_used=1,
            )

        # Resolve based on card type
        if card.definition.is_instant or card.definition.is_sorcery:
            template = self._templates.get(card.name)
            if template:
                if card.name in ("Thoughtseize", "Inquisition of Kozilek"):
                    result = template(state, action, card, agent=agent)
                elif card.name in ("Smallpox",):
                    result = template(state, action, card, agents=agents)
                else:
                    result = template(state, action, card)
            else:
                result = ActionResult(
                    success=True,
                    message=f"{card.name} resolves (no template)",
                    tier_used=3,
                )
            card.zone = Zone.GRAVEYARD
            return result
        else:
            # Permanent — goes to battlefield
            card.zone = Zone.BATTLEFIELD
            card.controller = item.controller
            if card.definition.is_creature:
                card.sick = True

            if card.definition.is_saga:
                card.counters["lore"] = 1

            if card.definition.is_planeswalker and card.definition.loyalty:
                card.counters["loyalty"] = int(card.definition.loyalty)

            template = self._templates.get(card.name)
            if template:
                if card.name == "Liliana of the Veil":
                    result = template(state, action, card, agents=agents)
                else:
                    result = template(state, action, card)
            else:
                etb_changes = [f"{card.name} ETB"]
                if card.definition.is_saga:
                    etb_changes.append(f"{card.name} gets lore counter 1")
                result = ActionResult(
                    success=True,
                    message=f"{card.name} enters the battlefield",
                    state_changes=etb_changes,
                    tier_used=2,
                )

            if hasattr(self, '_trigger_registry') and self._trigger_registry:
                from ..triggers import TriggerType
                etb_items = self._trigger_registry.check_triggers(
                    state, TriggerType.ETB, source_card=card
                )
                for ti in etb_items:
                    state.stack.append(ti)

            # Evoke: sacrifice after ETB (add sacrifice trigger to stack)
            if action.choices.get("evoke") == "true" and card.zone == Zone.BATTLEFIELD:
                evoke_sac = StackItem(
                    source_card_id=card.id,
                    source_card_name=card.name,
                    controller=item.controller,
                    description=f"Evoke sacrifice: {card.name}",
                    is_ability=True,
                    action_data={"evoke_sacrifice": True, "card_id": card.id},
                )
                state.stack.append(evoke_sac)

            return result

    def _targets_invalid(self, state: GameState, targets: list[str]) -> bool:
        """Check if ALL targets of a spell are invalid (spell fizzles if so).

        A target is invalid if:
        - It's a card ID and the card is not on the battlefield (or expected zone)
        - Player targets (player:xxx) are always valid
        """
        if not targets:
            return False
        for target in targets:
            if target.startswith("player:"):
                return False  # Player targets are always valid
            # Check if the card is still on the battlefield
            for p in state.players:
                card = p.find_card(target)
                if card and card.zone == Zone.BATTLEFIELD:
                    return False  # At least one target is valid
                # For hand-targeted spells (Thoughtseize), check hand
                if card and card.zone == Zone.HAND:
                    return False
        return True  # All targets invalid → fizzle

    def _resolve_triggered_ability(self, state: GameState, item: StackItem, agent=None) -> ActionResult:
        """Resolve a triggered ability from the stack."""
        # Evoke sacrifice trigger
        if item.action_data and item.action_data.get("evoke_sacrifice"):
            card_id = item.action_data.get("card_id")
            for p in state.players:
                card = p.find_card(card_id)
                if card and card.zone == Zone.BATTLEFIELD:
                    card.zone = Zone.GRAVEYARD
                    return ActionResult(
                        success=True,
                        message=f"Evoke: {card.name} is sacrificed",
                        state_changes=[f"{card.name} sacrificed (evoke)"],
                        tier_used=1,
                    )
            return ActionResult(
                success=True,
                message=f"Evoke sacrifice: card already gone",
                tier_used=1,
            )

        # Urza's Saga chapter III: search for artifact
        if item.source_card_name == "Urza's Saga" and item.action_data and \
                item.action_data.get("choices", {}).get("mode") == "saga_chapter_3":
            return self._resolve_urzas_saga_search(state, item, agent=agent)

        # Urza's Saga chapter I & II: no-op
        if item.source_card_name == "Urza's Saga" and "chapter I" in item.description:
            return ActionResult(
                success=True,
                message="Urza's Saga chapter I: gains {T}: Add {C}",
                tier_used=2,
            )
        if item.source_card_name == "Urza's Saga" and "chapter II" in item.description:
            return ActionResult(
                success=True,
                message="Urza's Saga chapter II: gains construct-making ability",
                tier_used=2,
            )

        if hasattr(self, '_trigger_registry') and self._trigger_registry:
            handler = self._trigger_registry.get_handler(item.source_card_name, item)
            if handler:
                return handler(state, item)

        return ActionResult(
            success=True,
            message=f"Triggered ability resolves: {item.description}",
            tier_used=2,
        )

    def _resolve_activate_ability(self, state: GameState, action: Action, agents: dict | None = None) -> ActionResult:
        player = state.get_player(action.player_id)
        card = player.find_card(action.card_id)
        if not card:
            return ActionResult(success=False, message="Card not found")

        # Fetchland activation
        if action.choices.get("mode") == "fetch" and card.name in self._fetch_targets():
            return self._resolve_fetchland(state, action, card)

        # Urza's Saga: create Construct token
        if card.name == "Urza's Saga" and action.choices.get("mode") == "construct":
            return self._resolve_urzas_saga_construct(state, action, card)

        # Mishra's Factory animate
        if card.name == "Mishra's Factory" and action.choices.get("mode") == "animate":
            card.counters["animated"] = 1
            return ActionResult(
                success=True,
                message="Mishra's Factory becomes a 2/2 creature until end of turn",
                tier_used=2,
            )

        # Treasure token sacrifice for mana
        if card.name == "Treasure" and action.choices.get("mode") == "sacrifice_treasure":
            player = state.get_player(action.player_id)
            card.zone = Zone.GRAVEYARD
            # Add one mana of any color (default to black for 8 Rack)
            player.mana_pool.black += 1
            return ActionResult(
                success=True,
                message="Sacrifice Treasure for {B}",
                state_changes=["Treasure sacrificed", f"{player.name} adds {{B}}"],
                tier_used=1,
            )

        # Castle Locthwain draw ability
        if card.name == "Castle Locthwain" and action.choices.get("mode") == "draw":
            template = self._templates.get("Castle Locthwain")
            if template:
                return template(state, action, card)

        template = self._templates.get(action.card_name)
        if template:
            if action.card_name == "Liliana of the Veil":
                return template(state, action, card, agents=agents)
            return template(state, action, card)
        return ActionResult(success=False, message="No template for ability", tier_used=3)

    def _fetch_targets(self):
        """Get FETCH_TARGETS constant (avoids circular import in mixin)."""
        from .helpers import FETCH_TARGETS
        return FETCH_TARGETS

    def _resolve_fetchland(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Sacrifice fetchland, pay 1 life, search library for matching land."""
        from .helpers import BASIC_TYPE_LANDS, FETCH_TARGETS

        player = state.get_player(action.player_id)
        fetch_name = card.name
        valid_types = FETCH_TARGETS.get(fetch_name, [])

        if not valid_types:
            return ActionResult(success=False, message=f"{fetch_name} is not a fetchland")

        card.zone = Zone.GRAVEYARD
        player.life -= 1

        valid_land_names: set[str] = set()
        for basic_type in valid_types:
            valid_land_names.update(BASIC_TYPE_LANDS.get(basic_type, []))

        target_land = None
        for lib_card in player.library:
            if lib_card.name in valid_land_names:
                target_land = lib_card
                break
            for basic_type in valid_types:
                if basic_type in lib_card.definition.type_line:
                    target_land = lib_card
                    break
            if target_land:
                break

        if target_land:
            target_land.zone = Zone.BATTLEFIELD
            target_land.controller = player.id
            return ActionResult(
                success=True,
                message=f"{fetch_name} finds {target_land.name}",
                state_changes=[
                    f"{fetch_name} sacrificed",
                    f"{player.name} pays 1 life ({player.life})",
                    f"{target_land.name} enters the battlefield untapped",
                ],
                tier_used=2,
            )
        else:
            return ActionResult(
                success=True,
                message=f"{fetch_name} finds nothing (no valid target in library)",
                state_changes=[
                    f"{fetch_name} sacrificed",
                    f"{player.name} pays 1 life ({player.life})",
                ],
                tier_used=2,
            )

    # --- Urza's Saga ---

    def _resolve_urzas_saga_construct(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        """Urza's Saga chapter II ability: {2}, {T}: Create a Construct token."""
        player = state.get_player(action.player_id)

        card.tapped = True
        player.mana_pool.pay("{2}")

        artifact_count = sum(1 for c in player.battlefield if c.definition.is_artifact)
        artifact_count += 1

        token = create_token(
            controller_id=player.id,
            name="Construct",
            type_line="Token Artifact Creature — Construct",
            card_types=[CardType.ARTIFACT, CardType.CREATURE],
            subtypes=["Construct"],
            power=str(artifact_count),
            toughness=str(artifact_count),
            oracle_text="This creature gets +1/+1 for each artifact you control.",
        )
        player.cards.append(token)

        return ActionResult(
            success=True,
            message=f"Urza's Saga creates a {artifact_count}/{artifact_count} Construct token",
            state_changes=[f"Construct token ({artifact_count}/{artifact_count}) enters the battlefield"],
            tier_used=2,
        )

    def _resolve_urzas_saga_search(self, state: GameState, item: StackItem, agent=None) -> ActionResult:
        """Urza's Saga chapter III: search library for artifact with CMC 0 or 1."""
        import random

        player = state.get_player(item.controller)

        candidates = [
            c for c in player.library
            if c.definition.is_artifact and c.definition.cmc <= 1
        ]

        if not candidates:
            random.shuffle(player.library)
            return ActionResult(
                success=True,
                message="Urza's Saga chapter III: no valid artifact found, shuffle",
                state_changes=["Library shuffled"],
                tier_used=2,
            )

        chosen_id = None
        if agent and hasattr(agent, 'choose_search_target'):
            chosen_id = agent.choose_search_target(state, candidates)

        chosen = None
        if chosen_id:
            chosen = next((c for c in candidates if c.id == chosen_id), None)
        if not chosen:
            chosen = candidates[0]

        chosen.zone = Zone.BATTLEFIELD
        chosen.controller = player.id

        lib = player.library
        random.shuffle(lib)

        return ActionResult(
            success=True,
            message=f"Urza's Saga chapter III: {chosen.name} enters the battlefield",
            state_changes=[f"{chosen.name} put onto battlefield", "Library shuffled"],
            tier_used=2,
        )
