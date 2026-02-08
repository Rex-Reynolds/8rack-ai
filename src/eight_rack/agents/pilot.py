"""8 Rack pilot agents: deterministic fast-path and LLM hybrid."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ..game.actions import Action, ActionType
from ..game.state import CardInstance, GameState, Phase, VisibleGameState

logger = logging.getLogger(__name__)

STRATEGY_PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "config" / "prompts" / "eight_rack_pilot.md"

# Priority order for casting spells
CAST_PRIORITY = [
    # Rack effects first (win condition)
    "The Rack",
    "Shrieking Affliction",
    # Targeted discard (take best card)
    "Thoughtseize",
    "Inquisition of Kozilek",
    # Recurring/mass discard
    "Raven's Crime",
    "Wrench Mind",
    "Funeral Charm",
    # Threats
    "Orcish Bowmasters",
    "Liliana of the Veil",
    # Removal
    "Fatal Push",
    "Bloodchief's Thirst",
    "Sheoldred's Edict",
    # Utility
    "Smallpox",
    "Nihil Spellbomb",
    "Ensnaring Bridge",
]

# Actions the deterministic pilot handles confidently
HEURISTIC_ACTIONS = {
    ActionType.PLAY_LAND,
    ActionType.PASS_PRIORITY,
    ActionType.ATTACK,
    ActionType.BLOCK,
}


class ActionChoice(BaseModel):
    """Structured LLM response for choosing a game action."""

    action_index: int = Field(description="Index of the chosen action from the legal actions list (0-based)")
    reasoning: str = Field(description="Brief explanation of why this action was chosen")


class MulliganDecision(BaseModel):
    """Structured LLM response for mulligan decisions."""

    keep: bool = Field(description="True to keep the hand, False to mulligan")
    reasoning: str = Field(description="Brief explanation of the mulligan decision")


class DiscardChoice(BaseModel):
    """Structured LLM response for choosing a discard target."""

    card_index: int = Field(description="Index of the card to make the opponent discard (0-based)")
    reasoning: str = Field(description="Brief explanation of why this card was chosen")


class DeterministicPilot:
    """A simple heuristic-based 8 Rack pilot.

    Follows a fixed priority order. No LLM calls.
    Good enough for goldfish testing and fast-path decisions.
    """

    @property
    def name(self) -> str:
        return "8 Rack Pilot (Deterministic)"

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return candidates[0].id if candidates else None

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        return _heuristic_cards_to_bottom(hand, count)

    def choose_mulligan(self, hand: list[str], mulligans: int) -> bool:
        if mulligans >= 2:
            return False
        lands = sum(1 for c in hand if _is_land(c))
        discard_spells = sum(1 for c in hand if _is_discard(c))
        racks = sum(1 for c in hand if c in ("The Rack", "Shrieking Affliction"))
        if lands < 1 or lands > 5:
            return True
        if discard_spells == 0 and racks == 0:
            return True
        return False

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        return _heuristic_choose_action(state, legal_actions)

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        return _heuristic_discard_target(opponent_hand)

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        return _heuristic_discard_from_hand(hand)

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return _heuristic_sacrifice(candidates)


class HybridPilot:
    """Hybrid 8 Rack pilot: heuristic fast-path + LLM for complex decisions.

    Uses deterministic heuristics for simple decisions (play land, attack, pass).
    Falls back to LLM when the decision is non-trivial:
    - Multiple castable spells with different strategic implications
    - Discard target selection from opponent's hand
    - Complex board states with multiple viable lines
    """

    def __init__(self, llm_client, model: str = "sonnet", confidence_threshold: float = 0.85):
        from ..llm.client import LLMClient
        self._llm: LLMClient = llm_client
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._system_prompt: str | None = None
        self.llm_calls = 0
        self.heuristic_calls = 0

    @property
    def name(self) -> str:
        return "8 Rack Pilot (Hybrid)"

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            if STRATEGY_PROMPT_PATH.exists():
                self._system_prompt = STRATEGY_PROMPT_PATH.read_text()
            else:
                self._system_prompt = (
                    "You are piloting an 8 Rack deck in Modern MTG. "
                    "Your goal is to empty the opponent's hand and win with rack damage."
                )
        return self._system_prompt

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        return _heuristic_cards_to_bottom(hand, count)

    def choose_mulligan(self, hand: list[str], mulligans: int) -> bool:
        """Use heuristics for clear keeps/mulls, LLM for borderline hands."""
        if mulligans >= 2:
            return False

        lands = sum(1 for c in hand if _is_land(c))
        discard_spells = sum(1 for c in hand if _is_discard(c))
        racks = sum(1 for c in hand if c in ("The Rack", "Shrieking Affliction"))

        # Clear keeps
        if 2 <= lands <= 3 and discard_spells >= 1 and racks >= 1:
            self.heuristic_calls += 1
            return False
        # Clear mulls
        if lands == 0 or lands >= 6:
            self.heuristic_calls += 1
            return True

        # Borderline - ask LLM
        return self._llm_mulligan(hand, mulligans)

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Heuristic fast path for simple decisions, LLM for complex ones."""
        if not legal_actions:
            return Action(type=ActionType.PASS_PRIORITY, player_id="")

        # Only pass available
        if len(legal_actions) == 1:
            self.heuristic_calls += 1
            return legal_actions[0]

        non_pass = [a for a in legal_actions if a.type != ActionType.PASS_PRIORITY]

        # Simple decision: only one real option
        if len(non_pass) <= 1:
            self.heuristic_calls += 1
            return non_pass[0] if non_pass else legal_actions[0]

        # All actions are simple types (land, attack) - use heuristics
        if all(a.type in HEURISTIC_ACTIONS for a in legal_actions):
            self.heuristic_calls += 1
            return _heuristic_choose_action(state, legal_actions)

        # Only one type of non-trivial action - use heuristics
        cast_actions = [a for a in legal_actions if a.type == ActionType.CAST_SPELL]
        if len(cast_actions) <= 1 and not any(
            a.type == ActionType.ACTIVATE_ABILITY for a in legal_actions
        ):
            self.heuristic_calls += 1
            return _heuristic_choose_action(state, legal_actions)

        # Complex decision: multiple spells/abilities to choose from - use LLM
        return self._llm_choose_action(state, legal_actions)

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return candidates[0].id if candidates else None

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        """Always use LLM for discard targeting (high-value decision)."""
        if not opponent_hand:
            return None
        if len(opponent_hand) == 1:
            self.heuristic_calls += 1
            return opponent_hand[0].id

        return self._llm_discard_target(state, opponent_hand)

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        return _heuristic_discard_from_hand(hand)

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return _heuristic_sacrifice(candidates)

    def _llm_mulligan(self, hand: list[str], mulligans: int) -> bool:
        self.llm_calls += 1
        prompt = (
            f"Mulligan #{mulligans + 1}. Hand ({7 - mulligans} cards): {', '.join(hand)}\n\n"
            f"Should we keep or mulligan? Consider land count, spell mix, "
            f"and whether we have a path to getting racks online with disruption."
        )
        try:
            result = self._llm.query(
                response_model=MulliganDecision,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=300,
            )
            logger.debug(f"LLM mulligan: {'keep' if result.keep else 'mull'} - {result.reasoning}")
            return not result.keep
        except Exception as e:
            logger.warning(f"LLM mulligan failed, falling back to heuristic: {e}")
            return DeterministicPilot().choose_mulligan(hand, mulligans)

    def _llm_choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        self.llm_calls += 1
        player_id = legal_actions[0].player_id
        visible = VisibleGameState.from_game_state(state, player_id)

        # Format actions for LLM
        action_list = "\n".join(
            f"  [{i}] {a.description or str(a)}" for i, a in enumerate(legal_actions)
        )

        prompt = (
            f"## Game State\n"
            f"Turn {visible.turn_number}, Phase: {visible.phase.value}\n"
            f"Your life: {visible.viewer_life} | Opponent life: {visible.opponent_life}\n"
            f"Your hand: {', '.join(visible.viewer_hand)}\n"
            f"Your board: {_format_board(visible.viewer_battlefield)}\n"
            f"Opponent hand size: {visible.opponent_hand_size}\n"
            f"Opponent board: {_format_board(visible.opponent_battlefield)}\n"
            f"Mana available: {_format_mana(visible.viewer_mana_pool)}\n"
            f"Land drops remaining: {visible.viewer_land_drops}\n\n"
            f"## Legal Actions\n{action_list}\n\n"
            f"Choose the best action by index. Consider the current game phase, "
            f"available mana, and our win condition (empty opponent's hand + rack damage)."
        )

        try:
            result = self._llm.query(
                response_model=ActionChoice,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=400,
            )
            idx = max(0, min(result.action_index, len(legal_actions) - 1))
            logger.debug(f"LLM action: [{idx}] {legal_actions[idx]} - {result.reasoning}")
            return legal_actions[idx]
        except Exception as e:
            logger.warning(f"LLM action choice failed, falling back to heuristic: {e}")
            return _heuristic_choose_action(state, legal_actions)

    def _llm_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        self.llm_calls += 1
        player = state.active_player
        visible = VisibleGameState.from_game_state(state, player.id)

        card_list = "\n".join(
            f"  [{i}] {c.name} ({c.definition.type_line}, CMC {c.definition.cmc})"
            for i, c in enumerate(opponent_hand)
        )

        prompt = (
            f"## Discard Target Selection\n"
            f"Opponent's hand:\n{card_list}\n\n"
            f"Your board: {_format_board(visible.viewer_battlefield)}\n"
            f"Opponent board: {_format_board(visible.opponent_battlefield)}\n"
            f"Opponent life: {visible.opponent_life}\n\n"
            f"Choose which card the opponent should discard. Consider:\n"
            f"- Which card is most dangerous if resolved?\n"
            f"- Which card generates the most value?\n"
            f"- Are there cards that beat our lock (racks + empty hand)?"
        )

        try:
            result = self._llm.query(
                response_model=DiscardChoice,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=300,
            )
            idx = max(0, min(result.card_index, len(opponent_hand) - 1))
            logger.debug(f"LLM discard target: {opponent_hand[idx].name} - {result.reasoning}")
            return opponent_hand[idx].id
        except Exception as e:
            logger.warning(f"LLM discard target failed, falling back to heuristic: {e}")
            return _heuristic_discard_target(opponent_hand)

    @property
    def usage_summary(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "heuristic_calls": self.heuristic_calls,
            "llm_ratio": self.llm_calls / max(1, self.llm_calls + self.heuristic_calls),
        }


