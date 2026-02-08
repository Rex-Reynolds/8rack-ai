"""Tests for engine fixes: legend rule, dual mana, funeral charm, menace, storm count, temp counters."""

import pytest

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, CombatState, GameState, ManaPool, Phase, PlayerState, StackItem, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import (
    DUAL_LAND_COLORS, Resolver, _effective_power, _effective_toughness,
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

SACRED_FOUNDRY = make_card(
    "Sacred Foundry",
    type_line="Land — Mountain Plains",
    subtypes=["Mountain", "Plains"],
)

BLOOD_CRYPT = make_card(
    "Blood Crypt",
    type_line="Land — Swamp Mountain",
    subtypes=["Swamp", "Mountain"],
)

STEAM_VENTS = make_card(
    "Steam Vents",
    type_line="Land — Island Mountain",
    subtypes=["Island", "Mountain"],
)

BEAR = make_card(
    "Grizzly Bears", mana_cost="{1}{G}", cmc=2.0,
    type_line="Creature — Bear",
    card_types=[CardType.CREATURE],
    power="2", toughness="2",
)

GOBLIN = make_card(
    "Goblin Guide", mana_cost="{R}", cmc=1.0,
    type_line="Creature — Goblin Scout",
    card_types=[CardType.CREATURE],
    power="2", toughness="2",
    keywords=["Haste"],
)

MENACE_CREATURE = make_card(
    "Dauthi Voidwalker", mana_cost="{B}{B}", cmc=2.0,
    type_line="Creature — Dauthi Rogue",
    card_types=[CardType.CREATURE],
    power="3", toughness="2",
    keywords=["Menace"],
)

ELF = make_card(
    "Llanowar Elves", mana_cost="{G}", cmc=1.0,
    type_line="Creature — Elf Druid",
    card_types=[CardType.CREATURE],
    power="1", toughness="1",
)

FUNERAL_CHARM = make_card(
    "Funeral Charm", mana_cost="{B}", cmc=1.0,
    type_line="Instant",
    card_types=[CardType.INSTANT],
)

MOUNTAIN = make_card("Mountain")
PLAINS = make_card("Plains")
FOREST = make_card("Forest")

BOLT = make_card(
    "Lightning Bolt", mana_cost="{R}", cmc=1.0,
    type_line="Instant",
    card_types=[CardType.INSTANT],
)


# ============================================================
# Legend Rule Tests
# ============================================================

class TestLegendRule:

    def test_is_legendary_property(self):
        assert LILIANA.is_legendary
        assert not BEAR.is_legendary
        assert not SWAMP.is_legendary

    def test_duplicate_legendary_dies(self):
        """If two Lilianas are on the battlefield, SBA sends the older one to graveyard."""
        lili1 = make_instance(LILIANA, Zone.BATTLEFIELD, "p1")
        lili1.counters["loyalty"] = 3
        lili2 = make_instance(LILIANA, Zone.BATTLEFIELD, "p1")
        lili2.counters["loyalty"] = 3

        state = make_two_player_state(p1_cards=[lili1, lili2])
        actions = state.check_state_based_actions()

        # The first (older) should die
        assert lili1.zone == Zone.GRAVEYARD
        assert lili2.zone == Zone.BATTLEFIELD
        assert any("Legend rule" in a for a in actions)

    def test_different_legendaries_coexist(self):
        """Two different legendary permanents can coexist."""
        karn = make_card(
            "Karn, the Great Creator", mana_cost="{4}", cmc=4.0,
            type_line="Legendary Planeswalker — Karn",
            card_types=[CardType.PLANESWALKER],
            loyalty="5",
        )
        lili = make_instance(LILIANA, Zone.BATTLEFIELD, "p1")
        lili.counters["loyalty"] = 3
        karn_inst = make_instance(karn, Zone.BATTLEFIELD, "p1")
        karn_inst.counters["loyalty"] = 5

        state = make_two_player_state(p1_cards=[lili, karn_inst])
        actions = state.check_state_based_actions()

        assert lili.zone == Zone.BATTLEFIELD
        assert karn_inst.zone == Zone.BATTLEFIELD
        assert not any("Legend rule" in a for a in actions)

    def test_non_legendary_duplicates_fine(self):
        """Non-legendary duplicates should not trigger legend rule."""
        bear1 = make_instance(BEAR, Zone.BATTLEFIELD, "p1")
        bear2 = make_instance(BEAR, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[bear1, bear2])
        actions = state.check_state_based_actions()

        assert bear1.zone == Zone.BATTLEFIELD
        assert bear2.zone == Zone.BATTLEFIELD

    def test_legend_rule_different_players(self):
        """Each player can have their own legendary with the same name."""
        lili1 = make_instance(LILIANA, Zone.BATTLEFIELD, "p1")
        lili1.counters["loyalty"] = 3
        lili2 = make_instance(LILIANA, Zone.BATTLEFIELD, "p2")
        lili2.counters["loyalty"] = 3

        state = make_two_player_state(p1_cards=[lili1], p2_cards=[lili2])
        actions = state.check_state_based_actions()

        # Each player keeps their own copy
        assert lili1.zone == Zone.BATTLEFIELD
        assert lili2.zone == Zone.BATTLEFIELD


# ============================================================
# Dual Land Mana Tests
# ============================================================

class TestDualLandMana:

    def test_sacred_foundry_pays_red(self):
        """Sacred Foundry should be able to pay {R} via auto_tap_lands."""
        sf = make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[sf])
        resolver = Resolver()
        result = resolver.auto_tap_lands(state, "p1", "{R}")
        assert result is True
        assert sf.tapped

    def test_sacred_foundry_pays_white(self):
        """Sacred Foundry should be able to pay {W} via auto_tap_lands."""
        sf = make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[sf])
        resolver = Resolver()
        result = resolver.auto_tap_lands(state, "p1", "{W}")
        assert result is True
        assert sf.tapped

    def test_dual_prefers_basic_over_dual(self):
        """Auto-tapper should prefer basics over duals when possible."""
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        sf = make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")
        mountain = make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p1")

        state = make_two_player_state(p1_cards=[swamp, sf, mountain])
        resolver = Resolver()
        # Pay {R}{W} — mountain for R, sacred foundry for W
        result = resolver.auto_tap_lands(state, "p1", "{R}{W}")
        assert result is True
        # Both mountain and sacred foundry tapped, swamp untapped
        assert mountain.tapped
        assert sf.tapped
        assert not swamp.tapped

    def test_can_pay_cost_dual_flexibility(self):
        """_can_pay_cost should recognize dual lands can provide either color."""
        sf = make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[sf])
        resolver = Resolver()
        player = state.players[0]

        # Can pay either color
        assert resolver._can_pay_cost(state, player, "{R}")
        assert resolver._can_pay_cost(state, player, "{W}")

    def test_can_pay_two_color_with_two_duals(self):
        """Two different duals can pay for their respective colors."""
        sf = make_instance(SACRED_FOUNDRY, Zone.BATTLEFIELD, "p1")
        sv = make_instance(STEAM_VENTS, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[sf, sv])
        resolver = Resolver()
        player = state.players[0]

        # {R}{U} — Sacred Foundry for R, Steam Vents for U (or vice versa)
        assert resolver._can_pay_cost(state, player, "{R}{U}")

    def test_blood_crypt_default_mana(self):
        """Blood Crypt default mana production is black."""
        bc = make_instance(BLOOD_CRYPT, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[bc])
        resolver = Resolver()
        mana = resolver._get_land_mana(bc, state)
        assert mana == {"black": 1}

    def test_all_duals_in_constant(self):
        """All 10 shock lands should be in DUAL_LAND_COLORS."""
        expected = {
            "Sacred Foundry", "Hallowed Fountain", "Steam Vents",
            "Blood Crypt", "Overgrown Tomb", "Stomping Ground",
            "Temple Garden", "Watery Grave", "Godless Shrine", "Breeding Pool",
        }
        assert set(DUAL_LAND_COLORS.keys()) == expected


