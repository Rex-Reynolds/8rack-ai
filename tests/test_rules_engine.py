"""Tests for rules engine overhaul: stack, triggers, combat, fetchlands."""

import pytest

from eight_rack.cards.models import CardDefinition, CardType, Color
from eight_rack.game.state import (
    CardInstance, CombatState, GameState, ManaPool, Phase, PlayerState, StackItem, Zone,
)
from eight_rack.game.actions import Action, ActionResult, ActionType
from eight_rack.game.resolver import Resolver, FETCH_TARGETS
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


SWAMP = make_card("Swamp")
MOUNTAIN = make_card("Mountain")
PLAINS = make_card("Plains")
FOREST = make_card("Forest")
ISLAND = make_card("Island")

THE_RACK = make_card(
    "The Rack", mana_cost="{1}", cmc=1.0, type_line="Artifact",
    oracle_text="At the beginning of each opponent's upkeep, The Rack deals X damage.",
    card_types=[CardType.ARTIFACT],
)
SHRIEKING = make_card(
    "Shrieking Affliction", mana_cost="{B}", cmc=1.0, type_line="Enchantment",
    card_types=[CardType.ENCHANTMENT],
)

LIGHTNING_BOLT = make_card(
    "Lightning Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
    oracle_text="Deal 3 damage to any target.", card_types=[CardType.INSTANT],
)
FATAL_PUSH = make_card(
    "Fatal Push", mana_cost="{B}", cmc=1.0, type_line="Instant",
    oracle_text="Destroy target creature with CMC <= 2.", card_types=[CardType.INSTANT],
)

GRIZZLY_BEARS = make_card(
    "Grizzly Bears", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
    card_types=[CardType.CREATURE], power="2", toughness="2",
)
SERRA_ANGEL = make_card(
    "Serra Angel", mana_cost="{3}{W}{W}", cmc=5.0, type_line="Creature — Angel",
    card_types=[CardType.CREATURE], power="4", toughness="4",
    keywords=["Flying", "Vigilance"],
)
GOBLIN_GUIDE = make_card(
    "Goblin Guide", mana_cost="{R}", cmc=1.0, type_line="Creature — Goblin Scout",
    card_types=[CardType.CREATURE], power="2", toughness="2",
    keywords=["Haste"],
)
BANESLAYER = make_card(
    "Baneslayer Angel", mana_cost="{3}{W}{W}", cmc=5.0, type_line="Creature — Angel",
    card_types=[CardType.CREATURE], power="5", toughness="5",
    keywords=["Flying", "First Strike", "Lifelink"],
)
DEATHTOUCHER = make_card(
    "Gifted Aetherborn", mana_cost="{B}{B}", cmc=2.0, type_line="Creature — Aetherborn Vampire",
    card_types=[CardType.CREATURE], power="2", toughness="3",
    keywords=["Deathtouch", "Lifelink"],
)
TRAMPLER = make_card(
    "Colossal Dreadmaw", mana_cost="{4}{G}{G}", cmc=6.0, type_line="Creature — Dinosaur",
    card_types=[CardType.CREATURE], power="6", toughness="6",
    keywords=["Trample"],
)
INDESTRUCTIBLE_GUY = make_card(
    "Darksteel Colossus", mana_cost="{11}", cmc=11.0, type_line="Artifact Creature — Golem",
    card_types=[CardType.ARTIFACT, CardType.CREATURE], power="11", toughness="11",
    keywords=["Indestructible", "Trample"],
)
FIRST_STRIKER = make_card(
    "Boros Elite", mana_cost="{W}", cmc=1.0, type_line="Creature — Human Soldier",
    card_types=[CardType.CREATURE], power="3", toughness="1",
    keywords=["First Strike"],
)
SMALL_CREATURE = make_card(
    "Scathe Zombies", mana_cost="{2}{B}", cmc=3.0, type_line="Creature — Zombie",
    card_types=[CardType.CREATURE], power="2", toughness="2",
)
FLYING_CREATURE = make_card(
    "Storm Crow", mana_cost="{1}{U}", cmc=2.0, type_line="Creature — Bird",
    card_types=[CardType.CREATURE], power="1", toughness="1",
    keywords=["Flying"],
)
REACH_CREATURE = make_card(
    "Nessian Hornbeetle", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Insect",
    card_types=[CardType.CREATURE], power="2", toughness="2",
    keywords=["Reach"],
)
BLOODSTAINED_MIRE = make_card(
    "Bloodstained Mire", type_line="Land", card_types=[CardType.LAND],
    oracle_text="{T}, Pay 1 life, Sacrifice Bloodstained Mire: Search your library for a Swamp or Mountain card.",
)
BLOOD_CRYPT = make_card(
    "Blood Crypt", type_line="Land — Swamp Mountain", card_types=[CardType.LAND],
    oracle_text="{T}: Add {B} or {R}.",
)
DOUBLE_STRIKER = make_card(
    "Fencing Ace", mana_cost="{1}{W}", cmc=2.0, type_line="Creature — Human Soldier",
    card_types=[CardType.CREATURE], power="1", toughness="1",
    keywords=["Double Strike"],
)


