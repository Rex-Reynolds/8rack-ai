"""Tests for priority fix (draw/begin combat/end combat) and saga support (Urza's Saga)."""

import pytest

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, CombatState, GameState, ManaPool, Phase, PlayerState, StackItem, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import Resolver
from eight_rack.game.engine import GameEngine


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


# Card fixtures
SWAMP = make_card("Swamp")
MOUNTAIN = make_card("Mountain")

LIGHTNING_BOLT = make_card(
    "Lightning Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
    oracle_text="Deal 3 damage to any target.", card_types=[CardType.INSTANT],
)

GRIZZLY_BEARS = make_card(
    "Grizzly Bears", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
    card_types=[CardType.CREATURE], power="2", toughness="2",
)

FLASH_CREATURE = make_card(
    "Aven Mindcensor", mana_cost="{2}{W}", cmc=3.0,
    type_line="Creature — Bird Wizard",
    card_types=[CardType.CREATURE], power="2", toughness="1",
    keywords=["Flash", "Flying"],
)

SORCERY_SPELL = make_card(
    "Lava Spike", mana_cost="{R}", cmc=1.0, type_line="Sorcery",
    oracle_text="Deal 3 damage to target player.",
    card_types=[CardType.SORCERY],
)

URZAS_SAGA = make_card(
    "Urza's Saga", type_line="Enchantment Land — Urza's Saga",
    card_types=[CardType.ENCHANTMENT, CardType.LAND],
    subtypes=["Urza's", "Saga"],
    oracle_text="(As this Saga enters and after your draw step, add a lore counter.)",
)

NIHIL_SPELLBOMB = make_card(
    "Nihil Spellbomb", mana_cost="{1}", cmc=1.0,
    type_line="Artifact",
    card_types=[CardType.ARTIFACT],
)

SHADOWSPEAR = make_card(
    "Shadowspear", mana_cost="{1}", cmc=1.0,
    type_line="Artifact — Equipment",
    card_types=[CardType.ARTIFACT],
    subtypes=["Equipment"],
)

SOL_RING = make_card(
    "Sol Ring", mana_cost="{1}", cmc=1.0,
    type_line="Artifact",
    card_types=[CardType.ARTIFACT],
)


class SimpleAgent:
    """Minimal agent that always passes priority."""

    def choose_action(self, state, legal_actions):
        return next(a for a in legal_actions if a.type == ActionType.PASS_PRIORITY)

    def choose_mulligan(self, hand, mulligans):
        return False

    def choose_discard_target(self, state, opponent_hand):
        return None

    def choose_search_target(self, state, candidates):
        return candidates[0].id if candidates else None


# =========================================================================
# PRIORITY FIX TESTS
# =========================================================================

class TestPriorityFix:
    def test_instant_castable_during_draw_step(self):
        """Player with an instant and mana should get priority during draw step."""
        bolt = make_instance(LIGHTNING_BOLT, Zone.HAND, "p2")
        mountain = make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p2_cards=[bolt, mountain])
        state.phase = Phase.DRAW
        state.active_player_index = 0  # p1 is active (their draw step)
        state.priority_player_index = 1  # p2 gets priority

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p2")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert len(cast_actions) > 0, "Should be able to cast instant during draw step"
        assert any(a.card_name == "Lightning Bolt" for a in cast_actions)

    def test_instant_castable_during_begin_combat(self):
        """Player should be able to cast instants during begin combat."""
        bolt = make_instance(LIGHTNING_BOLT, Zone.HAND, "p2")
        mountain = make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p2_cards=[bolt, mountain])
        state.phase = Phase.BEGIN_COMBAT
        state.active_player_index = 0
        state.priority_player_index = 1

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p2")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert len(cast_actions) > 0, "Should be able to cast instant during begin combat"

    def test_instant_castable_during_end_combat(self):
        """Player should be able to cast instants during end combat."""
        bolt = make_instance(LIGHTNING_BOLT, Zone.HAND, "p2")
        mountain = make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p2_cards=[bolt, mountain])
        state.phase = Phase.END_COMBAT
        state.active_player_index = 0
        state.priority_player_index = 1

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p2")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert len(cast_actions) > 0, "Should be able to cast instant during end combat"

    def test_sorcery_not_castable_during_draw(self):
        """Sorcery should NOT be castable during draw step."""
        spike = make_instance(SORCERY_SPELL, Zone.HAND, "p1")
        mountain = make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[spike, mountain])
        state.phase = Phase.DRAW
        state.active_player_index = 0

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert len(cast_actions) == 0, "Sorcery should not be castable during draw step"


