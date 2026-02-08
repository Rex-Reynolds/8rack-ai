"""Tests for rules engine gap fixes: Ensnaring Bridge, Urborg, Castle Locthwain,
Leyline of the Void, fizzling, board wipes, prowess, scry, evoke, Blood Moon,
Teferi, Karn, treasure tokens."""

import pytest

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, CombatState, GameState, ManaPool, Phase, PlayerState, StackItem, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import (
    Resolver, _effective_power, _effective_toughness, destroy_all_creatures, scry,
)
from eight_rack.game.tokens import create_token, create_treasure_token


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
MOUNTAIN = make_card("Mountain")
PLAINS = make_card("Plains")
ISLAND = make_card("Island")
FOREST = make_card("Forest")

MISHRAS_FACTORY = make_card(
    "Mishra's Factory",
    oracle_text="{T}: Add {C}.",
)

CASTLE_LOCTHWAIN = make_card(
    "Castle Locthwain",
    oracle_text="{1}{B}, {T}, Pay life equal to the number of cards in your hand: Draw a card.",
)

URBORG = make_card(
    "Urborg, Tomb of Yawgmoth",
    type_line="Legendary Land",
    card_types=[CardType.LAND],
)

ENSNARING_BRIDGE = make_card(
    "Ensnaring Bridge", mana_cost="{3}", cmc=3.0,
    type_line="Artifact",
    card_types=[CardType.ARTIFACT],
    oracle_text="Creatures with power greater than the number of cards in your hand can't attack.",
)

LEYLINE_OF_THE_VOID = make_card(
    "Leyline of the Void", mana_cost="{2}{B}{B}", cmc=4.0,
    type_line="Enchantment",
    card_types=[CardType.ENCHANTMENT],
    colors=[Color.BLACK],
    oracle_text="If Leyline of the Void is in your opening hand, you may begin the game with it on the battlefield.",
)

BLOOD_MOON = make_card(
    "Blood Moon", mana_cost="{2}{R}", cmc=3.0,
    type_line="Enchantment",
    card_types=[CardType.ENCHANTMENT],
    colors=[Color.RED],
    oracle_text="Nonbasic lands are Mountains.",
)

BONTUS = make_card(
    "Bontu's Last Reckoning", mana_cost="{1}{B}{B}", cmc=3.0,
    type_line="Sorcery",
    card_types=[CardType.SORCERY],
    colors=[Color.BLACK],
    oracle_text="Destroy all creatures. Lands you control don't untap during your next untap step.",
)

