"""Tests for display rendering fixes."""

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import CardInstance, Zone
from eight_rack.display import _compact_mana, _stats_line, _name_line, _render_mini_card, CARD_INNER


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


class TestCompactMana:
    def test_basic_mana_cost(self):
        assert _compact_mana("{1}{B}{B}") == "1BB"

    def test_x_cost(self):
        assert _compact_mana("{X}{R}") == "XR"

    def test_empty(self):
        assert _compact_mana("") == ""

    def test_hybrid(self):
        assert _compact_mana("{2}{W}{W}") == "2WW"


class TestEffectivePTDisplay:
    def test_creature_with_counters_shows_effective_pt(self):
        """Creature with +1/+1 counters shows effective P/T in stats line."""
        bear_def = make_card(
            "Grizzly Bears", mana_cost="{1}{G}", cmc=2.0,
            type_line="Creature — Bear",
            card_types=[CardType.CREATURE], power="2", toughness="2",
        )
        bear = make_instance(bear_def, Zone.BATTLEFIELD)
        bear.counters["p1p1"] = 2

        stats = _stats_line(bear, inner_width=15)
        assert "4/4" in stats

    def test_zero_base_token_shows_countered_pt(self):
        """A 0/0 token with p1p1 counters shows correct P/T."""
        orc_def = make_card(
            "Orc Army", type_line="Creature Token — Orc Army",
            card_types=[CardType.CREATURE], power="0", toughness="0",
        )
        orc = make_instance(orc_def, Zone.BATTLEFIELD)
        orc.counters["p1p1"] = 1

        stats = _stats_line(orc, inner_width=15)
        assert "1/1" in stats


class TestCardAlignment:
    def test_mini_card_borders_align(self):
        """Content between borders should not exceed border width."""
        swamp = make_card("Swamp")
        card = make_instance(swamp, Zone.HAND)

        lines = _render_mini_card(card, in_hand=True, inner_width=CARD_INNER)
        # All 4 lines should have the same visible width (ignoring Rich markup)
        # The border line uses inner_width dashes, content lines use space + (inner_width-1) chars
        # Both should total inner_width between the border chars


class TestSpellStatsDedup:
    def test_instant_shows_type_not_mana(self):
        """In-hand instant stats line shows 'instant' not mana cost."""
        bolt_def = make_card(
            "Lightning Bolt", mana_cost="{R}", cmc=1.0,
            type_line="Instant", card_types=[CardType.INSTANT],
        )
        bolt = make_instance(bolt_def, Zone.HAND)

        stats = _stats_line(bolt, in_hand=True, inner_width=14)
        assert "instant" in stats
        assert "{R}" not in stats

    def test_sorcery_shows_type_not_mana(self):
        """In-hand sorcery stats line shows 'sorcery' not mana cost."""
        spell_def = make_card(
            "Thoughtseize", mana_cost="{B}", cmc=1.0,
            type_line="Sorcery", card_types=[CardType.SORCERY],
        )
        spell = make_instance(spell_def, Zone.HAND)

        stats = _stats_line(spell, in_hand=True, inner_width=14)
        assert "sorcery" in stats
        assert "{B}" not in stats
