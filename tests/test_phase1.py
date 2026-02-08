"""Phase 1 tests: deterministic game engine, resolver, and goldfish."""

import pytest
from pathlib import Path

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, GameState, ManaPool, Phase, PlayerState, Zone, parse_mana_cost,
)
from eight_rack.game.actions import Action, ActionType
from eight_rack.game.resolver import Resolver
from eight_rack.agents.pilot import DeterministicPilot, GoldfishOpponent


# --- Fixtures ---

class _MockCard:
    """Minimal card-like object for mulligan tests (just needs .name)."""
    def __init__(self, name: str):
        self.name = name

def _mock_hand(names: list[str]) -> list:
    return [_MockCard(n) for n in names]

def make_card(name: str, **kwargs) -> CardDefinition:
    """Helper to create card definitions for testing."""
    defaults = {
        "name": name,
        "mana_cost": "",
        "cmc": 0.0,
        "type_line": "Land",
        "oracle_text": "",
        "card_types": [CardType.LAND],
    }
    defaults.update(kwargs)
    return CardDefinition(**defaults)


SWAMP = make_card("Swamp")
THE_RACK = make_card(
    "The Rack",
    mana_cost="{1}",
    cmc=1.0,
    type_line="Artifact",
    oracle_text="As The Rack enters, choose an opponent. At the beginning of the chosen player's upkeep, The Rack deals X damage to that player, where X is 3 minus the number of cards in their hand.",
    card_types=[CardType.ARTIFACT],
)
SHRIEKING = make_card(
    "Shrieking Affliction",
    mana_cost="{B}",
    cmc=1.0,
    type_line="Enchantment",
    oracle_text="At the beginning of each opponent's upkeep, if that opponent has one or fewer cards in hand, Shrieking Affliction deals 3 life loss to that player.",
    card_types=[CardType.ENCHANTMENT],
)
THOUGHTSEIZE = make_card(
    "Thoughtseize",
    mana_cost="{B}",
    cmc=1.0,
    type_line="Sorcery",
    oracle_text="Target opponent reveals their hand. You choose a nonland card from it. That player discards that card. You lose 2 life.",
    card_types=[CardType.SORCERY],
)
GRIZZLY_BEARS = make_card(
    "Grizzly Bears",
    mana_cost="{1}{G}",
    cmc=2.0,
    type_line="Creature — Bear",
    oracle_text="",
    card_types=[CardType.CREATURE],
    power="2",
    toughness="2",
)


def make_instance(card_def: CardDefinition, zone: Zone = Zone.HAND, owner: str = "p1") -> CardInstance:
    return CardInstance(definition=card_def, zone=zone, owner=owner, controller=owner)


def make_basic_state() -> GameState:
    """Create a minimal game state for testing."""
    p1 = PlayerState(
        id="p1",
        name="Player 1",
        cards=[
            make_instance(SWAMP, Zone.HAND, "p1"),
            make_instance(SWAMP, Zone.HAND, "p1"),
            make_instance(THE_RACK, Zone.HAND, "p1"),
        ],
    )
    p2 = PlayerState(
        id="p2",
        name="Player 2",
        cards=[
            make_instance(SWAMP, Zone.HAND, "p2"),
        ],
    )
    return GameState(players=[p1, p2])


# --- Tests ---

class TestManaCost:
    def test_parse_simple(self):
        result = parse_mana_cost("{1}{B}{B}")
        assert result == {"generic": 1, "B": 2}

    def test_parse_empty(self):
        result = parse_mana_cost("")
        assert result == {"generic": 0}

    def test_parse_generic_only(self):
        result = parse_mana_cost("{3}")
        assert result == {"generic": 3}

    def test_mana_pool_can_pay(self):
        pool = ManaPool(black=3)
        assert pool.can_pay("{1}{B}{B}")
        assert not pool.can_pay("{2}{B}{B}")

    def test_mana_pool_pay(self):
        pool = ManaPool(black=3)
        pool.pay("{1}{B}")
        assert pool.black == 1


class TestGameState:
    def test_player_zones(self):
        state = make_basic_state()
        assert len(state.players[0].hand) == 3
        assert state.players[0].hand_size == 3

    def test_draw(self):
        p = PlayerState(
            id="p1", name="P1",
            cards=[
                make_instance(SWAMP, Zone.LIBRARY, "p1"),
                make_instance(THE_RACK, Zone.LIBRARY, "p1"),
            ],
        )
        drawn = p.draw(1)
        assert len(drawn) == 1
        assert drawn[0].zone == Zone.HAND
        assert len(p.library) == 1

    def test_discard(self):
        card = make_instance(SWAMP, Zone.HAND, "p1")
        p = PlayerState(id="p1", name="P1", cards=[card])
        result = p.discard(card.id)
        assert result is not None
        assert result.zone == Zone.GRAVEYARD
        assert p.hand_size == 0

    def test_state_based_life(self):
        state = make_basic_state()
        state.players[1].life = 0
        sba = state.check_state_based_actions()
        assert state.game_over
        assert state.winner == "p1"

    def test_opponent_of(self):
        state = make_basic_state()
        opp = state.opponent_of("p1")
        assert opp.id == "p2"