class TestFlashKeyword:
    def test_flash_creature_castable_at_instant_speed(self):
        """A creature with Flash should be castable during opponent's turn."""
        flash_dude = make_instance(FLASH_CREATURE, Zone.HAND, "p2")
        plains1 = make_instance(make_card("Plains"), Zone.BATTLEFIELD, "p2")
        plains2 = make_instance(make_card("Plains"), Zone.BATTLEFIELD, "p2")
        plains3 = make_instance(make_card("Plains"), Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p2_cards=[flash_dude, plains1, plains2, plains3])
        state.phase = Phase.DRAW  # Not a main phase
        state.active_player_index = 0  # p1's turn

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p2")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert any(a.card_name == "Aven Mindcensor" for a in cast_actions), \
            "Flash creature should be castable at instant speed"

    def test_non_flash_creature_not_castable_at_instant_speed(self):
        """A creature without Flash should NOT be castable during opponent's turn."""
        bears = make_instance(GRIZZLY_BEARS, Zone.HAND, "p2")
        forest1 = make_instance(make_card("Forest"), Zone.BATTLEFIELD, "p2")
        forest2 = make_instance(make_card("Forest"), Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p2_cards=[bears, forest1, forest2])
        state.phase = Phase.DRAW
        state.active_player_index = 0  # p1's turn

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p2")

        cast_actions = [a for a in legal if a.type == ActionType.CAST_SPELL]
        assert not any(a.card_name == "Grizzly Bears" for a in cast_actions), \
            "Non-flash creature should not be castable at instant speed"


# =========================================================================
# SAGA TESTS
# =========================================================================

class TestSagaBasics:
    def test_is_saga_property(self):
        """CardDefinition.is_saga should detect Saga subtype."""
        assert URZAS_SAGA.is_saga
        assert not SWAMP.is_saga

    def test_saga_etb_gets_lore_counter(self):
        """Playing a saga land should add first lore counter."""
        saga = make_instance(URZAS_SAGA, Zone.HAND, "p1")
        state = make_two_player_state(p1_cards=[saga])
        state.phase = Phase.MAIN_1
        state.active_player_index = 0

        resolver = Resolver()
        action = Action(
            type=ActionType.PLAY_LAND, player_id="p1",
            card_id=saga.id, card_name="Urza's Saga",
        )
        result = resolver.resolve(state, action)

        assert result.success
        assert saga.zone == Zone.BATTLEFIELD
        assert saga.counters.get("lore") == 1

    def test_saga_sba_sacrifice_at_three_lore(self):
        """Saga should be sacrificed by SBA when lore counter reaches 3."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 3

        state = make_two_player_state(p1_cards=[saga])
        sba = state.check_state_based_actions()

        assert saga.zone == Zone.GRAVEYARD
        assert any("sacrificed" in s for s in sba)

    def test_saga_not_sacrificed_at_two_lore(self):
        """Saga should NOT be sacrificed when lore counter is only 2."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 2

        state = make_two_player_state(p1_cards=[saga])
        sba = state.check_state_based_actions()

        assert saga.zone == Zone.BATTLEFIELD
        assert not any("sacrificed" in s for s in sba)


