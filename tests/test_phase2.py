"""Phase 2 tests: LLM integration, adjudicator, hybrid pilot, opponent templates."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, GameState, ManaPool, Phase, PlayerState, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import Resolver
from eight_rack.llm.cache import ResponseCache


# --- Helpers ---

def make_card(name: str, **kwargs) -> CardDefinition:
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


def make_instance(card_def: CardDefinition, zone: Zone = Zone.HAND, owner: str = "p1") -> CardInstance:
    return CardInstance(definition=card_def, zone=zone, owner=owner, controller=owner)


SWAMP = make_card("Swamp")
PLAINS = make_card("Plains")
MOUNTAIN = make_card("Mountain")
SACRED_FOUNDRY = make_card("Sacred Foundry", oracle_text="{T}: Add {R} or {W}.")

RAGAVAN = make_card(
    "Ragavan, Nimble Pilferer",
    mana_cost="{R}",
    cmc=1.0,
    type_line="Legendary Creature — Monkey Pirate",
    card_types=[CardType.CREATURE],
    power="2",
    toughness="1",
)

PHLAGE = make_card(
    "Phlage, Titan of Fire's Fury",
    mana_cost="{1}{R}{W}",
    cmc=3.0,
    type_line="Creature — Elder Giant",
    oracle_text="When Phlage enters, it deals 3 damage to any target and you gain 3 life.",
    card_types=[CardType.CREATURE],
    power="4",
    toughness="4",
)

GALVANIC_DISCHARGE = make_card(
    "Galvanic Discharge",
    mana_cost="{R}",
    cmc=1.0,
    type_line="Sorcery",
    oracle_text="Galvanic Discharge deals X damage to target creature or planeswalker, where X is 2 plus the number of energy counters you pay.",
    card_types=[CardType.SORCERY],
)

LIGHTNING_BOLT = make_card(
    "Lightning Bolt",
    mana_cost="{R}",
    cmc=1.0,
    type_line="Instant",
    oracle_text="Lightning Bolt deals 3 damage to any target.",
    card_types=[CardType.INSTANT],
)


# --- Tests ---

class TestResponseCache:
    def test_put_and_get(self, tmp_path):
        cache = ResponseCache(tmp_path / "test_cache.db")
        cache.put("key1", '{"data": "test"}')
        result = cache.get("key1")
        assert result == '{"data": "test"}'
        assert cache.hits == 1
        cache.close()

    def test_miss(self, tmp_path):
        cache = ResponseCache(tmp_path / "test_cache.db")
        result = cache.get("nonexistent")
        assert result is None
        assert cache.misses == 1
        cache.close()

    def test_ttl_expiry(self, tmp_path):
        cache = ResponseCache(tmp_path / "test_cache.db", ttl_seconds=0)
        cache.put("key1", '{"data": "test"}')
        import time
        time.sleep(0.01)
        result = cache.get("key1")
        assert result is None
        cache.close()

    def test_hit_rate(self, tmp_path):
        cache = ResponseCache(tmp_path / "test_cache.db")
        cache.put("key1", "val")
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        assert cache.hit_rate == 0.5
        cache.close()


class TestOpponentCardTemplates:
    def test_generic_creature_etb(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[make_instance(SWAMP, Zone.BATTLEFIELD, "p1")]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(RAGAVAN, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        ragavan = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=ragavan.id,
            card_name="Ragavan, Nimble Pilferer",
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert ragavan.zone == Zone.STACK
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert ragavan.zone == Zone.BATTLEFIELD
        assert ragavan.sick  # summoning sickness

    def test_phlage_etb_damage(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(PHLAGE, Zone.HAND, "p2"),
                make_instance(PLAINS, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        phlage = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=phlage.id,
            card_name="Phlage, Titan of Fire's Fury",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert state.players[0].life == 17  # took 3 damage
        assert state.players[1].life == 23  # gained 3 life

    def test_galvanic_discharge(self):
        bowmasters = make_card(
            "Orcish Bowmasters",
            mana_cost="{1}{B}",
            cmc=2.0,
            type_line="Creature — Orc Archer",
            card_types=[CardType.CREATURE],
            power="1",
            toughness="1",
        )
        bm_inst = make_instance(bowmasters, Zone.BATTLEFIELD, "p1")

        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[bm_inst]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(GALVANIC_DISCHARGE, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        gd = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=gd.id,
            card_name="Galvanic Discharge",
            targets=[bm_inst.id],
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        # 2 damage to 1/1 should kill it
        assert bm_inst.zone == Zone.GRAVEYARD

    def test_lightning_bolt_face(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(LIGHTNING_BOLT, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        bolt = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=bolt.id,
            card_name="Lightning Bolt",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert state.players[0].life == 17


class TestLandMana:
    def test_plains_produces_white(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[make_instance(PLAINS, Zone.BATTLEFIELD, "p1")]),
            PlayerState(id="p2", name="P2", cards=[]),
        ])
        resolver = Resolver()
        mana = resolver._get_land_mana(state.players[0].battlefield[0], state)
        assert mana == {"white": 1}

    def test_sacred_foundry_produces_white(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")]),
            PlayerState(id="p2", name="P2", cards=[]),
        ])
        resolver = Resolver()
        mana = resolver._get_land_mana(state.players[0].battlefield[0], state)
        assert mana == {"white": 1}


class TestHybridPilot:
    def test_heuristic_for_simple_decisions(self):
        """Verify the hybrid pilot uses heuristics for simple decisions."""
        from eight_rack.agents.pilot import HybridPilot
        mock_llm = MagicMock()
        pilot = HybridPilot(mock_llm)

        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[make_instance(SWAMP, Zone.HAND, "p1")]),
            PlayerState(id="p2", name="P2", cards=[]),
        ])
        state.phase = Phase.MAIN_1

        actions = [
            Action(type=ActionType.PLAY_LAND, player_id="p1", card_name="Swamp"),
            Action(type=ActionType.PASS_PRIORITY, player_id="p1"),
        ]
        result = pilot.choose_action(state, actions)
        assert result.type == ActionType.PLAY_LAND
        assert pilot.heuristic_calls == 1
        assert pilot.llm_calls == 0
        mock_llm.query.assert_not_called()


class TestScriptedOpponent:
    def test_plays_land_and_attacks(self):
        from eight_rack.agents.opponent import ScriptedOpponent
        opp = ScriptedOpponent("boros_energy")

        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(MOUNTAIN, Zone.HAND, "p2"),
                make_instance(RAGAVAN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        state.active_player_index = 1
        state.phase = Phase.MAIN_1

        actions = [
            Action(type=ActionType.PLAY_LAND, player_id="p2", card_name="Mountain"),
            Action(type=ActionType.CAST_SPELL, player_id="p2", card_name="Galvanic Discharge"),
            Action(type=ActionType.PASS_PRIORITY, player_id="p2"),
        ]
        result = opp.choose_action(state, actions)
        assert result.type == ActionType.PLAY_LAND  # land first


class TestDFCParsing:
    def test_dfc_from_scryfall(self):
        """Test parsing a DFC card from Scryfall-style data."""
        dfc_data = {
            "name": "Ajani, Nacatl Pariah // Ajani, Nacatl Avenger",
            "cmc": 2.0,
            "type_line": "Legendary Creature — Cat Warrior // Legendary Planeswalker — Ajani",
            "keywords": [],
            "color_identity": ["W"],
            "id": "test-id",
            "legalities": {"modern": "legal"},
            "card_faces": [
                {
                    "name": "Ajani, Nacatl Pariah",
                    "mana_cost": "{1}{W}",
                    "type_line": "Legendary Creature — Cat Warrior",
                    "oracle_text": "When Ajani enters, create a 2/1 white Cat Warrior token.",
                    "power": "1",
                    "toughness": "2",
                    "colors": ["W"],
                },
                {
                    "name": "Ajani, Nacatl Avenger",
                    "mana_cost": "",
                    "type_line": "Legendary Planeswalker — Ajani",
                    "oracle_text": "+2: Put a +1/+1 counter...",
                    "loyalty": "3",
                    "colors": ["R", "W"],
                },
            ],
        }
        card = CardDefinition.from_scryfall(dfc_data)
        assert card.name == "Ajani, Nacatl Pariah // Ajani, Nacatl Avenger"
        assert card.mana_cost == "{1}{W}"
        assert card.power == "1"
        assert card.toughness == "2"
        assert "When Ajani enters" in card.oracle_text
