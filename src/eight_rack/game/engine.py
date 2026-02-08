"""Game engine: main loop, phase management, tier routing."""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Protocol

import yaml

from ..cards.database import CardDatabase
from ..cards.models import CardDefinition
from .actions import Action, ActionResult, ActionType
from .adjudicator import LLMAdjudicator
from .resolver import Resolver
from .state import CardInstance, CombatState, GameState, Phase, PlayerState, StackItem, Zone, PHASE_ORDER

logger = logging.getLogger(__name__)

MAX_TURNS = 50  # Safety limit


class Agent(Protocol):
    """Protocol for game agents (pilots)."""

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action: ...
    def choose_mulligan(self, hand: list[CardInstance], mulligans: int) -> bool: ...
    def choose_cards_to_bottom(self, hand: list[CardInstance], count: int) -> list[str]: ...
    def choose_discard_target(self, state: GameState, opponent_hand: list[CardInstance]) -> str | None: ...
    def choose_discard_from_hand(self, state: GameState, hand: list[CardInstance]) -> str | None: ...
    def choose_sacrifice(self, state: GameState, candidates: list[CardInstance]) -> str | None: ...
    def choose_search_target(self, state: GameState, candidates: list[CardInstance]) -> str | None: ...
    def choose_scry(self, cards: list[CardInstance], count: int) -> dict[str, list[str]] | None: ...


class GameObserver(Protocol):
    """Protocol for observing game events (e.g., visual display)."""

    def on_phase_change(self, state: GameState) -> None: ...
    def on_action(self, state: GameState, action_desc: str) -> None: ...
    def show_result(self, state: GameState) -> None: ...