LIGHTNING_BOLT = make_card(
    "Lightning Bolt", mana_cost="{R}", cmc=1.0,
    type_line="Instant",
    card_types=[CardType.INSTANT],
    colors=[Color.RED],
    oracle_text="Lightning Bolt deals 3 damage to any target.",
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

MONASTERY_SWIFTSPEAR = make_card(
    "Monastery Swiftspear", mana_cost="{R}", cmc=1.0,
    type_line="Creature — Human Monk",
    card_types=[CardType.CREATURE],
    power="1", toughness="2",
    keywords=["Haste", "Prowess"],
)

SOLITUDE = make_card(
    "Solitude", mana_cost="{3}{W}{W}", cmc=5.0,
    type_line="Creature — Elemental Incarnation",
    card_types=[CardType.CREATURE],
    power="3", toughness="2",
    colors=[Color.WHITE],
    keywords=["Flash", "Lifelink"],
    oracle_text="When Solitude enters the battlefield, exile up to one other target creature. That creature's controller gains life equal to its power.",
)

INDESTRUCTIBLE_CREATURE = make_card(
    "Darksteel Colossus", mana_cost="{11}", cmc=11.0,
    type_line="Artifact Creature — Golem",
    card_types=[CardType.ARTIFACT, CardType.CREATURE],
    power="11", toughness="11",
    keywords=["Trample", "Indestructible"],
)

SACRED_FOUNDRY = make_card(
    "Sacred Foundry",
    type_line="Land — Mountain Plains",
    subtypes=["Mountain", "Plains"],
)


# ====================================================================
# Part 2A: Ensnaring Bridge — controller's hand size
# ====================================================================

class TestEnsnaringBridge:
    def test_bridge_controller_hand_matters(self):
        """Ensnaring Bridge uses its controller's hand size, not attacker's."""
        resolver = Resolver()
        # p1 controls Bridge with 2 cards in hand
        bridge = make_instance(ENSNARING_BRIDGE, zone=Zone.BATTLEFIELD, owner="p1")
        swamp1 = make_instance(SWAMP, zone=Zone.HAND, owner="p1")
        swamp2 = make_instance(SWAMP, zone=Zone.HAND, owner="p1")

        # p2 has a 2/2 creature and 5 cards in hand
        creature = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p2")
        creature.sick = False
        opp_hand = [make_instance(SWAMP, zone=Zone.HAND, owner="p2") for _ in range(5)]

        state = make_two_player_state(
            p1_cards=[bridge, swamp1, swamp2],
            p2_cards=[creature] + opp_hand,
        )
        state.active_player_index = 1  # p2 is attacking
        state.phase = Phase.DECLARE_ATTACKERS

        legal = resolver.get_legal_actions(state, "p2")
        attack_actions = [a for a in legal if a.type == ActionType.ATTACK]
        # Bear has power 2, Bridge controller (p1) has 2 cards → power must be <= 2 → can attack
        assert len(attack_actions) == 1

    def test_bridge_blocks_high_power(self):
        """Creature with power > bridge controller's hand can't attack."""
        resolver = Resolver()
        bridge = make_instance(ENSNARING_BRIDGE, zone=Zone.BATTLEFIELD, owner="p1")
        # p1 has 1 card in hand
        swamp1 = make_instance(SWAMP, zone=Zone.HAND, owner="p1")

        big_creature = make_instance(make_card(
            "Big Dude", mana_cost="{4}", cmc=4.0,
            type_line="Creature — Giant",
            card_types=[CardType.CREATURE],
            power="3", toughness="3",
        ), zone=Zone.BATTLEFIELD, owner="p2")
        big_creature.sick = False

        state = make_two_player_state(
            p1_cards=[bridge, swamp1],
            p2_cards=[big_creature],
        )
        state.active_player_index = 1
        state.phase = Phase.DECLARE_ATTACKERS

        legal = resolver.get_legal_actions(state, "p2")
        attack_actions = [a for a in legal if a.type == ActionType.ATTACK]
        # Power 3 > hand size 1 → can't attack
        assert len(attack_actions) == 0

    def test_bridge_zero_hand_only_zero_power(self):
        """With empty hand, only 0-power creatures can attack."""
        resolver = Resolver()
        bridge = make_instance(ENSNARING_BRIDGE, zone=Zone.BATTLEFIELD, owner="p1")
        # p1 has empty hand

        zero_power = make_instance(make_card(
            "Ornithopter", mana_cost="{0}", cmc=0.0,
            type_line="Artifact Creature — Thopter",
            card_types=[CardType.ARTIFACT, CardType.CREATURE],
            power="0", toughness="2",
            keywords=["Flying"],
        ), zone=Zone.BATTLEFIELD, owner="p2")
        zero_power.sick = False

        one_power = make_instance(make_card(
            "Llanowar Elves", mana_cost="{G}", cmc=1.0,
            type_line="Creature — Elf Druid",
            card_types=[CardType.CREATURE],
            power="1", toughness="1",
        ), zone=Zone.BATTLEFIELD, owner="p2")
        one_power.sick = False

        state = make_two_player_state(
            p1_cards=[bridge],
            p2_cards=[zero_power, one_power],
        )
        state.active_player_index = 1
        state.phase = Phase.DECLARE_ATTACKERS

        legal = resolver.get_legal_actions(state, "p2")
        attack_actions = [a for a in legal if a.type == ActionType.ATTACK]
        # Only Ornithopter (power 0) can attack; Elves (power 1) can't
        assert len(attack_actions) == 1
        assert attack_actions[0].card_name == "Ornithopter"


# ====================================================================
# Part 2B: Urborg, Tomb of Yawgmoth
# ====================================================================

class TestUrborg:
    def test_urborg_makes_factory_tap_for_black(self):
        """With Urborg, Mishra's Factory can be used for black mana costs."""
        resolver = Resolver()
        urborg = make_instance(URBORG, zone=Zone.BATTLEFIELD, owner="p1")
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[urborg, factory])
        result = resolver.auto_tap_lands(state, "p1", "{B}")
        assert result is True

    def test_no_urborg_factory_cant_pay_black(self):
        """Without Urborg, Mishra's Factory can't pay for black."""
        resolver = Resolver()
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[factory])
        result = resolver.auto_tap_lands(state, "p1", "{B}")
        assert result is False

    def test_urborg_mountain_produces_black(self):
        """Urborg makes a Mountain able to pay for black."""
        resolver = Resolver()
        urborg = make_instance(URBORG, zone=Zone.BATTLEFIELD, owner="p1")
        mountain = make_instance(MOUNTAIN, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[urborg, mountain])
        # Should be able to pay {B} using the mountain
        can_pay = resolver._can_pay_cost(state, state.players[0], "{B}")
        assert can_pay is True