class TestResolver:
    def test_play_land(self):
        state = make_basic_state()
        resolver = Resolver()
        card = state.players[0].hand[0]
        action = Action(
            type=ActionType.PLAY_LAND,
            player_id="p1",
            card_id=card.id,
            card_name="Swamp",
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert card.zone == Zone.BATTLEFIELD
        assert state.players[0].land_drops_remaining == 0

    def test_untap_step(self):
        state = make_basic_state()
        resolver = Resolver()
        card = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        card.tapped = True
        state.players[0].cards.append(card)
        changes = resolver.resolve_untap_step(state)
        assert not card.tapped

    def test_rack_trigger_empty_hand(self):
        state = make_basic_state()
        resolver = Resolver()
        # Put rack on p1's battlefield, p2 has empty hand
        rack = make_instance(THE_RACK, Zone.BATTLEFIELD, "p1")
        state.players[0].cards.append(rack)
        state.players[1].cards[0].zone = Zone.GRAVEYARD  # empty p2's hand

        changes = resolver.resolve_upkeep_triggers(state)
        assert any("The Rack deals 3" in c for c in changes)
        assert state.players[1].life == 17

    def test_shrieking_trigger(self):
        state = make_basic_state()
        resolver = Resolver()
        sa = make_instance(SHRIEKING, Zone.BATTLEFIELD, "p1")
        state.players[0].cards.append(sa)
        state.players[1].cards[0].zone = Zone.GRAVEYARD  # empty hand

        changes = resolver.resolve_upkeep_triggers(state)
        assert any("Shrieking Affliction deals 3" in c for c in changes)
        assert state.players[1].life == 17

    def test_rack_no_damage_with_3_cards(self):
        state = make_basic_state()
        resolver = Resolver()
        rack = make_instance(THE_RACK, Zone.BATTLEFIELD, "p1")
        state.players[0].cards.append(rack)
        # Give p2 three cards in hand
        for _ in range(2):
            state.players[1].cards.append(make_instance(SWAMP, Zone.HAND, "p2"))

        initial_life = state.players[1].life
        resolver.resolve_upkeep_triggers(state)
        assert state.players[1].life == initial_life  # No damage at 3 cards

    def test_thoughtseize_resolution(self):
        state = make_basic_state()
        resolver = Resolver()
        # Add swamp to p1 battlefield for mana
        swamp_bf = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        state.players[0].cards.append(swamp_bf)
        # Add a card to p2's hand to target
        target_card = make_instance(GRIZZLY_BEARS, Zone.HAND, "p2")
        state.players[1].cards.append(target_card)

        # Cast thoughtseize targeting the bear
        ts = state.players[0].hand[2]  # THE_RACK is in hand[2]
        # Actually let's add a thoughtseize to hand
        ts_card = make_instance(THOUGHTSEIZE, Zone.HAND, "p1")
        state.players[0].cards.append(ts_card)

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=ts_card.id,
            card_name="Thoughtseize",
            targets=[target_card.id],
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert ts_card.zone == Zone.STACK  # Spell on stack
        # Resolve the stack
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert target_card.zone == Zone.GRAVEYARD
        assert state.players[0].life == 18  # Lost 2 life

    def test_legal_actions_land(self):
        state = make_basic_state()
        state.phase = Phase.MAIN_1
        resolver = Resolver()

        legal = resolver.get_legal_actions(state, "p1")
        land_plays = [a for a in legal if a.type == ActionType.PLAY_LAND]
        assert len(land_plays) == 2  # Two swamps in hand

    def test_auto_tap_lands(self):
        state = make_basic_state()
        resolver = Resolver()
        # Put two swamps on battlefield
        for _ in range(2):
            s = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
            state.players[0].cards.append(s)

        success = resolver.auto_tap_lands(state, "p1", "{1}{B}")
        assert success
        tapped = [c for c in state.players[0].battlefield if c.tapped]
        assert len(tapped) == 2


class TestAgents:
    def test_pilot_mulligan_keeps_good_hand(self):
        pilot = DeterministicPilot()
        hand = _mock_hand(["Swamp", "Swamp", "Thoughtseize", "The Rack", "Raven's Crime", "Swamp", "Liliana of the Veil"])
        assert not pilot.choose_mulligan(hand, 0)

    def test_pilot_mulligan_rejects_no_lands(self):
        pilot = DeterministicPilot()
        hand = _mock_hand(["Thoughtseize", "The Rack", "Raven's Crime", "Fatal Push", "Smallpox", "Wrench Mind", "Liliana of the Veil"])
        assert pilot.choose_mulligan(hand, 0)

    def test_pilot_plays_land_first(self):
        pilot = DeterministicPilot()
        state = make_basic_state()
        state.phase = Phase.MAIN_1
        actions = [
            Action(type=ActionType.PLAY_LAND, player_id="p1", card_name="Swamp"),
            Action(type=ActionType.CAST_SPELL, player_id="p1", card_name="The Rack"),
            Action(type=ActionType.PASS_PRIORITY, player_id="p1"),
        ]
        choice = pilot.choose_action(state, actions)
        assert choice.type == ActionType.PLAY_LAND

    def test_goldfish_always_keeps(self):
        goldfish = GoldfishOpponent()
        assert not goldfish.choose_mulligan(_mock_hand(["Swamp"] * 7), 0)