class GoldfishOpponent:
    """A do-nothing opponent for goldfish testing."""

    @property
    def name(self) -> str:
        return "Goldfish"

    def choose_mulligan(self, hand: list[str], mulligans: int) -> bool:
        return False

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        return [c.id for c in hand[-count:]]

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return None

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        for a in legal_actions:
            if a.type == ActionType.PLAY_LAND:
                return a
        return next(
            (a for a in legal_actions if a.type == ActionType.PASS_PRIORITY),
            legal_actions[0],
        )

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        return None

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        return hand[0].id if hand else None

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return candidates[0].id if candidates else None


# --- Shared heuristic functions ---

def _heuristic_choose_action(state: GameState, legal_actions: list[Action]) -> Action:
    """Deterministic action selection using fixed priority."""
    if not legal_actions:
        return Action(type=ActionType.PASS_PRIORITY, player_id="")

    land_plays = [a for a in legal_actions if a.type == ActionType.PLAY_LAND]
    casts = [a for a in legal_actions if a.type == ActionType.CAST_SPELL]
    abilities = [a for a in legal_actions if a.type == ActionType.ACTIVATE_ABILITY]
    attacks = [a for a in legal_actions if a.type == ActionType.ATTACK]

    # Priority: play land first
    if land_plays:
        for lp in land_plays:
            if lp.card_name == "Swamp":
                return lp
        for lp in land_plays:
            if lp.card_name == "Urborg, Tomb of Yawgmoth":
                return lp
        return land_plays[0]

    # Attack with creatures if able
    if attacks:
        return attacks[0]

    # Block to protect life total
    blocks = [a for a in legal_actions if a.type == ActionType.BLOCK]
    if blocks:
        # Block the biggest attacker with our smallest creature that survives
        return blocks[0]

    # Activate Liliana if on board
    if abilities:
        for ab in abilities:
            if "Liliana" in ab.card_name:
                player = state.get_player(ab.player_id)
                opponent = state.opponent_of(ab.player_id)
                if ab.choices.get("mode") == "+1":
                    if opponent.hand_size > 0 or player.hand_size > 1:
                        return ab
                if opponent.hand_size == 0 and any(
                    c.definition.is_creature for c in opponent.battlefield
                ):
                    if ab.choices.get("mode") == "-2":
                        return ab

    # Cast spells in priority order
    if casts:
        for priority_name in CAST_PRIORITY:
            for cast in casts:
                if cast.card_name == priority_name:
                    return cast
        return casts[0]

    if abilities:
        return abilities[0]

    return next(a for a in legal_actions if a.type == ActionType.PASS_PRIORITY)