# ====================================================================
# Part 2C: Castle Locthwain
# ====================================================================

class TestCastleLocthwain:
    def test_castle_draw_ability_appears(self):
        """Castle Locthwain ability shows up in legal actions when untapped with enough mana."""
        resolver = Resolver()
        castle = make_instance(CASTLE_LOCTHWAIN, zone=Zone.BATTLEFIELD, owner="p1")
        swamp1 = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")
        swamp2 = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[castle, swamp1, swamp2])
        state.active_player_index = 0
        state.phase = Phase.MAIN_1

        legal = resolver.get_legal_actions(state, "p1")
        castle_abilities = [a for a in legal if a.type == ActionType.ACTIVATE_ABILITY and a.card_name == "Castle Locthwain"]
        assert len(castle_abilities) == 1

    def test_castle_not_available_when_tapped(self):
        """Castle Locthwain ability doesn't show when tapped."""
        resolver = Resolver()
        castle = make_instance(CASTLE_LOCTHWAIN, zone=Zone.BATTLEFIELD, owner="p1")
        castle.tapped = True
        swamp1 = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[castle, swamp1])
        state.active_player_index = 0
        state.phase = Phase.MAIN_1

        legal = resolver.get_legal_actions(state, "p1")
        castle_abilities = [a for a in legal if a.type == ActionType.ACTIVATE_ABILITY and a.card_name == "Castle Locthwain"]
        assert len(castle_abilities) == 0


# ====================================================================
# Part 2D: Leyline of the Void
# ====================================================================

class TestLeylineOfTheVoid:
    def test_leyline_graveyard_redirect(self):
        """With Leyline on battlefield, opponent's graveyard destination is exile."""
        leyline = make_instance(LEYLINE_OF_THE_VOID, zone=Zone.BATTLEFIELD, owner="p1")
        state = make_two_player_state(p1_cards=[leyline])
        # p2's cards should go to exile instead of graveyard
        dest = state.graveyard_destination("p2")
        assert dest == Zone.EXILE

    def test_leyline_doesnt_affect_controller(self):
        """Leyline doesn't redirect controller's own cards."""
        leyline = make_instance(LEYLINE_OF_THE_VOID, zone=Zone.BATTLEFIELD, owner="p1")
        state = make_two_player_state(p1_cards=[leyline])
        dest = state.graveyard_destination("p1")
        assert dest == Zone.GRAVEYARD

    def test_no_leyline_normal_graveyard(self):
        """Without Leyline, cards go to graveyard normally."""
        state = make_two_player_state()
        assert state.graveyard_destination("p2") == Zone.GRAVEYARD

    def test_leyline_opening_hand(self):
        """Leyline in opening hand starts on battlefield."""
        from eight_rack.game.engine import GameEngine
        from eight_rack.cards.database import CardDatabase

        leyline = make_instance(LEYLINE_OF_THE_VOID, zone=Zone.HAND, owner="p1")
        state = make_two_player_state(p1_cards=[leyline])

        engine = GameEngine(card_db=CardDatabase.__new__(CardDatabase))
        engine._check_leylines(state)

        assert leyline.zone == Zone.BATTLEFIELD


# ====================================================================
# Part 3A: Fizzling / Target Validation
# ====================================================================

