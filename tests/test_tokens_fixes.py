"""Tests for token creation, planeswalker ETB, bowmasters amass, SBA p1p1, and London mulligan."""

import pytest

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, GameState, ManaPool, Phase, PlayerState, StackItem, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import Resolver
from eight_rack.game.tokens import create_token
from eight_rack.game.triggers import TriggerRegistry, TriggerType


# --- Helpers ---

def make_card(name: str, **kwargs) -> CardDefinition:
    defaults = {
        "name": name,
        "mana_cost": "",
        "cmc": 0.0,
        "type_line": "Land",
        "oracle_text": "",
        "card_types": [CardType.LAND],
        "keywords": [],
    }
    defaults.update(kwargs)
    return CardDefinition(**defaults)


def make_instance(card_def: CardDefinition, zone: Zone = Zone.HAND, owner: str = "p1") -> CardInstance:
    return CardInstance(definition=card_def, zone=zone, owner=owner, controller=owner)


def make_two_player_state(**kwargs) -> GameState:
    return GameState(players=[
        PlayerState(id="p1", name="Player 1", cards=kwargs.get("p1_cards", [])),
        PlayerState(id="p2", name="Player 2", cards=kwargs.get("p2_cards", [])),
    ])


# --- Card fixtures ---

SWAMP = make_card("Swamp")

LILIANA = make_card(
    "Liliana of the Veil", mana_cost="{1}{B}{B}", cmc=3.0,
    type_line="Legendary Planeswalker — Liliana",
    card_types=[CardType.PLANESWALKER],
    loyalty="3",
)

GENERIC_PLANESWALKER = make_card(
    "Karn Liberated", mana_cost="{7}", cmc=7.0,
    type_line="Legendary Planeswalker — Karn",
    card_types=[CardType.PLANESWALKER],
    loyalty="6",
)

BOWMASTERS = make_card(
    "Orcish Bowmasters", mana_cost="{1}{B}", cmc=2.0,
    type_line="Creature — Orc Archer",
    card_types=[CardType.CREATURE],
    power="1", toughness="1",
    keywords=["Flash"],
)

URZAS_SAGA = make_card(
    "Urza's Saga", type_line="Enchantment Land — Urza's Saga",
    card_types=[CardType.ENCHANTMENT, CardType.LAND],
    subtypes=["Urza's", "Saga"],
)


# --- Tests: create_token ---

class TestCreateToken:
    def test_creates_creature_token_with_summoning_sickness(self):
        token = create_token(
            controller_id="p1",
            name="Goblin",
            type_line="Token Creature — Goblin",
            card_types=[CardType.CREATURE],
            subtypes=["Goblin"],
            power="1", toughness="1",
        )
        assert token.zone == Zone.BATTLEFIELD
        assert token.owner == "p1"
        assert token.controller == "p1"
        assert token.sick is True
        assert token.definition.name == "Goblin"
        assert token.definition.power == "1"
        assert token.definition.toughness == "1"

    def test_creates_token_with_counters(self):
        token = create_token(
            controller_id="p1",
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
            counters={"p1p1": 1},
        )
        assert token.counters["p1p1"] == 1
        assert token.definition.power == "0"
        assert token.definition.toughness == "0"

    def test_noncreature_token_no_summoning_sickness(self):
        token = create_token(
            controller_id="p1",
            name="Treasure",
            type_line="Token Artifact — Treasure",
            card_types=[CardType.ARTIFACT],
            subtypes=["Treasure"],
        )
        assert token.sick is False


# --- Tests: SBA +1/+1 counters ---

class TestSBAPlusCounters:
    def test_zero_toughness_with_p1p1_survives(self):
        """A 0/0 creature with a +1/+1 counter should survive SBA."""
        token = create_token(
            controller_id="p1",
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
            counters={"p1p1": 1},
        )
        state = make_two_player_state(p1_cards=[token])
        actions = state.check_state_based_actions()
        assert token.zone == Zone.BATTLEFIELD
        assert not any("dies" in a for a in actions)

    def test_zero_toughness_without_counter_dies(self):
        """A 0/0 creature without counters should die."""
        token = create_token(
            controller_id="p1",
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
        )
        state = make_two_player_state(p1_cards=[token])
        actions = state.check_state_based_actions()
        assert token.zone == Zone.GRAVEYARD

    def test_lethal_damage_accounts_for_p1p1(self):
        """Lethal damage check should include +1/+1 counters."""
        bear = make_card(
            "Bear", card_types=[CardType.CREATURE], power="2", toughness="2",
            type_line="Creature — Bear",
        )
        inst = make_instance(bear, zone=Zone.BATTLEFIELD)
        inst.counters["p1p1"] = 1  # now effectively 3/3
        inst.damage_marked = 2  # 2 damage on a 3-toughness creature = survives
        state = make_two_player_state(p1_cards=[inst])
        actions = state.check_state_based_actions()
        assert inst.zone == Zone.BATTLEFIELD

        inst.damage_marked = 3  # 3 damage on a 3-toughness creature = dies
        actions = state.check_state_based_actions()
        assert inst.zone == Zone.GRAVEYARD


