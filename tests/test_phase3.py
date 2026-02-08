"""Phase 3 tests: match runner, sideboard, game logging, opponent templates, visual display."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, GameState, ManaPool, Phase, PlayerState, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import Resolver
from eight_rack.match.runner import GameResult, MatchResult, MatchRunner
from eight_rack.match.sideboard import SideboardManager, EIGHT_RACK_SB_GUIDES
from eight_rack.match.logger import MatchLogger
from eight_rack.display import (
    render_board, _render_mini_card, _render_info_bar, _render_phase_bar,
    _get_card_color, _get_type_icon,
)


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
MOUNTAIN = make_card("Mountain")
THE_RACK = make_card(
    "The Rack",
    mana_cost="{1}",
    cmc=1.0,
    type_line="Artifact",
    oracle_text="At the beginning of each opponent's upkeep, The Rack deals X damage to that player, where X is 3 minus the number of cards in their hand.",
    card_types=[CardType.ARTIFACT],
)
RAVENS_CRIME = make_card(
    "Raven's Crime",
    mana_cost="{B}",
    cmc=1.0,
    type_line="Sorcery",
    oracle_text="Target player discards a card.",
    card_types=[CardType.SORCERY],
)
FATAL_PUSH = make_card(
    "Fatal Push",
    mana_cost="{B}",
    cmc=1.0,
    type_line="Instant",
    oracle_text="Destroy target creature if it has converted mana cost 2 or less.",
    card_types=[CardType.INSTANT],
)
WRENCH_MIND = make_card(
    "Wrench Mind",
    mana_cost="{B}{B}",
    cmc=2.0,
    type_line="Sorcery",
    card_types=[CardType.SORCERY],
)
FUNERAL_CHARM = make_card(
    "Funeral Charm",
    mana_cost="{B}",
    cmc=1.0,
    type_line="Instant",
    card_types=[CardType.INSTANT],
)
BONTUS_RECKONING = make_card(
    "Bontu's Last Reckoning",
    mana_cost="{1}{B}{B}",
    cmc=3.0,
    type_line="Sorcery",
    card_types=[CardType.SORCERY],
)
ENSNARING_BRIDGE = make_card(
    "Ensnaring Bridge",
    mana_cost="{3}",
    cmc=3.0,
    type_line="Artifact",
    card_types=[CardType.ARTIFACT],
)
LEYLINE_OF_VOID = make_card(
    "Leyline of the Void",
    mana_cost="{2}{B}{B}",
    cmc=4.0,
    type_line="Enchantment",
    card_types=[CardType.ENCHANTMENT],
)
DAMPING_SPHERE = make_card(
    "Damping Sphere",
    mana_cost="{2}",
    cmc=2.0,
    type_line="Artifact",
    card_types=[CardType.ARTIFACT],
)
RAGAVAN = make_card(
    "Ragavan, Nimble Pilferer",
    mana_cost="{R}",
    cmc=1.0,
    type_line="Legendary Creature — Monkey Pirate",
    card_types=[CardType.CREATURE],
    power="2",
    toughness="1",
)
THOUGHT_KNOT = make_card(
    "Thought-Knot Seer",
    mana_cost="{3}{C}",
    cmc=4.0,
    type_line="Creature — Eldrazi",
    oracle_text="When Thought-Knot Seer enters the battlefield, target opponent reveals their hand. You choose a nonland card from it and exile that card.",
    card_types=[CardType.CREATURE],
    power="4",
    toughness="4",
)


# --- Match Runner Tests ---

class TestMatchResult:
    def test_is_complete_p1_wins(self):
        result = MatchResult(p1_wins=2, p2_wins=1)
        assert result.is_complete

    def test_is_complete_p2_wins(self):
        result = MatchResult(p1_wins=0, p2_wins=2)
        assert result.is_complete

    def test_not_complete(self):
        result = MatchResult(p1_wins=1, p2_wins=1)
        assert not result.is_complete

    def test_match_id_generated(self):
        r1 = MatchResult()
        r2 = MatchResult()
        assert r1.match_id != r2.match_id


class TestGameResult:
    def test_game_result_fields(self):
        gr = GameResult(
            game_number=1,
            winner_id="p1",
            winner_name="8 Rack",
            loser_name="Boros Energy",
            turns=12,
            p1_life=15,
            p2_life=0,
        )
        assert gr.game_number == 1
        assert gr.winner_name == "8 Rack"
        assert not gr.is_post_sideboard


# --- Sideboard Tests ---

class TestSideboardManager:
    def _make_mainboard(self):
        """Create a simplified mainboard."""
        cards = []
        for _ in range(4):
            cards.append(RAVENS_CRIME)
        for _ in range(2):
            cards.append(FUNERAL_CHARM)
        cards.append(WRENCH_MIND)
        cards.append(FATAL_PUSH)
        # Fill rest with swamps
        while len(cards) < 60:
            cards.append(SWAMP)
        return cards

    def _make_sideboard(self):
        """Create a simplified sideboard."""
        return [
            FATAL_PUSH,
            BONTUS_RECKONING,
            BONTUS_RECKONING,
            ENSNARING_BRIDGE,
            LEYLINE_OF_VOID,
            LEYLINE_OF_VOID,
            LEYLINE_OF_VOID,
            LEYLINE_OF_VOID,
            DAMPING_SPHERE,
            DAMPING_SPHERE,
        ]

    def test_heuristic_boros_energy(self):
        sb_mgr = SideboardManager()
        main = self._make_mainboard()
        sb = self._make_sideboard()

        new_main, new_sb = sb_mgr.sideboard(
            mainboard=main,
            sideboard=sb,
            opponent_deck_name="Boros Energy",
            game_results=[],
            is_pilot=True,
        )
        # Should swap cards in/out
        assert len(new_main) == 60
        assert len(new_sb) == len(sb)
        # Fatal Push should be in mainboard (brought in)
        main_names = [c.name for c in new_main]
        assert main_names.count("Fatal Push") >= 2  # original + brought in

    def test_opponent_no_sideboard(self):
        sb_mgr = SideboardManager()
        main = [MOUNTAIN] * 60
        sb = [RAGAVAN] * 15

        new_main, new_sb = sb_mgr.sideboard(
            mainboard=main,
            sideboard=sb,
            opponent_deck_name="8 Rack",
            game_results=[],
            is_pilot=False,
        )
        # Opponent shouldn't sideboard
        assert len(new_main) == 60
        assert all(c.name == "Mountain" for c in new_main)

    def test_unknown_archetype_no_llm(self):
        sb_mgr = SideboardManager()
        main = [SWAMP] * 60
        sb = [FATAL_PUSH] * 15

        new_main, new_sb = sb_mgr.sideboard(
            mainboard=main,
            sideboard=sb,
            opponent_deck_name="Unknown Deck",
            game_results=[],
            is_pilot=True,
        )
        # No guide, no LLM -> unchanged
        assert len(new_main) == 60
        assert all(c.name == "Swamp" for c in new_main)

    def test_all_archetypes_have_guides(self):
        """Verify all 10 meta decks have sideboard guides."""
        expected = {
            "boros_energy", "ruby_storm", "jeskai_blink", "eldrazi_tron",
            "affinity", "domain_zoo", "amulet_titan", "neobrand",
            "goryos_vengeance", "yawgmoth",
        }
        assert set(EIGHT_RACK_SB_GUIDES.keys()) == expected


# --- JSONL Logger Tests ---

class TestMatchLogger:
    def test_log_and_load_match(self, tmp_path):
        logger = MatchLogger(tmp_path)
        result = MatchResult(
            match_id="test123",
            p1_name="8 Rack",
            p2_name="Boros Energy",
            p1_deck="8 Rack",
            p2_deck="Boros Energy",
            p1_wins=2,
            p2_wins=1,
            match_winner_id="p1",
            match_winner_name="8 Rack",
            games=[
                GameResult(game_number=1, winner_name="8 Rack", turns=12),
                GameResult(game_number=2, winner_name="Boros Energy", turns=8),
                GameResult(game_number=3, winner_name="8 Rack", turns=15),
            ],
        )
        logger.log_match(result)

        matches = logger.load_matches()
        assert len(matches) == 1
        assert matches[0]["match_id"] == "test123"
        assert matches[0]["match_winner"] == "8 Rack"

        games = logger.load_games()
        assert len(games) == 3
        assert games[0]["game_number"] == 1
        assert games[2]["game_number"] == 3

    def test_load_empty(self, tmp_path):
        logger = MatchLogger(tmp_path)
        assert logger.load_matches() == []
        assert logger.load_games() == []


# --- Opponent Template Tests ---

class TestNewOpponentTemplates:
    def test_thought_knot_seer_exiles(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[
                make_instance(RAVENS_CRIME, Zone.HAND, "p1"),
                make_instance(SWAMP, Zone.HAND, "p1"),
            ]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(THOUGHT_KNOT, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        tks = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=tks.id,
            card_name="Thought-Knot Seer",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        # Should exile a nonland from opponent's hand
        exiled = [c for c in state.players[0].cards if c.zone == Zone.EXILE]
        assert len(exiled) == 1
        assert exiled[0].name == "Raven's Crime"  # only nonland

    def test_grapeshot_damage(self):
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(
                    make_card("Grapeshot", mana_cost="{1}{R}", cmc=2.0,
                              type_line="Sorcery", card_types=[CardType.SORCERY],
                              oracle_text="Grapeshot deals 1 damage to any target. Storm"),
                    Zone.HAND, "p2"
                ),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        gs = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=gs.id,
            card_name="Grapeshot",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        # Should deal at least 1 damage
        assert state.players[0].life < 20

    def test_dismember_kills_creature(self):
        bowmasters = make_card(
            "Orcish Bowmasters",
            mana_cost="{1}{B}",
            cmc=2.0,
            type_line="Creature",
            card_types=[CardType.CREATURE],
            power="1",
            toughness="1",
        )
        bm_inst = make_instance(bowmasters, Zone.BATTLEFIELD, "p1")
        dismember = make_card(
            "Dismember",
            mana_cost="{1}{B/P}{B/P}",
            cmc=3.0,
            type_line="Instant",
            card_types=[CardType.INSTANT],
            oracle_text="Target creature gets -5/-5 until end of turn.",
        )
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[bm_inst]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(dismember, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        dm = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=dm.id,
            card_name="Dismember",
            targets=[bm_inst.id],
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert bm_inst.zone == Zone.GRAVEYARD  # -5/-5 kills 1/1
        assert state.players[1].life == 16  # paid 4 life

    def test_ritual_adds_mana(self):
        ritual = make_card(
            "Desperate Ritual",
            mana_cost="{1}{R}",
            cmc=2.0,
            type_line="Instant — Arcane",
            card_types=[CardType.INSTANT],
        )
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(ritual, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        resolver = Resolver()
        r = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=r.id,
            card_name="Desperate Ritual",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert state.players[1].mana_pool.red >= 3

    def test_all_is_dust(self):
        colored_creature = make_card(
            "Orcish Bowmasters",
            mana_cost="{1}{B}",
            cmc=2.0,
            type_line="Creature",
            card_types=[CardType.CREATURE],
            power="1",
            toughness="1",
            colors=["B"],
        )
        bm_inst = make_instance(colored_creature, Zone.BATTLEFIELD, "p1")
        aid = make_card(
            "All Is Dust",
            mana_cost="{7}",
            cmc=7.0,
            type_line="Tribal Sorcery — Eldrazi",
            card_types=[CardType.SORCERY],
        )
        state = GameState(players=[
            PlayerState(id="p1", name="P1", cards=[bm_inst]),
            PlayerState(id="p2", name="P2", cards=[
                make_instance(aid, Zone.HAND, "p2"),
                # 7 mountains for mana
                *[make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2") for _ in range(7)],
            ]),
        ])
        resolver = Resolver()
        a = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p2",
            card_id=a.id,
            card_name="All Is Dust",
        )
        result = resolver.resolve(state, action)
        assert result.success
        result2 = resolver.resolve_top_of_stack(state)
        assert result2.success
        assert bm_inst.zone == Zone.GRAVEYARD  # colored permanent sacrificed


# --- Visual Display Tests ---

class TestVisualDisplay:
    def test_render_board(self):
        state = GameState(players=[
            PlayerState(id="p1", name="8 Rack", life=18, cards=[
                make_instance(SWAMP, Zone.BATTLEFIELD, "p1"),
                make_instance(THE_RACK, Zone.BATTLEFIELD, "p1"),
                make_instance(RAVENS_CRIME, Zone.HAND, "p1"),
            ]),
            PlayerState(id="p2", name="Boros Energy", life=14, cards=[
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(RAGAVAN, Zone.BATTLEFIELD, "p2"),
            ]),
        ])
        state.turn_number = 5
        state.phase = Phase.MAIN_1

        output = render_board(state)
        assert "Turn 5" in output
        assert "Main 1" in output
        assert "8 Rack" in output
        assert "Boros Energy" in output
        assert "18" in output  # p1 life
        assert "14" in output  # p2 life

    def test_info_bar_life_colors(self):
        """Info bar shows life with color coding."""
        p = PlayerState(id="p1", name="Test", life=20, cards=[])
        bar = _render_info_bar(p)
        assert "20" in bar
        assert "green" in bar  # life > 10 => green
        p_low = PlayerState(id="p1", name="Test", life=3, cards=[])
        bar_low = _render_info_bar(p_low)
        assert "3" in bar_low
        assert "red" in bar_low  # life <= 5 => red

    def test_mini_card_creature(self):
        inst = make_instance(RAGAVAN, Zone.BATTLEFIELD, "p2")
        lines = _render_mini_card(inst)
        joined = " ".join(lines)
        assert "Ragavan" in joined
        assert "⚔" in joined

    def test_mini_card_tapped(self):
        inst = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        inst.tapped = True
        lines = _render_mini_card(inst, is_tapped=True)
        joined = " ".join(lines)
        # Tapped cards use dashed borders (┄)
        assert "┄" in joined

    def test_mini_card_face_down(self):
        inst = make_instance(SWAMP, Zone.HAND, "p2")
        lines = _render_mini_card(inst, face_down=True)
        joined = " ".join(lines)
        assert "░" in joined

    def test_phase_bar_highlights_active(self):
        bar = _render_phase_bar(Phase.MAIN_1)
        assert "●Main 1" in bar

    def test_card_color_land(self):
        inst = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        assert _get_card_color(inst) == "yellow"

    def test_card_color_red_creature(self):
        red_ragavan = make_card(
            "Ragavan, Nimble Pilferer",
            mana_cost="{R}", cmc=1.0,
            type_line="Legendary Creature — Monkey Pirate",
            card_types=[CardType.CREATURE], power="2", toughness="1",
            colors=["R"],
        )
        inst = make_instance(red_ragavan, Zone.BATTLEFIELD, "p2")
        assert _get_card_color(inst) == "red"

    def test_type_icon_creature(self):
        inst = make_instance(RAGAVAN, Zone.BATTLEFIELD, "p2")
        assert _get_type_icon(inst) == "⚔"

    def test_type_icon_artifact(self):
        inst = make_instance(THE_RACK, Zone.BATTLEFIELD, "p1")
        assert _get_type_icon(inst) == "⚙"