# ============================================================
# Funeral Charm Fix Tests
# ============================================================

class TestFuneralCharmFix:

    def test_shrink_uses_temp_counter_not_damage(self):
        """-1/-1 mode should use m1m1_temp counter, not damage."""
        bear = make_instance(BEAR, Zone.BATTLEFIELD, "p2")
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm], p2_cards=[bear])
        resolver = Resolver()

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "shrink"},
            targets=[bear.id],
        )
        result = resolver._resolve_funeral_charm(state, action, charm)
        assert result.success
        assert bear.counters.get("m1m1_temp", 0) == 1
        assert bear.damage_marked == 0  # No damage, uses counter instead

    def test_shrink_kills_1_1(self):
        """-1/-1 on a 1/1 creature: toughness becomes 0, dies in SBA."""
        elf = make_instance(ELF, Zone.BATTLEFIELD, "p2")
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm], p2_cards=[elf])
        resolver = Resolver()

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "shrink"},
            targets=[elf.id],
        )
        resolver._resolve_funeral_charm(state, action, charm)
        # SBA should kill the 1/1 with -1/-1
        sba = state.check_state_based_actions()
        assert elf.zone == Zone.GRAVEYARD
        assert any("0 toughness" in a for a in sba)

    def test_shrink_2_2_survives(self):
        """-1/-1 on a 2/2 creature: becomes 1/1, survives."""
        bear = make_instance(BEAR, Zone.BATTLEFIELD, "p2")
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm], p2_cards=[bear])
        resolver = Resolver()

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "shrink"},
            targets=[bear.id],
        )
        resolver._resolve_funeral_charm(state, action, charm)
        sba = state.check_state_based_actions()
        assert bear.zone == Zone.BATTLEFIELD
        assert _effective_toughness(bear) == 1

    def test_shrink_wears_off_at_cleanup(self):
        """-1/-1 temp counter should be cleared during cleanup step."""
        bear = make_instance(BEAR, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[bear])
        bear.counters["m1m1_temp"] = 1

        resolver = Resolver()
        resolver.resolve_cleanup_step(state)
        assert bear.counters.get("m1m1_temp") is None
        assert _effective_toughness(bear) == 2

    def test_pump_uses_temp_counters(self):
        """+2/-1 mode should use pump_power_temp and pump_toughness_temp."""
        bear = make_instance(BEAR, Zone.BATTLEFIELD, "p1")
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm, bear])
        resolver = Resolver()

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "pump"},
            targets=[bear.id],
        )
        result = resolver._resolve_funeral_charm(state, action, charm)
        assert result.success
        assert _effective_power(bear) == 4   # 2 base + 2 pump
        assert _effective_toughness(bear) == 1  # 2 base - 1 pump

    def test_pump_minus1_kills_1_toughness(self):
        """+2/-1 on a 1/1 creature should kill it via SBA (toughness 0)."""
        elf = make_instance(ELF, Zone.BATTLEFIELD, "p1")
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm, elf])
        resolver = Resolver()

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "pump"},
            targets=[elf.id],
        )
        resolver._resolve_funeral_charm(state, action, charm)
        sba = state.check_state_based_actions()
        assert elf.zone == Zone.GRAVEYARD

    def test_pump_wears_off_at_cleanup(self):
        """Pump temp counters should be cleared during cleanup."""
        bear = make_instance(BEAR, Zone.BATTLEFIELD, "p1")
        bear.counters["pump_power_temp"] = 2
        bear.counters["pump_toughness_temp"] = -1

        state = make_two_player_state(p1_cards=[bear])
        resolver = Resolver()
        resolver.resolve_cleanup_step(state)
        assert bear.counters.get("pump_power_temp") is None
        assert bear.counters.get("pump_toughness_temp") is None
        assert _effective_power(bear) == 2
        assert _effective_toughness(bear) == 2

    def test_shrink_interacts_with_p1p1(self):
        """-1/-1 temp on a creature with +1/+1 counter: nets out."""
        elf = make_instance(ELF, Zone.BATTLEFIELD, "p2")
        elf.counters["p1p1"] = 1  # 2/2 now

        state = make_two_player_state(p2_cards=[elf])
        elf.counters["m1m1_temp"] = 1  # back to 1/1

        assert _effective_power(elf) == 1
        assert _effective_toughness(elf) == 1
        # Should survive SBA (toughness = 1 > 0)
        sba = state.check_state_based_actions()
        assert elf.zone == Zone.BATTLEFIELD