def _heuristic_cards_to_bottom(hand: list[CardInstance], count: int) -> list[str]:
    """Bottom excess lands first, then highest-CMC cards."""
    lands = [c for c in hand if c.definition.is_land]
    non_lands = [c for c in hand if not c.definition.is_land]
    to_bottom: list[str] = []
    # Bottom excess lands (keep up to 3)
    if len(lands) > 3:
        excess = lands[3:]
        for c in excess:
            if len(to_bottom) >= count:
                break
            to_bottom.append(c.id)
    # Bottom highest-CMC non-lands
    non_lands.sort(key=lambda c: c.definition.cmc, reverse=True)
    for c in non_lands:
        if len(to_bottom) >= count:
            break
        to_bottom.append(c.id)
    # If still need more, bottom remaining lands
    for c in lands:
        if len(to_bottom) >= count:
            break
        if c.id not in to_bottom:
            to_bottom.append(c.id)
    return to_bottom[:count]


def _heuristic_discard_target(opponent_hand: list[CardInstance]) -> str | None:
    """Score-based discard target selection."""
    if not opponent_hand:
        return None

    best_id = None
    best_score = -1.0
    for card in opponent_hand:
        score = 0.0
        if card.definition.is_planeswalker:
            score = 10
        elif card.definition.is_creature:
            score = 7
        elif card.definition.is_instant or card.definition.is_sorcery:
            score = 5
        elif card.definition.is_enchantment:
            score = 6
        elif card.definition.is_artifact:
            score = 4
        elif card.definition.is_land:
            score = 1
        score += card.definition.cmc * 0.5
        if score > best_score:
            best_score = score
            best_id = card.id
    return best_id