class TestFizzling:
    def test_spell_fizzles_when_target_removed(self):
        """A spell targeting a creature that's no longer on the battlefield fizzles."""
        resolver = Resolver()
        bolt_card = make_instance(LIGHTNING_BOLT, zone=Zone.STACK, owner="p1")
        creature = make_instance(BEAR, zone=Zone.GRAVEYARD, owner="p2")  # Already removed

        state = make_two_player_state(
            p1_cards=[bolt_card],
            p2_cards=[creature],
        )

        item = StackItem(
            source_card_id=bolt_card.id,
            source_card_name="Lightning Bolt",
            controller="p1",
            description="Lightning Bolt (spell)",
            targets=[creature.id],
            card_instance=bolt_card,
            action_data=Action(
                type=ActionType.CAST_SPELL,
                player_id="p1",
                card_id=bolt_card.id,
                card_name="Lightning Bolt",
                targets=[creature.id],
            ).model_dump(),
        )
        state.stack.append(item)

        result = resolver.resolve_top_of_stack(state)
        assert result.success is True
        assert "fizzle" in result.message.lower()
        assert bolt_card.zone == Zone.GRAVEYARD

    def test_player_target_never_fizzles(self):
        """Spells targeting a player don't fizzle."""
        resolver = Resolver()
        bolt_card = make_instance(LIGHTNING_BOLT, zone=Zone.STACK, owner="p1")

        state = make_two_player_state(p1_cards=[bolt_card])

        item = StackItem(
            source_card_id=bolt_card.id,
            source_card_name="Lightning Bolt",
            controller="p1",
            description="Lightning Bolt (spell)",
            targets=["player:p2"],
            card_instance=bolt_card,
            action_data=Action(
                type=ActionType.CAST_SPELL,
                player_id="p1",
                card_id=bolt_card.id,
                card_name="Lightning Bolt",
                targets=["player:p2"],
            ).model_dump(),
        )
        state.stack.append(item)

        result = resolver.resolve_top_of_stack(state)
        assert result.success is True
        assert "fizzle" not in result.message.lower()
        # Bolt deals 3 to p2
        assert state.players[1].life == 17

    def test_spell_resolves_if_target_valid(self):
        """Spell resolves normally when target is still on the battlefield."""
        resolver = Resolver()
        bolt_card = make_instance(LIGHTNING_BOLT, zone=Zone.STACK, owner="p1")
        creature = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p2")

        state = make_two_player_state(
            p1_cards=[bolt_card],
            p2_cards=[creature],
        )

        item = StackItem(
            source_card_id=bolt_card.id,
            source_card_name="Lightning Bolt",
            controller="p1",
            description="Lightning Bolt (spell)",
            targets=[creature.id],
            card_instance=bolt_card,
            action_data=Action(
                type=ActionType.CAST_SPELL,
                player_id="p1",
                card_id=bolt_card.id,
                card_name="Lightning Bolt",
                targets=[creature.id],
            ).model_dump(),
        )
        state.stack.append(item)

        result = resolver.resolve_top_of_stack(state)
        assert result.success is True
        assert "fizzle" not in result.message.lower()


# ====================================================================
# Part 3B: Board Wipes
# ====================================================================

class TestBoardWipes:
    def test_destroy_all_creatures(self):
        """destroy_all_creatures kills all creatures on battlefield."""
        c1 = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p1")
        c2 = make_instance(GOBLIN, zone=Zone.BATTLEFIELD, owner="p2")
        state = make_two_player_state(p1_cards=[c1], p2_cards=[c2])

        changes = destroy_all_creatures(state)
        assert c1.zone == Zone.GRAVEYARD
        assert c2.zone == Zone.GRAVEYARD
        assert len(changes) == 2

    def test_indestructible_survives_board_wipe(self):
        """Indestructible creatures survive destroy_all_creatures."""
        c1 = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p1")
        c2 = make_instance(INDESTRUCTIBLE_CREATURE, zone=Zone.BATTLEFIELD, owner="p2")
        state = make_two_player_state(p1_cards=[c1], p2_cards=[c2])

        changes = destroy_all_creatures(state)
        assert c1.zone == Zone.GRAVEYARD
        assert c2.zone == Zone.BATTLEFIELD  # Survives!
        assert any("survives" in c for c in changes)

    def test_bontus_last_reckoning_template(self):
        """Bontu's Last Reckoning destroys all creatures and marks lands for skip_untap."""
        resolver = Resolver()
        bontus_card = make_instance(BONTUS, zone=Zone.BATTLEFIELD, owner="p1")
        creature1 = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p1")
        creature2 = make_instance(GOBLIN, zone=Zone.BATTLEFIELD, owner="p2")
        swamp = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[bontus_card, creature1, swamp],
            p2_cards=[creature2],
        )

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=bontus_card.id,
            card_name="Bontu's Last Reckoning",
        )
        result = resolver._resolve_bontus_last_reckoning(state, action, bontus_card)
        assert result.success
        assert creature1.zone == Zone.GRAVEYARD
        assert creature2.zone == Zone.GRAVEYARD
        assert swamp.counters.get("skip_untap") == 1