# ============================================================
# Menace Enforcement Tests
# ============================================================

class TestMenaceEnforcement:

    def _make_combat_state(self, attacker_card, blocker_cards, p1_extras=None, p2_extras=None):
        """Helper: set up a combat state with attacker and optional blockers."""
        atk = make_instance(attacker_card, Zone.BATTLEFIELD, "p1")
        atk.tapped = True
        cards_p1 = [atk] + (p1_extras or [])

        blockers = [make_instance(c, Zone.BATTLEFIELD, "p2") for c in blocker_cards]
        cards_p2 = blockers + (p2_extras or [])

        state = GameState(
            players=[
                PlayerState(id="p1", name="Attacker", cards=cards_p1),
                PlayerState(id="p2", name="Defender", cards=cards_p2),
            ],
            phase=Phase.DECLARE_BLOCKERS,
            combat=CombatState(
                attackers=[atk.id],
                blockers={b.id: atk.id for b in blockers},
            ),
        )
        return state, atk, blockers

    def test_menace_zero_blockers_unblocked(self):
        """Menace creature with 0 blockers is unblocked — no enforcement needed."""
        state, atk, _ = self._make_combat_state(MENACE_CREATURE, [])
        from eight_rack.game.engine import GameEngine
        from eight_rack.cards.database import CardDatabase
        engine = GameEngine.__new__(GameEngine)
        engine.resolver = Resolver()
        engine._enforce_menace(state)
        # No blockers assigned, nothing changed
        assert len(state.combat.blockers) == 0

    def test_menace_one_blocker_removed(self):
        """Menace creature with only 1 blocker: block assignment removed."""
        state, atk, blockers = self._make_combat_state(MENACE_CREATURE, [BEAR])
        assert len(state.combat.blockers) == 1

        from eight_rack.game.engine import GameEngine
        engine = GameEngine.__new__(GameEngine)
        engine.resolver = Resolver()
        engine._enforce_menace(state)

        # Single blocker removed (menace requires 2+)
        assert len(state.combat.blockers) == 0

    def test_menace_two_blockers_ok(self):
        """Menace creature with 2 blockers: block stays."""
        state, atk, blockers = self._make_combat_state(MENACE_CREATURE, [BEAR, ELF])
        assert len(state.combat.blockers) == 2

        from eight_rack.game.engine import GameEngine
        engine = GameEngine.__new__(GameEngine)
        engine.resolver = Resolver()
        engine._enforce_menace(state)

        # Both blockers stay
        assert len(state.combat.blockers) == 2

    def test_non_menace_one_blocker_ok(self):
        """Non-menace creature with 1 blocker is fine."""
        state, atk, blockers = self._make_combat_state(BEAR, [ELF])
        assert len(state.combat.blockers) == 1

        from eight_rack.game.engine import GameEngine
        engine = GameEngine.__new__(GameEngine)
        engine.resolver = Resolver()
        engine._enforce_menace(state)

        # Blocker stays (no menace)
        assert len(state.combat.blockers) == 1