class GameEngine:
    """Runs a single game of Magic."""

    def __init__(
        self,
        card_db: CardDatabase,
        resolver: Resolver | None = None,
        adjudicator: LLMAdjudicator | None = None,
        observer: GameObserver | None = None,
    ):
        self.card_db = card_db
        self.resolver = resolver or Resolver()
        self.adjudicator = adjudicator
        self.observer = observer

    def build_deck(self, decklist_path: Path) -> list[CardDefinition]:
        """Load a decklist YAML and return card definitions (mainboard only)."""
        with open(decklist_path) as f:
            deck_data = yaml.safe_load(f)

        cards = []
        for entry in deck_data.get("mainboard", []):
            card_def = self.card_db.get(entry["name"])
            if not card_def:
                logger.warning(f"Card not in database: {entry['name']}")
                continue
            for _ in range(entry["quantity"]):
                cards.append(card_def)
        return cards

    def build_sideboard(self, decklist_path: Path) -> list[CardDefinition]:
        """Load a decklist YAML and return sideboard card definitions."""
        with open(decklist_path) as f:
            deck_data = yaml.safe_load(f)

        cards = []
        for entry in deck_data.get("sideboard", []):
            card_def = self.card_db.get(entry["name"])
            if not card_def:
                logger.warning(f"Sideboard card not in database: {entry['name']}")
                continue
            for _ in range(entry["quantity"]):
                cards.append(card_def)
        return cards

    def load_deck_config(self, decklist_path: Path) -> dict:
        """Load raw deck YAML config (for metadata like name, meta_share)."""
        with open(decklist_path) as f:
            return yaml.safe_load(f)

    def create_player(
        self, player_id: str, name: str, deck: list[CardDefinition], starting_life: int = 20
    ) -> PlayerState:
        """Create a player with a shuffled deck."""
        cards = []
        for card_def in deck:
            inst = CardInstance(
                definition=card_def,
                zone=Zone.LIBRARY,
                owner=player_id,
                controller=player_id,
            )
            cards.append(inst)

        # Shuffle library
        random.shuffle(cards)

        return PlayerState(
            id=player_id,
            name=name,
            life=starting_life,
            cards=cards,
        )

    def setup_game(
        self,
        player1: PlayerState,
        player2: PlayerState,
        agent1: Agent,
        agent2: Agent,
    ) -> GameState:
        """Set up a new game: shuffle, mulligan, draw opening hands."""
        state = GameState(players=[player1, player2])

        # Mulligan phase
        for i, (player, agent) in enumerate([(player1, agent1), (player2, agent2)]):
            mulligans = 0
            while True:
                # Draw 7
                for card in player.cards:
                    card.zone = Zone.LIBRARY
                random.shuffle(player.library)
                player.draw(7)

                if mulligans >= 3 or not agent.choose_mulligan(player.hand, mulligans):
                    # Keep - put back cards for mulligan (London mulligan)
                    if mulligans > 0:
                        state.log(f"{player.name} keeps {7 - mulligans} cards (mulled {mulligans})")
                        to_bottom = agent.choose_cards_to_bottom(player.hand, mulligans)
                        for card_id in to_bottom:
                            card = player.find_card(card_id)
                            if card and card.zone == Zone.HAND:
                                card.zone = Zone.LIBRARY
                        random.shuffle(player.library)
                    else:
                        state.log(f"{player.name} keeps 7 cards")
                    break
                mulligans += 1
                state.log(f"{player.name} mulligans to {7 - mulligans}")

        return state

    def _check_leylines(self, state: GameState) -> None:
        """Check for Leyline of the Void in opening hands and put on battlefield for free."""
        for player in state.players:
            for card in player.hand[:]:
                if card.name == "Leyline of the Void":
                    card.zone = Zone.BATTLEFIELD
                    card.controller = player.id
                    state.log(f"{player.name} puts {card.name} onto the battlefield (opening hand)")

    def run_game(
        self,
        state: GameState,
        agents: dict[str, Agent],
    ) -> GameState:
        """Run a game to completion."""
        self._check_leylines(state)
        state.log("Game begins")

        while not state.game_over and state.turn_number <= MAX_TURNS:
            self._run_turn(state, agents)

            # Switch active player
            state.active_player_index = 1 - state.active_player_index
            state.turn_number += 1

        if state.turn_number > MAX_TURNS:
            state.log("Game ended: turn limit reached (draw)")
            state.game_over = True

        if self.observer:
            self.observer.show_result(state)

        return state

    def _run_turn(self, state: GameState, agents: dict[str, Agent]) -> None:
        """Run a single turn through all phases."""
        player = state.active_player
        state.spells_cast_this_turn = 0
        state.log(f"--- {player.name}'s turn {state.turn_number} ---")

        for phase in PHASE_ORDER:
            if state.game_over:
                break

            state.phase = phase
            state.priority_player_index = state.active_player_index

            if self.observer:
                self.observer.on_phase_change(state)

            match phase:
                case Phase.UNTAP:
                    changes = self.resolver.resolve_untap_step(state)
                    for c in changes:
                        state.log(c)
                    player.has_drawn_for_turn = False

                case Phase.UPKEEP:
                    # Use trigger registry if available, else fall back to hardcoded
                    if hasattr(self.resolver, '_trigger_registry') and self.resolver._trigger_registry:
                        from .triggers import TriggerType
                        trigger_items = self.resolver._trigger_registry.check_triggers(
                            state, TriggerType.UPKEEP
                        )
                        for ti in trigger_items:
                            state.stack.append(ti)
                            state.log(f"Trigger: {ti.description}")
                    else:
                        changes = self.resolver.resolve_upkeep_triggers(state)
                        for c in changes:
                            state.log(c)

                    sba = state.check_state_based_actions()
                    for s in sba:
                        state.log(s)
                    if state.game_over:
                        break
                    # Give priority (will resolve stack items)
                    self._priority_loop(state, agents)

                case Phase.DRAW:
                    changes = self.resolver.resolve_draw_step(state)
                    for c in changes:
                        state.log(c)

                    # Advance saga lore counters (after draw step)
                    for card in player.battlefield:
                        if card.definition.is_saga:
                            card.counters["lore"] = card.counters.get("lore", 0) + 1
                            chapter = card.counters["lore"]
                            trigger = self._make_saga_trigger(state, card, chapter)
                            if trigger:
                                state.stack.append(trigger)
                                state.log(f"Saga: {card.name} chapter {chapter}")

                    self._priority_loop(state, agents)

                case Phase.MAIN_1 | Phase.MAIN_2:
                    self._priority_loop(state, agents)

                case Phase.BEGIN_COMBAT:
                    state.combat = CombatState()
                    self._priority_loop(state, agents)

                case Phase.DECLARE_ATTACKERS:
                    self._declare_attackers(state, agents)

                case Phase.DECLARE_BLOCKERS:
                    if state.combat.attackers:
                        self._declare_blockers(state, agents)

                case Phase.COMBAT_DAMAGE:
                    if state.combat.attackers:
                        changes = self.resolver.resolve_combat_damage(state)
                        for c in changes:
                            state.log(c)
                        sba = state.check_state_based_actions()
                        for s in sba:
                            state.log(s)

                case Phase.END_COMBAT:
                    state.combat = CombatState()
                    self._priority_loop(state, agents)

                case Phase.END_STEP:
                    self._priority_loop(state, agents)

                case Phase.CLEANUP:
                    changes = self.resolver.resolve_cleanup_step(state)
                    for c in changes:
                        state.log(c)

    def _priority_loop(self, state: GameState, agents: dict[str, Agent]) -> None:
        """Run priority passes until both players pass with an empty stack."""
        consecutive_passes = 0
        max_actions = 200  # Safety limit per priority loop

        for _ in range(max_actions):
            if state.game_over:
                break

            # Both players passed — check stack
            if consecutive_passes >= 2:
                if state.stack:
                    # Resolve top of stack — pass controller's agent for interactive targeting
                    controller_id = state.stack[-1].controller
                    controller_agent = agents.get(controller_id)
                    result = self.resolver.resolve_top_of_stack(state, agent=controller_agent, agents=agents)
                    if result.success:
                        state.log(f"  Stack resolves: {result.message}")
                        for change in result.state_changes:
                            state.log(f"  -> {change}")
                    else:
                        state.log(f"  Stack resolution FAILED: {result.message}")

                    # Check SBA
                    sba = state.check_state_based_actions()
                    for s in sba:
                        state.log(s)

                    # Reset priority to active player and continue
                    state.priority_player_index = state.active_player_index
                    consecutive_passes = 0
                    continue
                else:
                    # Stack empty, both passed — exit priority
                    break

            current = state.priority_player
            agent = agents[current.id]

            legal = self.resolver.get_legal_actions(state, current.id)
            if not legal:
                break

            action = agent.choose_action(state, legal)
            state.log(str(action))

            if action.type == ActionType.PASS_PRIORITY:
                consecutive_passes += 1
                # Switch priority
                state.priority_player_index = 1 - state.priority_player_index
            else:
                consecutive_passes = 0
                if self.observer:
                    self.observer.on_action(state, str(action))
                result = self._resolve_action(state, action, agents=agents)
                if result.success:
                    for change in result.state_changes:
                        state.log(f"  -> {change}")
                else:
                    state.log(f"  FAILED: {result.message}")

                # Check state-based actions
                sba = state.check_state_based_actions()
                for s in sba:
                    state.log(s)

    def _resolve_action(self, state: GameState, action: Action, agents: dict | None = None) -> ActionResult:
        """Route an action through the appropriate tier."""
        if self.resolver.can_resolve(action):
            return self.resolver.resolve(state, action, agents=agents)
        if self.adjudicator:
            state.log(f"  [Tier 3 LLM adjudication for {action.card_name}]")
            return self.adjudicator.adjudicate(state, action)
        # No adjudicator available - try resolver anyway (it may partially handle it)
        return self.resolver.resolve(state, action)

    def _declare_attackers(self, state: GameState, agents: dict[str, Agent]) -> None:
        """Handle the declare attackers step — creatures are declared, no damage yet."""
        player = state.active_player
        agent = agents[player.id]

        legal = self.resolver.get_legal_actions(state, player.id)
        attack_actions = [a for a in legal if a.type == ActionType.ATTACK]

        if not attack_actions:
            return

        # Let agent declare attackers one at a time
        for _ in range(len(attack_actions) + 1):
            legal = self.resolver.get_legal_actions(state, player.id)
            attacks = [a for a in legal if a.type == ActionType.ATTACK]
            if not attacks:
                break

            action = agent.choose_action(state, attacks + [Action(
                type=ActionType.PASS_PRIORITY,
                player_id=player.id,
                description="Done declaring attackers",
            )])

            if action.type == ActionType.PASS_PRIORITY:
                break

            result = self.resolver.resolve(state, action)
            if result.success:
                state.log(str(action))
                for change in result.state_changes:
                    state.log(f"  -> {change}")

        # After attackers declared, run priority loop for responses (e.g., instants)
        if state.combat.attackers:
            self._priority_loop(state, agents)

    def _declare_blockers(self, state: GameState, agents: dict[str, Agent]) -> None:
        """Handle the declare blockers step — defending player assigns blockers."""
        defending_player = state.non_active_player
        agent = agents[defending_player.id]

        # Let defending player declare blockers
        for _ in range(20):  # Safety limit
            blocks = self.resolver.get_legal_blocks(state, defending_player.id)
            if not blocks:
                break

            action = agent.choose_action(state, blocks + [Action(
                type=ActionType.PASS_PRIORITY,
                player_id=defending_player.id,
                description="Done declaring blockers",
            )])

            if action.type == ActionType.PASS_PRIORITY:
                break

            result = self.resolver.resolve(state, action)
            if result.success:
                state.log(str(action))
                for change in result.state_changes:
                    state.log(f"  -> {change}")

        # Enforce menace: attackers with menace must be blocked by 2+ creatures
        self._enforce_menace(state)

        # After blockers declared, run priority loop for responses
        if state.combat.attackers:
            self._priority_loop(state, agents)

    def _enforce_menace(self, state: GameState) -> None:
        """Remove illegal block assignments on menace attackers (need 2+ blockers)."""
        active_player = state.active_player
        for atk_id in state.combat.attackers:
            attacker = active_player.find_card(atk_id)
            if not attacker:
                continue
            has_menace = "Menace" in attacker.definition.keywords or "menace" in attacker.definition.oracle_text.lower()
            if not has_menace:
                continue
            # Count blockers assigned to this attacker
            blocker_ids = [bid for bid, aid in state.combat.blockers.items() if aid == atk_id]
            if len(blocker_ids) == 1:
                # Only 1 blocker — illegal, remove the block
                del state.combat.blockers[blocker_ids[0]]
                state.log(f"Menace: {attacker.name} can't be blocked by only one creature, block removed")

    def _make_saga_trigger(self, state: GameState, card: CardInstance, chapter: int) -> StackItem | None:
        """Create a StackItem for a saga chapter trigger."""
        if card.name == "Urza's Saga":
            if chapter == 1:
                return StackItem(
                    source_card_id=card.id,
                    source_card_name=card.name,
                    controller=card.controller,
                    description=f"Urza's Saga chapter I: gains '{{T}}: Add {{C}}'",
                    is_ability=True,
                )
            elif chapter == 2:
                return StackItem(
                    source_card_id=card.id,
                    source_card_name=card.name,
                    controller=card.controller,
                    description=f"Urza's Saga chapter II: gains construct-making ability",
                    is_ability=True,
                )
            elif chapter == 3:
                return StackItem(
                    source_card_id=card.id,
                    source_card_name=card.name,
                    controller=card.controller,
                    description=f"Urza's Saga chapter III: search for artifact with CMC 0 or 1",
                    is_ability=True,
                    action_data={"type": "activate_ability", "player_id": card.controller,
                                 "card_id": card.id, "card_name": card.name,
                                 "choices": {"mode": "saga_chapter_3"}},
                )
        # Generic saga support (no-op trigger)
        return StackItem(
            source_card_id=card.id,
            source_card_name=card.name,
            controller=card.controller,
            description=f"{card.name} chapter {chapter}",
            is_ability=True,
        )