# ====================================================================
# Part 3C: Prowess
# ====================================================================

class TestProwess:
    def test_prowess_triggers_on_noncreature_spell(self):
        """Casting a noncreature spell gives prowess creature +1/+1."""
        resolver = Resolver()
        swiftspear = make_instance(MONASTERY_SWIFTSPEAR, zone=Zone.BATTLEFIELD, owner="p1")
        swiftspear.sick = False
        bolt = make_instance(LIGHTNING_BOLT, zone=Zone.HAND, owner="p1")
        # Need a land to pay for bolt
        mountain = make_instance(MOUNTAIN, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[swiftspear, bolt, mountain],
        )
        state.phase = Phase.MAIN_1

        action = Action(
            type=ActionType.CAST_SPELL,
            player_id="p1",
            card_id=bolt.id,
            card_name="Lightning Bolt",
            targets=["player:p2"],
        )
        resolver.put_spell_on_stack(state, action)

        # Swiftspear should now have +1/+1 temp
        assert swiftspear.counters.get("pump_power_temp", 0) == 1
        assert swiftspear.counters.get("pump_toughness_temp", 0) == 1

    def test_prowess_stacks(self):
        """Multiple noncreature spells stack prowess."""
        resolver = Resolver()
        swiftspear = make_instance(MONASTERY_SWIFTSPEAR, zone=Zone.BATTLEFIELD, owner="p1")
        swiftspear.sick = False
        bolt1 = make_instance(LIGHTNING_BOLT, zone=Zone.HAND, owner="p1")
        bolt2 = make_instance(LIGHTNING_BOLT, zone=Zone.HAND, owner="p1")
        mountain1 = make_instance(MOUNTAIN, zone=Zone.BATTLEFIELD, owner="p1")
        mountain2 = make_instance(MOUNTAIN, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[swiftspear, bolt1, bolt2, mountain1, mountain2],
        )

        # Cast first bolt
        a1 = Action(type=ActionType.CAST_SPELL, player_id="p1", card_id=bolt1.id,
                     card_name="Lightning Bolt", targets=["player:p2"])
        resolver.put_spell_on_stack(state, a1)

        # Cast second bolt
        a2 = Action(type=ActionType.CAST_SPELL, player_id="p1", card_id=bolt2.id,
                     card_name="Lightning Bolt", targets=["player:p2"])
        resolver.put_spell_on_stack(state, a2)

        assert swiftspear.counters.get("pump_power_temp", 0) == 2
        assert swiftspear.counters.get("pump_toughness_temp", 0) == 2

    def test_creature_spell_doesnt_trigger_prowess(self):
        """Casting a creature spell does NOT trigger prowess."""
        resolver = Resolver()
        swiftspear = make_instance(MONASTERY_SWIFTSPEAR, zone=Zone.BATTLEFIELD, owner="p1")
        bear = make_instance(BEAR, zone=Zone.HAND, owner="p1")
        forest = make_instance(FOREST, zone=Zone.BATTLEFIELD, owner="p1")
        forest2 = make_instance(FOREST, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[swiftspear, bear, forest, forest2],
        )

        action = Action(type=ActionType.CAST_SPELL, player_id="p1", card_id=bear.id,
                         card_name="Grizzly Bears")
        resolver.put_spell_on_stack(state, action)

        assert swiftspear.counters.get("pump_power_temp", 0) == 0


# ====================================================================
# Part 3D: Scry
# ====================================================================