# ============================================================
# Storm Count Tests
# ============================================================

class TestStormCount:

    def test_spell_cast_increments_counter(self):
        """Putting a spell on the stack increments spells_cast_this_turn."""
        swamp = make_instance(SWAMP, Zone.BATTLEFIELD, "p1")
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[swamp, charm])
        state.phase = Phase.MAIN_1
        assert state.spells_cast_this_turn == 0

        resolver = Resolver()
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=charm.id,
            card_name="Funeral Charm",
            choices={"mode": "discard"},
        )
        result = resolver.put_spell_on_stack(state, action)
        assert result.success
        assert state.spells_cast_this_turn == 1

    def test_grapeshot_uses_counter(self):
        """Grapeshot should use spells_cast_this_turn for storm count."""
        charm = make_instance(FUNERAL_CHARM, Zone.HAND, "p1")
        grapeshot_def = make_card(
            "Grapeshot", mana_cost="{1}{R}", cmc=2.0,
            type_line="Sorcery",
            card_types=[CardType.SORCERY],
        )
        gs = make_instance(grapeshot_def, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[charm, gs])
        state.spells_cast_this_turn = 4  # 3 previous spells + Grapeshot itself

        resolver = Resolver()
        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=gs.id,
            card_name="Grapeshot",
        )
        result = resolver._resolve_grapeshot(state, action, gs)
        assert result.success
        assert state.players[1].life == 16  # 20 - 4 storm copies

    def test_storm_count_resets_between_turns(self):
        """spells_cast_this_turn should be 0 at start, can be set, and is tracked."""
        state = make_two_player_state()
        assert state.spells_cast_this_turn == 0
        state.spells_cast_this_turn = 5
        assert state.spells_cast_this_turn == 5


# ============================================================
# Effective Power/Toughness with Temp Counters
# ============================================================

class TestEffectivePTWithTemp:

    def test_m1m1_temp_reduces(self):
        bear = make_instance(BEAR, Zone.BATTLEFIELD)
        bear.counters["m1m1_temp"] = 1
        assert _effective_power(bear) == 1
        assert _effective_toughness(bear) == 1

    def test_pump_power_temp_increases(self):
        bear = make_instance(BEAR, Zone.BATTLEFIELD)
        bear.counters["pump_power_temp"] = 3
        assert _effective_power(bear) == 5
        assert _effective_toughness(bear) == 2  # toughness unaffected

    def test_pump_toughness_temp_negative(self):
        bear = make_instance(BEAR, Zone.BATTLEFIELD)
        bear.counters["pump_toughness_temp"] = -1
        assert _effective_toughness(bear) == 1

    def test_all_counters_combined(self):
        bear = make_instance(BEAR, Zone.BATTLEFIELD)
        bear.counters["p1p1"] = 2
        bear.counters["m1m1_temp"] = 1
        bear.counters["pump_power_temp"] = 1
        bear.counters["pump_toughness_temp"] = -2
        # Power: 2 + 2 - 1 + 1 = 4
        # Toughness: 2 + 2 - 1 + (-2) = 1
        assert _effective_power(bear) == 4
        assert _effective_toughness(bear) == 1