class TestUrzasSagaChapters:
    def test_chapter_trigger_on_etb(self):
        """When Urza's Saga enters, chapter I trigger should be created by engine."""
        from eight_rack.cards.database import CardDatabase
        engine = GameEngine(card_db=CardDatabase.__new__(CardDatabase))

        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 1
        state = make_two_player_state(p1_cards=[saga])

        trigger = engine._make_saga_trigger(state, saga, 1)
        assert trigger is not None
        assert "chapter I" in trigger.description
        assert trigger.is_ability

    def test_chapter_2_trigger(self):
        """Chapter II trigger should mention construct-making ability."""
        from eight_rack.cards.database import CardDatabase
        engine = GameEngine(card_db=CardDatabase.__new__(CardDatabase))

        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 2
        state = make_two_player_state(p1_cards=[saga])

        trigger = engine._make_saga_trigger(state, saga, 2)
        assert trigger is not None
        assert "chapter II" in trigger.description

    def test_chapter_3_trigger_has_action_data(self):
        """Chapter III trigger should have action_data for search resolution."""
        from eight_rack.cards.database import CardDatabase
        engine = GameEngine(card_db=CardDatabase.__new__(CardDatabase))

        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 3
        state = make_two_player_state(p1_cards=[saga])

        trigger = engine._make_saga_trigger(state, saga, 3)
        assert trigger is not None
        assert "chapter III" in trigger.description
        assert trigger.action_data is not None
        assert trigger.action_data["choices"]["mode"] == "saga_chapter_3"

    def test_construct_ability_appears_in_legal_actions(self):
        """Urza's Saga with lore >= 2 and enough mana should offer construct ability."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 2
        swamp1 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        swamp2 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[saga, swamp1, swamp2])
        state.phase = Phase.MAIN_1
        state.active_player_index = 0

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")

        construct_actions = [
            a for a in legal
            if a.type == ActionType.ACTIVATE_ABILITY and "Construct" in (a.description or "")
        ]
        assert len(construct_actions) == 1

    def test_construct_ability_not_available_at_lore_1(self):
        """Urza's Saga with only 1 lore counter should NOT offer construct ability."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 1
        swamp1 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        swamp2 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[saga, swamp1, swamp2])
        state.phase = Phase.MAIN_1
        state.active_player_index = 0

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")

        construct_actions = [
            a for a in legal
            if a.type == ActionType.ACTIVATE_ABILITY and "Construct" in (a.description or "")
        ]
        assert len(construct_actions) == 0

    def test_construct_token_creation(self):
        """Activating Urza's Saga construct ability should create a token."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 2
        swamp1 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        swamp2 = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[saga, swamp1, swamp2])
        state.phase = Phase.MAIN_1
        state.active_player_index = 0
        state.players[0].mana_pool.black = 2

        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=saga.id, card_name="Urza's Saga",
            choices={"mode": "construct"},
        )
        result = resolver.resolve(state, action)

        assert result.success
        assert saga.tapped

        # Find the token
        tokens = [c for c in state.players[0].battlefield if c.name == "Construct"]
        assert len(tokens) == 1
        assert tokens[0].definition.is_creature
        assert tokens[0].definition.is_artifact

    def test_chapter_3_search_finds_artifact(self):
        """Chapter III should search for artifact with CMC <= 1 and put it on battlefield."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 3
        spellbomb = make_instance(NIHIL_SPELLBOMB, Zone.LIBRARY, "p1")
        # Also have a non-qualifying card
        bears = make_instance(GRIZZLY_BEARS, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[saga, spellbomb, bears])

        resolver = Resolver()
        item = StackItem(
            source_card_id=saga.id,
            source_card_name="Urza's Saga",
            controller="p1",
            description="Urza's Saga chapter III: search for artifact with CMC 0 or 1",
            is_ability=True,
            action_data={"type": "activate_ability", "player_id": "p1",
                         "card_id": saga.id, "card_name": "Urza's Saga",
                         "choices": {"mode": "saga_chapter_3"}},
        )

        agent = SimpleAgent()
        result = resolver._resolve_triggered_ability(state, item, agent=agent)

        assert result.success
        assert spellbomb.zone == Zone.BATTLEFIELD
        assert bears.zone == Zone.LIBRARY

    def test_chapter_3_search_no_valid_target(self):
        """Chapter III with no valid artifacts should just shuffle."""
        saga = make_instance(URZAS_SAGA, Zone.BATTLEFIELD, "p1")
        saga.counters["lore"] = 3
        bears = make_instance(GRIZZLY_BEARS, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[saga, bears])

        resolver = Resolver()
        item = StackItem(
            source_card_id=saga.id,
            source_card_name="Urza's Saga",
            controller="p1",
            description="Urza's Saga chapter III: search for artifact with CMC 0 or 1",
            is_ability=True,
            action_data={"type": "activate_ability", "player_id": "p1",
                         "card_id": saga.id, "card_name": "Urza's Saga",
                         "choices": {"mode": "saga_chapter_3"}},
        )

        result = resolver._resolve_triggered_ability(state, item)

        assert result.success
        assert "no valid artifact" in result.message
        assert bears.zone == Zone.LIBRARY