class TestScry:
    def test_scry_1_keep_on_top(self):
        """Scry 1: heuristic keeps a non-land card on top when we have lands."""
        resolver = Resolver()
        # Library: bolt on top, then swamps
        bolt = make_instance(LIGHTNING_BOLT, zone=Zone.LIBRARY, owner="p1")
        swamp1 = make_instance(SWAMP, zone=Zone.LIBRARY, owner="p1")
        swamp2 = make_instance(SWAMP, zone=Zone.LIBRARY, owner="p1")
        # Player has 4 lands on battlefield
        lands = [make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1") for _ in range(4)]

        state = make_two_player_state(
            p1_cards=lands + [bolt, swamp1, swamp2],
        )

        changes = scry(state, "p1", 1)
        # Bolt should be kept on top (non-land, have enough lands)
        lib = state.players[0].library
        assert lib[0].name == "Lightning Bolt"

    def test_scry_1_bottom_land_when_flooded(self):
        """Scry 1: heuristic puts excess land on bottom when we have many lands."""
        extra_swamp = make_instance(SWAMP, zone=Zone.LIBRARY, owner="p1")
        bolt = make_instance(LIGHTNING_BOLT, zone=Zone.LIBRARY, owner="p1")
        lands = [make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1") for _ in range(5)]

        state = make_two_player_state(
            p1_cards=lands + [extra_swamp, bolt],
        )

        changes = scry(state, "p1", 1)
        lib = state.players[0].library
        # Swamp should be on bottom (flooded), bolt remains
        assert lib[-1].name == "Swamp"


# ====================================================================
# Part 3E: Evoke
# ====================================================================

class TestEvoke:
    def test_evoke_appears_in_legal_actions(self):
        """Evoke action shows up for Solitude when cost is payable."""
        resolver = Resolver()
        solitude = make_instance(SOLITUDE, zone=Zone.HAND, owner="p1")
        plains = make_instance(PLAINS, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[solitude, plains])
        state.active_player_index = 0
        state.phase = Phase.MAIN_1

        legal = resolver.get_legal_actions(state, "p1")
        evoke_actions = [a for a in legal if a.choices.get("evoke") == "true"]
        assert len(evoke_actions) == 1
        assert "Evoke" in evoke_actions[0].description

    def test_evoke_no_normal_cast_without_mana(self):
        """Can't hardcast Solitude without enough mana, but can evoke."""
        resolver = Resolver()
        solitude = make_instance(SOLITUDE, zone=Zone.HAND, owner="p1")
        plains = make_instance(PLAINS, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[solitude, plains])
        state.active_player_index = 0
        state.phase = Phase.MAIN_1

        legal = resolver.get_legal_actions(state, "p1")
        normal_casts = [a for a in legal if a.type == ActionType.CAST_SPELL
                        and a.card_name == "Solitude" and a.choices.get("evoke") != "true"]
        # Can't hardcast (needs 3WW, only have 1 Plains)
        assert len(normal_casts) == 0

    def test_evoke_sacrifice_trigger_added(self):
        """When evoked creature resolves, a sacrifice trigger is put on the stack."""
        resolver = Resolver()
        solitude = make_instance(SOLITUDE, zone=Zone.STACK, owner="p1")

        state = make_two_player_state(p1_cards=[solitude])

        item = StackItem(
            source_card_id=solitude.id,
            source_card_name="Solitude",
            controller="p1",
            description="Solitude (spell)",
            card_instance=solitude,
            action_data=Action(
                type=ActionType.CAST_SPELL,
                player_id="p1",
                card_id=solitude.id,
                card_name="Solitude",
                choices={"evoke": "true"},
            ).model_dump(),
        )
        state.stack.append(item)

        resolver.resolve_top_of_stack(state)
        # After resolving, sacrifice trigger should be on stack
        assert len(state.stack) == 1
        assert "sacrifice" in state.stack[0].description.lower()

    def test_evoke_sacrifice_resolves(self):
        """Evoke sacrifice trigger removes the creature from battlefield."""
        resolver = Resolver()
        solitude = make_instance(SOLITUDE, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[solitude])

        sac_trigger = StackItem(
            source_card_id=solitude.id,
            source_card_name="Solitude",
            controller="p1",
            description="Evoke sacrifice: Solitude",
            is_ability=True,
            action_data={"evoke_sacrifice": True, "card_id": solitude.id},
        )
        state.stack.append(sac_trigger)

        result = resolver.resolve_top_of_stack(state)
        assert result.success
        assert solitude.zone == Zone.GRAVEYARD


# ====================================================================
# Part 4A: Blood Moon
# ====================================================================

class TestBloodMoon:
    def test_blood_moon_nonbasic_produces_red(self):
        """With Blood Moon, nonbasic lands only produce red."""
        resolver = Resolver()
        blood_moon = make_instance(BLOOD_MOON, zone=Zone.BATTLEFIELD, owner="p2")
        castle = make_instance(CASTLE_LOCTHWAIN, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[castle],
            p2_cards=[blood_moon],
        )

        mana = resolver._get_land_mana(castle, state)
        assert mana == {"red": 1}

    def test_blood_moon_basic_unaffected(self):
        """Blood Moon doesn't affect basic lands."""
        resolver = Resolver()
        blood_moon = make_instance(BLOOD_MOON, zone=Zone.BATTLEFIELD, owner="p2")
        swamp = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[swamp],
            p2_cards=[blood_moon],
        )

        mana = resolver._get_land_mana(swamp, state)
        assert mana == {"black": 1}

    def test_blood_moon_shock_becomes_mountain(self):
        """Blood Moon turns shock lands into Mountains."""
        resolver = Resolver()
        blood_moon = make_instance(BLOOD_MOON, zone=Zone.BATTLEFIELD, owner="p2")
        foundry = make_instance(SACRED_FOUNDRY, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[foundry],
            p2_cards=[blood_moon],
        )

        mana = resolver._get_land_mana(foundry, state)
        assert mana == {"red": 1}


# ====================================================================
# Part 4B: Planeswalker Templates
# ====================================================================

class TestTeferi:
    def test_teferi_etb(self):
        """Teferi enters the battlefield with loyalty."""
        resolver = Resolver()
        teferi = make_instance(make_card(
            "Teferi, Time Raveler", mana_cost="{1}{W}{U}", cmc=3.0,
            type_line="Legendary Planeswalker — Teferi",
            card_types=[CardType.PLANESWALKER],
            loyalty="4",
        ), zone=Zone.BATTLEFIELD, owner="p2")
        teferi.counters["loyalty"] = 4

        state = make_two_player_state(p2_cards=[teferi])
        action = Action(type=ActionType.ACTIVATE_ABILITY, player_id="p2",
                        card_id=teferi.id, card_name="Teferi, Time Raveler")
        result = resolver._resolve_teferi_time_raveler(state, action, teferi)
        assert result.success
        assert "enters" in result.message.lower() or "teferi" in result.message.lower()

    def test_teferi_minus_3_bounces(self):
        """Teferi -3 bounces a nonland permanent."""
        resolver = Resolver()
        teferi = make_instance(make_card(
            "Teferi, Time Raveler", mana_cost="{1}{W}{U}", cmc=3.0,
            type_line="Legendary Planeswalker — Teferi",
            card_types=[CardType.PLANESWALKER],
            loyalty="4",
        ), zone=Zone.BATTLEFIELD, owner="p2")
        teferi.counters["loyalty"] = 4

        target = make_instance(ENSNARING_BRIDGE, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(
            p1_cards=[target],
            p2_cards=[teferi],
        )
        action = Action(type=ActionType.ACTIVATE_ABILITY, player_id="p2",
                        card_id=teferi.id, card_name="Teferi, Time Raveler",
                        choices={"mode": "-3"})
        result = resolver._resolve_teferi_time_raveler(state, action, teferi)
        assert result.success
        assert target.zone == Zone.HAND
        assert teferi.counters["loyalty"] == 1


class TestKarn:
    def test_karn_minus_2_returns_artifact(self):
        """Karn -2 returns an artifact from exile to hand."""
        resolver = Resolver()
        karn = make_instance(make_card(
            "Karn, the Great Creator", mana_cost="{4}", cmc=4.0,
            type_line="Legendary Planeswalker — Karn",
            card_types=[CardType.PLANESWALKER],
            loyalty="5",
        ), zone=Zone.BATTLEFIELD, owner="p2")
        karn.counters["loyalty"] = 5

        exiled_artifact = make_instance(make_card(
            "Ensnaring Bridge", mana_cost="{3}", cmc=3.0,
            type_line="Artifact",
            card_types=[CardType.ARTIFACT],
        ), zone=Zone.EXILE, owner="p2")

        state = make_two_player_state(p2_cards=[karn, exiled_artifact])
        action = Action(type=ActionType.ACTIVATE_ABILITY, player_id="p2",
                        card_id=karn.id, card_name="Karn, the Great Creator",
                        choices={"mode": "-2"})
        result = resolver._resolve_karn_great_creator(state, action, karn)
        assert result.success
        assert exiled_artifact.zone == Zone.HAND
        assert karn.counters["loyalty"] == 3


# ====================================================================
# Part 4C: Treasure Tokens
# ====================================================================

class TestTreasureTokens:
    def test_create_treasure_token(self):
        """create_treasure_token creates a proper Treasure artifact."""
        token = create_treasure_token("p1")
        assert token.name == "Treasure"
        assert token.zone == Zone.BATTLEFIELD
        assert token.definition.is_artifact
        assert not token.sick  # Not a creature

    def test_treasure_sacrifice_in_legal_actions(self):
        """Treasure sacrifice appears in legal actions."""
        resolver = Resolver()
        treasure = create_treasure_token("p1")
        state = make_two_player_state(p1_cards=[treasure])
        state.active_player_index = 0
        state.phase = Phase.MAIN_1

        legal = resolver.get_legal_actions(state, "p1")
        treasure_actions = [a for a in legal if a.choices.get("mode") == "sacrifice_treasure"]
        assert len(treasure_actions) == 1

    def test_treasure_sacrifice_adds_mana(self):
        """Sacrificing a Treasure adds mana and goes to graveyard."""
        resolver = Resolver()
        treasure = create_treasure_token("p1")
        state = make_two_player_state(p1_cards=[treasure])

        action = Action(
            type=ActionType.ACTIVATE_ABILITY,
            player_id="p1",
            card_id=treasure.id,
            card_name="Treasure",
            choices={"mode": "sacrifice_treasure"},
        )
        result = resolver._resolve_activate_ability(state, action)
        assert result.success
        assert treasure.zone == Zone.GRAVEYARD
        assert state.players[0].mana_pool.black == 1


# ====================================================================
# Skip Untap (Bontu's Last Reckoning integration)
# ====================================================================

class TestSkipUntap:
    def test_skip_untap_counter(self):
        """Lands with skip_untap counter don't untap and counter is removed."""
        resolver = Resolver()
        swamp = make_instance(SWAMP, zone=Zone.BATTLEFIELD, owner="p1")
        swamp.tapped = True
        swamp.counters["skip_untap"] = 1

        state = make_two_player_state(p1_cards=[swamp])
        changes = resolver.resolve_untap_step(state)
        # Swamp should NOT untap
        assert swamp.tapped is True
        # Counter should be removed
        assert "skip_untap" not in swamp.counters


# ====================================================================
# Mishra's Factory — animation, attacking, blocking
# ====================================================================

class TestMishrasFactory:
    def test_animate_available_on_opponent_turn(self):
        """Factory can be animated on opponent's turn (to block with it)."""
        resolver = Resolver()
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")

        state = make_two_player_state(p1_cards=[factory])
        state.active_player_index = 1  # opponent's turn
        state.phase = Phase.BEGIN_COMBAT

        legal = resolver.get_legal_actions(state, "p1")
        animate = [a for a in legal if a.choices.get("mode") == "animate"]
        assert len(animate) == 1

    def test_animated_factory_can_block(self):
        """Once animated, Factory shows up as a legal blocker."""
        resolver = Resolver()
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")
        factory.counters["animated"] = 1

        attacker = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p2")
        attacker.sick = False

        state = make_two_player_state(
            p1_cards=[factory],
            p2_cards=[attacker],
        )
        state.combat.attackers = [attacker.id]

        blocks = resolver.get_legal_blocks(state, "p1")
        assert len(blocks) == 1
        assert blocks[0].card_name == "Mishra's Factory"

    def test_animated_factory_can_attack(self):
        """Once animated, Factory shows up as a legal attacker."""
        resolver = Resolver()
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")
        factory.counters["animated"] = 1
        factory.sick = False

        state = make_two_player_state(p1_cards=[factory])
        state.active_player_index = 0
        state.phase = Phase.DECLARE_ATTACKERS

        legal = resolver.get_legal_actions(state, "p1")
        attacks = [a for a in legal if a.type == ActionType.ATTACK]
        assert len(attacks) == 1
        assert attacks[0].card_name == "Mishra's Factory"

    def test_unanimated_factory_cant_block(self):
        """Non-animated Factory is NOT a legal blocker."""
        resolver = Resolver()
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")

        attacker = make_instance(BEAR, zone=Zone.BATTLEFIELD, owner="p2")
        attacker.sick = False

        state = make_two_player_state(
            p1_cards=[factory],
            p2_cards=[attacker],
        )
        state.combat.attackers = [attacker.id]

        blocks = resolver.get_legal_blocks(state, "p1")
        assert len(blocks) == 0

    def test_animated_factory_effective_power(self):
        """Animated Factory has effective power/toughness of 2/2."""
        from eight_rack.game.resolver import _effective_power, _effective_toughness
        factory = make_instance(MISHRAS_FACTORY, zone=Zone.BATTLEFIELD, owner="p1")
        factory.counters["animated"] = 1

        assert _effective_power(factory) == 2
        assert _effective_toughness(factory) == 2