def make_two_player_state(**kwargs) -> GameState:
    """Create a game state with two empty players."""
    return GameState(players=[
        PlayerState(id="p1", name="Player 1", cards=kwargs.get("p1_cards", [])),
        PlayerState(id="p2", name="Player 2", cards=kwargs.get("p2_cards", [])),
    ])


# =========================================================================
# STACK TESTS
# =========================================================================

class TestSpellStack:
    def test_spell_goes_on_stack(self):
        """Casting a spell puts it on the stack, not immediately resolved."""
        state = make_two_player_state(
            p2_cards=[
                make_instance(LIGHTNING_BOLT, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ],
        )
        resolver = Resolver()
        bolt = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL, player_id="p2",
            card_id=bolt.id, card_name="Lightning Bolt",
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert bolt.zone == Zone.STACK
        assert len(state.stack) == 1
        assert state.stack[0].source_card_name == "Lightning Bolt"
        # Opponent life unchanged until resolution
        assert state.players[0].life == 20

    def test_both_pass_resolves_stack(self):
        """When both players pass, the top of stack resolves."""
        state = make_two_player_state(
            p2_cards=[
                make_instance(LIGHTNING_BOLT, Zone.HAND, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ],
        )
        resolver = Resolver()
        bolt = state.players[1].hand[0]
        action = Action(
            type=ActionType.CAST_SPELL, player_id="p2",
            card_id=bolt.id, card_name="Lightning Bolt",
        )
        resolver.resolve(state, action)
        # Now resolve the stack
        result = resolver.resolve_top_of_stack(state)
        assert result.success
        assert state.players[0].life == 17  # Bolt dealt 3
        assert bolt.zone == Zone.GRAVEYARD
        assert len(state.stack) == 0

    def test_lifo_stack_order(self):
        """Spells resolve in LIFO order (last in, first out)."""
        state = make_two_player_state(
            p2_cards=[
                make_instance(LIGHTNING_BOLT, Zone.HAND, "p2"),
                make_instance(
                    make_card("Shock", mana_cost="{R}", cmc=1.0, type_line="Instant",
                              oracle_text="Deal 2 damage.", card_types=[CardType.INSTANT]),
                    Zone.HAND, "p2",
                ),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
                make_instance(MOUNTAIN, Zone.BATTLEFIELD, "p2"),
            ],
        )
        resolver = Resolver()
        bolt = state.players[1].hand[0]
        shock = state.players[1].hand[1]

        # Cast bolt first
        resolver.resolve(state, Action(
            type=ActionType.CAST_SPELL, player_id="p2",
            card_id=bolt.id, card_name="Lightning Bolt",
        ))
        # Cast shock second (on top of bolt)
        resolver.resolve(state, Action(
            type=ActionType.CAST_SPELL, player_id="p2",
            card_id=shock.id, card_name="Shock",
        ))

        assert len(state.stack) == 2
        # Top of stack should be Shock (last in)
        assert state.stack[-1].source_card_name == "Shock"

        # Resolve top: Shock first
        resolver.resolve_top_of_stack(state)
        assert len(state.stack) == 1
        # Bolt still on stack
        assert state.stack[0].source_card_name == "Lightning Bolt"

    def test_instant_response_on_stack(self):
        """An instant can be cast in response to a spell on the stack."""
        state = make_two_player_state(
            p1_cards=[
                make_instance(FATAL_PUSH, Zone.HAND, "p1"),
                make_instance(SWAMP, Zone.BATTLEFIELD, "p1"),
            ],
            p2_cards=[
                make_instance(GRIZZLY_BEARS, Zone.HAND, "p2"),
                make_instance(FOREST, Zone.BATTLEFIELD, "p2"),
                make_instance(FOREST, Zone.BATTLEFIELD, "p2"),
            ],
        )
        resolver = Resolver()

        # P2 casts bears
        bears = state.players[1].hand[0]
        resolver.resolve(state, Action(
            type=ActionType.CAST_SPELL, player_id="p2",
            card_id=bears.id, card_name="Grizzly Bears",
        ))
        assert len(state.stack) == 1

        # P1 responds with Fatal Push (targeting something else in this case)
        push = state.players[0].hand[0]
        resolver.resolve(state, Action(
            type=ActionType.CAST_SPELL, player_id="p1",
            card_id=push.id, card_name="Fatal Push",
        ))
        assert len(state.stack) == 2

        # Fatal Push on top, Bears below
        assert state.stack[-1].source_card_name == "Fatal Push"
        assert state.stack[0].source_card_name == "Grizzly Bears"


# =========================================================================
# TRIGGER TESTS
# =========================================================================

class TestTriggers:
    def test_upkeep_triggers_on_stack(self):
        """Upkeep triggers create StackItems instead of resolving immediately."""
        registry = TriggerRegistry()
        rack = make_instance(THE_RACK, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[rack])
        state.active_player_index = 1  # It's p2's turn (opponent of rack controller)

        items = registry.check_triggers(state, TriggerType.UPKEEP)
        assert len(items) == 1
        assert items[0].source_card_name == "The Rack"
        assert items[0].is_ability

    def test_shrieking_trigger_fires(self):
        """Shrieking Affliction triggers when opponent has <= 1 card."""
        registry = TriggerRegistry()
        sa = make_instance(SHRIEKING, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[sa])
        state.active_player_index = 1  # opponent's upkeep

        items = registry.check_triggers(state, TriggerType.UPKEEP)
        assert len(items) == 1
        assert items[0].source_card_name == "Shrieking Affliction"

    def test_shrieking_no_trigger_with_cards(self):
        """Shrieking Affliction doesn't trigger if opponent has > 1 card."""
        registry = TriggerRegistry()
        sa = make_instance(SHRIEKING, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(
            p1_cards=[sa],
            p2_cards=[
                make_instance(SWAMP, Zone.HAND, "p2"),
                make_instance(SWAMP, Zone.HAND, "p2"),
            ],
        )
        state.active_player_index = 1

        items = registry.check_triggers(state, TriggerType.UPKEEP)
        assert len(items) == 0

    def test_rack_trigger_resolves_via_stack(self):
        """The Rack trigger resolves and deals damage when popped from stack."""
        registry = TriggerRegistry()
        resolver = Resolver(trigger_registry=registry)

        rack = make_instance(THE_RACK, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[rack])
        state.active_player_index = 1  # p2's upkeep

        items = registry.check_triggers(state, TriggerType.UPKEEP)
        assert len(items) == 1
        state.stack.append(items[0])

        result = resolver.resolve_top_of_stack(state)
        assert result.success
        assert state.players[1].life == 17  # 3 damage (empty hand)

    def test_etb_trigger_fires(self):
        """ETB triggers fire when a permanent enters the battlefield."""
        registry = TriggerRegistry()
        bowmasters_def = make_card(
            "Orcish Bowmasters", mana_cost="{1}{B}", cmc=2.0,
            type_line="Creature — Orc Archer", card_types=[CardType.CREATURE],
            power="1", toughness="1",
        )
        bm = make_instance(bowmasters_def, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[bm])

        items = registry.check_triggers(state, TriggerType.ETB, source_card=bm)
        assert len(items) == 1
        assert items[0].source_card_name == "Orcish Bowmasters"


# =========================================================================
# COMBAT TESTS
# =========================================================================

class TestCombat:
    def test_unblocked_damage(self):
        """Unblocked attacker deals full damage to defending player."""
        bear = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")
        bear.sick = False
        state = make_two_player_state(p1_cards=[bear])
        state.combat.attackers.append(bear.id)

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        assert state.players[1].life == 18  # 2 damage from 2/2

    def test_blocked_damage(self):
        """Blocked attacker deals damage to blocker, not player."""
        attacker = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")
        attacker.sick = False
        blocker = make_instance(SMALL_CREATURE, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p1_cards=[attacker], p2_cards=[blocker])
        state.combat.attackers.append(attacker.id)
        state.combat.blockers[blocker.id] = attacker.id

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Player takes no damage (blocked)
        assert state.players[1].life == 20
        # Both creatures deal damage to each other
        assert attacker.damage_marked == 2  # 2/2 blocker
        assert blocker.damage_marked == 2  # 2/2 attacker

    def test_flying_cant_be_blocked_by_ground(self):
        """Flying creature can't be blocked by ground creature."""
        flyer = make_instance(FLYING_CREATURE, Zone.BATTLEFIELD, "p1")
        ground = make_instance(SMALL_CREATURE, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p1_cards=[flyer], p2_cards=[ground])
        state.combat.attackers.append(flyer.id)

        resolver = Resolver()
        blocks = resolver.get_legal_blocks(state, "p2")
        # Ground creature can't block flyer
        assert len(blocks) == 0

    def test_reach_can_block_flying(self):
        """Reach creature can block flying creature."""
        flyer = make_instance(FLYING_CREATURE, Zone.BATTLEFIELD, "p1")
        reacher = make_instance(REACH_CREATURE, Zone.BATTLEFIELD, "p2")

        state = make_two_player_state(p1_cards=[flyer], p2_cards=[reacher])
        state.combat.attackers.append(flyer.id)

        resolver = Resolver()
        blocks = resolver.get_legal_blocks(state, "p2")
        assert len(blocks) == 1
        assert blocks[0].card_name == "Nessian Hornbeetle"

    def test_first_strike_kills_before_regular(self):
        """First strike creature deals damage first, may kill before taking damage."""
        fs = make_instance(FIRST_STRIKER, Zone.BATTLEFIELD, "p1")  # 3/1 first strike
        fs.sick = False
        blocker = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p2")  # 2/2

        state = make_two_player_state(p1_cards=[fs], p2_cards=[blocker])
        state.combat.attackers.append(fs.id)
        state.combat.blockers[blocker.id] = fs.id

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        state.check_state_based_actions()

        # First strike 3 damage kills 2/2 blocker
        assert blocker.zone == Zone.GRAVEYARD
        # First striker survives if blocker died in first strike step
        # (SBA runs between first strike and regular damage)
        assert fs.zone == Zone.BATTLEFIELD

    def test_trample_excess_damage(self):
        """Trample creature deals excess damage to defending player."""
        trampler = make_instance(TRAMPLER, Zone.BATTLEFIELD, "p1")  # 6/6 trample
        trampler.sick = False
        blocker = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p2")  # 2/2

        state = make_two_player_state(p1_cards=[trampler], p2_cards=[blocker])
        state.combat.attackers.append(trampler.id)
        state.combat.blockers[blocker.id] = trampler.id

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # 2 damage to kill 2/2 blocker, 4 tramples through
        assert state.players[1].life == 16

    def test_lifelink(self):
        """Lifelink creature's controller gains life equal to damage dealt."""
        angel = make_instance(BANESLAYER, Zone.BATTLEFIELD, "p1")  # 5/5 flying first strike lifelink
        angel.sick = False
        state = make_two_player_state(p1_cards=[angel])
        state.players[0].life = 10
        state.combat.attackers.append(angel.id)

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Deals 5 to opponent
        assert state.players[1].life == 15
        # Gains 5 life
        assert state.players[0].life == 15

    def test_vigilance_no_tap(self):
        """Vigilance creature doesn't tap when attacking."""
        angel = make_instance(SERRA_ANGEL, Zone.BATTLEFIELD, "p1")  # 4/4 vigilance
        angel.sick = False
        state = make_two_player_state(p1_cards=[angel])
        state.phase = Phase.DECLARE_ATTACKERS

        resolver = Resolver()
        action = Action(
            type=ActionType.ATTACK, player_id="p1",
            card_id=angel.id, card_name="Serra Angel",
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert not angel.tapped  # Vigilance!

    def test_haste_attacks_through_sickness(self):
        """Haste creature can attack even with summoning sickness."""
        goblin = make_instance(GOBLIN_GUIDE, Zone.BATTLEFIELD, "p1")
        goblin.sick = True  # just entered
        state = make_two_player_state(p1_cards=[goblin])
        state.phase = Phase.DECLARE_ATTACKERS

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")
        attacks = [a for a in legal if a.type == ActionType.ATTACK]
        assert len(attacks) == 1
        assert attacks[0].card_name == "Goblin Guide"

    def test_summoning_sick_cant_attack_without_haste(self):
        """Creatures with summoning sickness can't attack without haste."""
        bear = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")
        bear.sick = True
        state = make_two_player_state(p1_cards=[bear])
        state.phase = Phase.DECLARE_ATTACKERS

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")
        attacks = [a for a in legal if a.type == ActionType.ATTACK]
        assert len(attacks) == 0

    def test_indestructible_survives_damage(self):
        """Indestructible creature survives lethal damage."""
        indestructible = make_instance(INDESTRUCTIBLE_GUY, Zone.BATTLEFIELD, "p1")
        indestructible.damage_marked = 100  # massive damage

        state = make_two_player_state(p1_cards=[indestructible])
        sba = state.check_state_based_actions()
        assert indestructible.zone == Zone.BATTLEFIELD  # survives!

    def test_deathtouch_kills_with_any_damage(self):
        """Deathtouch creature kills any creature it damages."""
        dt = make_instance(DEATHTOUCHER, Zone.BATTLEFIELD, "p1")  # 2/3 deathtouch
        dt.sick = False
        big_creature = make_instance(TRAMPLER, Zone.BATTLEFIELD, "p2")  # 6/6

        state = make_two_player_state(p1_cards=[dt], p2_cards=[big_creature])
        state.combat.attackers.append(dt.id)
        state.combat.blockers[big_creature.id] = dt.id

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Deathtouch assigns only 1 damage to kill
        assert big_creature.counters.get("deathtouch_damage") == 1
        # SBA should kill the big creature
        sba = state.check_state_based_actions()
        assert big_creature.zone == Zone.GRAVEYARD

    def test_double_strike_deals_damage_twice(self):
        """Double strike creature deals damage in both first strike and regular steps."""
        ds = make_instance(DOUBLE_STRIKER, Zone.BATTLEFIELD, "p1")  # 1/1 double strike
        ds.sick = False
        state = make_two_player_state(p1_cards=[ds])
        state.combat.attackers.append(ds.id)

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Double strike deals 1 in first strike + 1 in regular = 2 total
        assert state.players[1].life == 18


# =========================================================================
# FETCHLAND TESTS
# =========================================================================

class TestFetchlands:
    def test_find_basic_land(self):
        """Fetchland finds a basic land from library."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        swamp = make_instance(SWAMP, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[mire, swamp])
        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=mire.id, card_name="Bloodstained Mire",
            choices={"mode": "fetch"},
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert mire.zone == Zone.GRAVEYARD  # sacrificed
        assert swamp.zone == Zone.BATTLEFIELD  # found and put on battlefield
        assert state.players[0].life == 19  # paid 1 life

    def test_find_shock_land(self):
        """Fetchland can find a shock land with the right basic type."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        crypt = make_instance(BLOOD_CRYPT, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[mire, crypt])
        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=mire.id, card_name="Bloodstained Mire",
            choices={"mode": "fetch"},
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert crypt.zone == Zone.BATTLEFIELD

    def test_pay_1_life(self):
        """Cracking a fetchland costs 1 life."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        swamp = make_instance(SWAMP, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[mire, swamp])
        state.players[0].life = 5
        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=mire.id, card_name="Bloodstained Mire",
            choices={"mode": "fetch"},
        )
        resolver.resolve(state, action)
        assert state.players[0].life == 4

    def test_sacrifice_fetch(self):
        """Fetchland is sacrificed when activated."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[mire])
        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=mire.id, card_name="Bloodstained Mire",
            choices={"mode": "fetch"},
        )
        resolver.resolve(state, action)
        assert mire.zone == Zone.GRAVEYARD

    def test_no_valid_target(self):
        """Fetchland still sacrifices and costs life even with no valid target."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        # Library only has an Island (Bloodstained Mire can't find Islands)
        island = make_instance(ISLAND, Zone.LIBRARY, "p1")

        state = make_two_player_state(p1_cards=[mire, island])
        resolver = Resolver()

        action = Action(
            type=ActionType.ACTIVATE_ABILITY, player_id="p1",
            card_id=mire.id, card_name="Bloodstained Mire",
            choices={"mode": "fetch"},
        )
        result = resolver.resolve(state, action)
        assert result.success
        assert mire.zone == Zone.GRAVEYARD  # still sacrificed
        assert state.players[0].life == 19  # still paid 1 life
        assert island.zone == Zone.LIBRARY  # island stays in library

    def test_fetchlands_dont_produce_mana(self):
        """Fetchlands should not produce mana (they sacrifice instead)."""
        resolver = Resolver()
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[mire])
        mana = resolver._get_land_mana(mire, state)
        assert mana == {}

    def test_fetch_appears_in_legal_actions(self):
        """Untapped fetchlands should show up as legal actions."""
        mire = make_instance(BLOODSTAINED_MIRE, Zone.BATTLEFIELD, "p1")
        state = make_two_player_state(p1_cards=[mire])
        state.phase = Phase.MAIN_1

        resolver = Resolver()
        legal = resolver.get_legal_actions(state, "p1")
        fetch_actions = [a for a in legal if a.type == ActionType.ACTIVATE_ABILITY and "fetch" in str(a.choices)]
        assert len(fetch_actions) == 1


# =========================================================================
# EFFECTIVE P/T WITH +1/+1 COUNTERS
# =========================================================================

class TestEffectivePowerToughness:
    def test_creature_with_p1p1_deals_extra_combat_damage(self):
        """A creature with +1/+1 counters deals damage based on effective power."""
        bear = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")  # base 2/2
        bear.sick = False
        bear.counters["p1p1"] = 2  # now effectively 4/4

        state = make_two_player_state(p1_cards=[bear])
        state.combat.attackers.append(bear.id)

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Should deal 4 damage (2 base + 2 from counters), not 2
        assert state.players[1].life == 16

    def test_blocker_with_p1p1_deals_extra_damage(self):
        """A blocker with +1/+1 counters deals damage based on effective power."""
        attacker = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")  # 2/2
        attacker.sick = False
        blocker = make_instance(SMALL_CREATURE, Zone.BATTLEFIELD, "p2")  # base 2/2
        blocker.counters["p1p1"] = 3  # effectively 5/5

        state = make_two_player_state(p1_cards=[attacker], p2_cards=[blocker])
        state.combat.attackers.append(attacker.id)
        state.combat.blockers[blocker.id] = attacker.id

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Blocker should deal 5 damage to attacker (2 base + 3 counters)
        assert attacker.damage_marked == 5
        # Player takes no damage (blocked)
        assert state.players[1].life == 20

    def test_zero_base_token_with_p1p1_deals_damage(self):
        """A 0/0 token with +1/+1 counters deals damage based on counters."""
        # Simulate an Orc Army token (0/0 with p1p1 counters)
        orc_def = make_card(
            "Orc Army", mana_cost="", cmc=0.0, type_line="Creature Token — Orc Army",
            card_types=[CardType.CREATURE], power="0", toughness="0",
        )
        orc = make_instance(orc_def, Zone.BATTLEFIELD, "p1")
        orc.sick = False
        orc.counters["p1p1"] = 3  # effectively 3/3

        state = make_two_player_state(p1_cards=[orc])
        state.combat.attackers.append(orc.id)

        resolver = Resolver()
        changes = resolver.resolve_combat_damage(state)
        # Should deal 3 damage (0 base + 3 from counters)
        assert state.players[1].life == 17

    def test_ensnaring_bridge_uses_effective_power(self):
        """Ensnaring Bridge check uses effective power (base + counters)."""
        bridge_def = make_card(
            "Ensnaring Bridge", mana_cost="{3}", cmc=3.0, type_line="Artifact",
            card_types=[CardType.ARTIFACT],
            oracle_text="Creatures with power greater than the number of cards in your hand can't attack.",
        )
        bridge = make_instance(bridge_def, Zone.BATTLEFIELD, "p1")

        # 1/1 creature with 2 p1p1 counters = effective 3 power
        small = make_instance(FLYING_CREATURE, Zone.BATTLEFIELD, "p1")  # 1/1
        small.sick = False
        small.counters["p1p1"] = 2  # effectively 3/3

        # Give player 2 cards in hand → creatures with power > 2 can't attack
        hand1 = make_instance(SWAMP, Zone.HAND, "p1")
        hand2 = make_instance(SWAMP, Zone.HAND, "p1")

        state = make_two_player_state(p1_cards=[bridge, small, hand1, hand2])
        state.phase = Phase.DECLARE_ATTACKERS

        resolver = Resolver()
        actions = resolver.get_legal_actions(state, "p1")
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        # Effective power 3 > hand size 2, so can't attack
        assert len(attack_actions) == 0

    def test_attack_description_shows_effective_pt(self):
        """Attack action description shows effective P/T, not base."""
        bear = make_instance(GRIZZLY_BEARS, Zone.BATTLEFIELD, "p1")  # base 2/2
        bear.sick = False
        bear.counters["p1p1"] = 1  # effectively 3/3

        state = make_two_player_state(p1_cards=[bear])
        state.phase = Phase.DECLARE_ATTACKERS

        resolver = Resolver()
        actions = resolver.get_legal_actions(state, "p1")
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        assert len(attack_actions) == 1
        assert "(3/3)" in attack_actions[0].description