# --- Tests: Planeswalker ETB loyalty ---

class TestPlaneswalkerETB:
    def test_generic_planeswalker_gets_loyalty(self):
        """Any planeswalker resolved from the stack gets loyalty counters from definition."""
        resolver = Resolver()
        card = make_instance(GENERIC_PLANESWALKER, zone=Zone.STACK, owner="p1")
        state = make_two_player_state(p1_cards=[card])
        state.players[0].mana_pool.colorless = 7

        action = Action(
            type=ActionType.CAST_SPELL, player_id="p1",
            card_id=card.id, card_name="Karn Liberated",
        )
        stack_item = StackItem(
            source_card_id=card.id,
            source_card_name="Karn Liberated",
            controller="p1",
            card_instance=card,
            action_data=action.model_dump(),
        )
        state.stack.append(stack_item)
        result = resolver.resolve_top_of_stack(state)

        assert card.zone == Zone.BATTLEFIELD
        assert card.counters.get("loyalty") == 6

    def test_liliana_still_gets_loyalty(self):
        """Liliana should get loyalty from generic ETB path (no longer from template)."""
        resolver = Resolver()
        card = make_instance(LILIANA, zone=Zone.STACK, owner="p1")
        state = make_two_player_state(p1_cards=[card])

        action = Action(
            type=ActionType.CAST_SPELL, player_id="p1",
            card_id=card.id, card_name="Liliana of the Veil",
        )
        stack_item = StackItem(
            source_card_id=card.id,
            source_card_name="Liliana of the Veil",
            controller="p1",
            card_instance=card,
            action_data=action.model_dump(),
        )
        state.stack.append(stack_item)
        result = resolver.resolve_top_of_stack(state)

        assert card.zone == Zone.BATTLEFIELD
        assert card.counters.get("loyalty") == 3


# --- Tests: Construct token via create_token ---

class TestConstructTokenRefactor:
    def test_construct_token_via_create_token(self):
        """Construct token creation uses create_token utility."""
        resolver = Resolver()
        saga = make_instance(URZAS_SAGA, zone=Zone.BATTLEFIELD, owner="p1")
        saga.counters["lore"] = 2
        state = make_two_player_state(p1_cards=[saga])
        state.players[0].mana_pool.colorless = 2

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=saga.id, card_name="Urza's Saga",
            description="Urza's Saga: Create Construct token",
        )
        result = resolver._resolve_urzas_saga_construct(state, action, saga)

        assert result.success
        tokens = [c for c in state.players[0].cards if c.name == "Construct"]
        assert len(tokens) == 1
        assert tokens[0].zone == Zone.BATTLEFIELD
        assert tokens[0].sick is True


# --- Tests: Bowmasters amass ---

class TestBowmastersAmass:
    def test_bowmasters_creates_army_token(self):
        """Bowmasters trigger creates a 0/0 Orc Army token with +1/+1 counter."""
        registry = TriggerRegistry()
        bowmasters = make_instance(BOWMASTERS, zone=Zone.BATTLEFIELD, owner="p1")
        state = make_two_player_state(p1_cards=[bowmasters])

        # Simulate ETB trigger
        item = StackItem(
            source_card_id=bowmasters.id,
            source_card_name="Orcish Bowmasters",
            controller="p1",
            targets=["player:p2"],
            is_ability=True,
        )

        handler = registry.get_handler("Orcish Bowmasters", item)
        assert handler is not None
        result = handler(state, item)

        assert result.success
        assert state.players[1].life == 19  # 1 damage dealt

        # Check Orc Army token
        armies = [c for c in state.players[0].cards if "Army" in c.definition.subtypes]
        assert len(armies) == 1
        assert armies[0].counters["p1p1"] == 1
        assert armies[0].zone == Zone.BATTLEFIELD

    def test_bowmasters_amass_existing_army(self):
        """If controller already has an Army, amass adds a counter instead."""
        registry = TriggerRegistry()
        bowmasters = make_instance(BOWMASTERS, zone=Zone.BATTLEFIELD, owner="p1")

        existing_army = create_token(
            controller_id="p1",
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
            counters={"p1p1": 2},
        )

        state = make_two_player_state(p1_cards=[bowmasters, existing_army])

        item = StackItem(
            source_card_id=bowmasters.id,
            source_card_name="Orcish Bowmasters",
            controller="p1",
            targets=["player:p2"],
            is_ability=True,
        )

        handler = registry.get_handler("Orcish Bowmasters", item)
        result = handler(state, item)

        assert result.success
        # Should NOT have created a new army
        armies = [c for c in state.players[0].cards if "Army" in c.definition.subtypes]
        assert len(armies) == 1
        assert armies[0].counters["p1p1"] == 3  # 2 + 1

    def test_army_with_p1p1_survives_sba(self):
        """Orc Army token with +1/+1 counter should survive SBA."""
        token = create_token(
            controller_id="p1",
            name="Orc Army",
            type_line="Token Creature — Orc Army",
            card_types=[CardType.CREATURE],
            subtypes=["Orc", "Army"],
            counters={"p1p1": 1},
        )
        state = make_two_player_state(p1_cards=[token])
        actions = state.check_state_based_actions()
        assert token.zone == Zone.BATTLEFIELD