def _heuristic_discard_from_hand(hand: list[CardInstance]) -> str | None:
    """Discard highest CMC non-land, or excess land."""
    if not hand:
        return None
    non_lands = [c for c in hand if not c.definition.is_land]
    if non_lands:
        # Discard highest CMC non-land
        best = max(non_lands, key=lambda c: c.definition.cmc)
        return best.id
    # All lands — discard any
    return hand[0].id


def _heuristic_sacrifice(candidates: list[CardInstance]) -> str | None:
    """Sacrifice least valuable permanent (lowest CMC)."""
    if not candidates:
        return None
    worst = min(candidates, key=lambda c: c.definition.cmc)
    return worst.id


def _is_land(name: str) -> bool:
    return name in (
        "Swamp", "Urborg, Tomb of Yawgmoth", "Castle Locthwain",
        "Mishra's Factory", "Urza's Saga",
    )


def _is_discard(name: str) -> bool:
    return name in (
        "Thoughtseize", "Inquisition of Kozilek", "Raven's Crime",
        "Wrench Mind", "Funeral Charm",
    )


def _format_board(cards: list[dict]) -> str:
    if not cards:
        return "empty"
    parts = []
    for c in cards:
        s = c["name"]
        if c.get("tapped"):
            s += " (tapped)"
        if c.get("power"):
            s += f" {c['power']}/{c['toughness']}"
        parts.append(s)
    return ", ".join(parts)


def _format_mana(mana_pool) -> str:
    parts = []
    for color, attr in [("B", "black"), ("W", "white"), ("U", "blue"), ("R", "red"), ("G", "green"), ("C", "colorless")]:
        val = getattr(mana_pool, attr, 0)
        if val > 0:
            parts.append(f"{val}{color}")
    return " ".join(parts) if parts else "empty"