# --- Tests: London mulligan ---

class TestLondonMulligan:
    def test_choose_cards_to_bottom_deterministic(self):
        """DeterministicPilot bottoms excess lands first, then highest CMC."""
        from eight_rack.agents.pilot import DeterministicPilot

        pilot = DeterministicPilot()
        hand = [
            make_instance(make_card("Swamp"), zone=Zone.HAND),
            make_instance(make_card("Swamp"), zone=Zone.HAND),
            make_instance(make_card("Swamp"), zone=Zone.HAND),
            make_instance(make_card("Swamp"), zone=Zone.HAND),
            make_instance(make_card(
                "The Rack", mana_cost="{1}", cmc=1.0,
                type_line="Artifact", card_types=[CardType.ARTIFACT],
            ), zone=Zone.HAND),
            make_instance(make_card(
                "Thoughtseize", mana_cost="{B}", cmc=1.0,
                type_line="Sorcery", card_types=[CardType.SORCERY],
            ), zone=Zone.HAND),
            make_instance(make_card(
                "Liliana of the Veil", mana_cost="{1}{B}{B}", cmc=3.0,
                type_line="Planeswalker", card_types=[CardType.PLANESWALKER],
                loyalty="3",
            ), zone=Zone.HAND),
        ]

        to_bottom = pilot.choose_cards_to_bottom(hand, 2)
        assert len(to_bottom) == 2
        # Should bottom the 4th Swamp (excess land) and Liliana (highest CMC non-land)
        bottomed_names = [next(c.name for c in hand if c.id == cid) for cid in to_bottom]
        assert "Swamp" in bottomed_names  # excess land

    def test_choose_cards_to_bottom_opponent(self):
        """ScriptedOpponent bottoms highest-CMC cards."""
        from eight_rack.agents.opponent import ScriptedOpponent

        opponent = ScriptedOpponent()
        hand = [
            make_instance(make_card(
                "Mountain", card_types=[CardType.LAND],
            ), zone=Zone.HAND),
            make_instance(make_card(
                "Goblin Guide", mana_cost="{R}", cmc=1.0,
                type_line="Creature", card_types=[CardType.CREATURE],
                power="2", toughness="2",
            ), zone=Zone.HAND),
            make_instance(make_card(
                "Fury", mana_cost="{3}{R}{R}", cmc=5.0,
                type_line="Creature", card_types=[CardType.CREATURE],
                power="3", toughness="3",
            ), zone=Zone.HAND),
        ]

        to_bottom = opponent.choose_cards_to_bottom(hand, 1)
        assert len(to_bottom) == 1
        # Should bottom Fury (highest CMC)
        bottomed = next(c for c in hand if c.id == to_bottom[0])
        assert bottomed.name == "Fury"

    def test_goldfish_cards_to_bottom(self):
        """GoldfishOpponent bottoms last N cards."""
        from eight_rack.agents.pilot import GoldfishOpponent

        goldfish = GoldfishOpponent()
        hand = [
            make_instance(make_card("A"), zone=Zone.HAND),
            make_instance(make_card("B"), zone=Zone.HAND),
            make_instance(make_card("C"), zone=Zone.HAND),
        ]

        to_bottom = goldfish.choose_cards_to_bottom(hand, 1)
        assert len(to_bottom) == 1
        assert to_bottom[0] == hand[-1].id
