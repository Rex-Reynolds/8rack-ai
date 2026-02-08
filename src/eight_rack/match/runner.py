"""Best-of-3 match orchestration."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..cards.models import CardDefinition
from ..game.engine import GameEngine
from ..game.state import GameState

logger = logging.getLogger(__name__)


class GameResult(BaseModel):
    """Result of a single game."""

    game_number: int
    winner_id: str | None = None
    winner_name: str = ""
    loser_name: str = ""
    turns: int = 0
    p1_life: int = 0
    p2_life: int = 0
    game_log: list[str] = Field(default_factory=list)
    is_post_sideboard: bool = False


class MatchResult(BaseModel):
    """Result of a best-of-3 match."""

    match_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    p1_name: str = ""
    p2_name: str = ""
    p1_deck: str = ""
    p2_deck: str = ""
    games: list[GameResult] = Field(default_factory=list)
    match_winner_id: str | None = None
    match_winner_name: str = ""
    p1_wins: int = 0
    p2_wins: int = 0

    @property
    def is_complete(self) -> bool:
        return self.p1_wins >= 2 or self.p2_wins >= 2


class MatchRunner:
    """Runs a best-of-3 match with sideboarding between games.

    Manages:
    - Game 1 (pre-board)
    - Sideboarding between games
    - Games 2-3 (post-board)
    - Match result aggregation
    """

    def __init__(
        self,
        engine: GameEngine,
        sideboard_manager: Any = None,
    ):
        self.engine = engine
        self.sideboard_manager = sideboard_manager

    def run_match(
        self,
        *,
        p1_name: str,
        p2_name: str,
        p1_mainboard: list[CardDefinition],
        p2_mainboard: list[CardDefinition],
        p1_sideboard: list[CardDefinition] | None = None,
        p2_sideboard: list[CardDefinition] | None = None,
        p1_agent: Any,
        p2_agent: Any,
        p1_deck_name: str = "",
        p2_deck_name: str = "",
    ) -> MatchResult:
        """Run a best-of-3 match."""
        result = MatchResult(
            p1_name=p1_name,
            p2_name=p2_name,
            p1_deck=p1_deck_name,
            p2_deck=p2_deck_name,
        )

        p1_current_deck = list(p1_mainboard)
        p2_current_deck = list(p2_mainboard)
        p1_current_sb = list(p1_sideboard or [])
        p2_current_sb = list(p2_sideboard or [])

        game_number = 0
        # Alternate who goes first: G1 random, G2 loser, G3 loser
        p1_on_play = True  # Simplified: p1 always on play G1

        while not result.is_complete and game_number < 3:
            game_number += 1
            is_post_sb = game_number > 1

            logger.info(
                f"=== Game {game_number} of match {result.match_id} "
                f"({'post-SB' if is_post_sb else 'pre-SB'}) ==="
            )

            # Sideboard between games
            if is_post_sb and self.sideboard_manager:
                p1_current_deck, p1_current_sb = self.sideboard_manager.sideboard(
                    mainboard=p1_current_deck,
                    sideboard=p1_current_sb,
                    opponent_deck_name=p2_deck_name,
                    game_results=result.games,
                    is_pilot=True,
                )
                p2_current_deck, p2_current_sb = self.sideboard_manager.sideboard(
                    mainboard=p2_current_deck,
                    sideboard=p2_current_sb,
                    opponent_deck_name=p1_deck_name,
                    game_results=result.games,
                    is_pilot=False,
                )

            # Create players and run game
            if p1_on_play:
                player1 = self.engine.create_player("p1", p1_name, p1_current_deck)
                player2 = self.engine.create_player("p2", p2_name, p2_current_deck)
                state = self.engine.setup_game(player1, player2, p1_agent, p2_agent)
                agents = {"p1": p1_agent, "p2": p2_agent}
            else:
                # Swap who's on the play (p2 goes first but keeps same IDs)
                player1 = self.engine.create_player("p1", p1_name, p1_current_deck)
                player2 = self.engine.create_player("p2", p2_name, p2_current_deck)
                state = self.engine.setup_game(player1, player2, p1_agent, p2_agent)
                state.active_player_index = 1  # p2 goes first
                agents = {"p1": p1_agent, "p2": p2_agent}

            state = self.engine.run_game(state, agents)

            # Record game result
            game_result = GameResult(
                game_number=game_number,
                winner_id=state.winner,
                winner_name=p1_name if state.winner == "p1" else p2_name if state.winner == "p2" else "",
                loser_name=p2_name if state.winner == "p1" else p1_name if state.winner == "p2" else "",
                turns=state.turn_number,
                p1_life=state.players[0].life,
                p2_life=state.players[1].life,
                game_log=state.game_log,
                is_post_sideboard=is_post_sb,
            )
            result.games.append(game_result)

            if state.winner == "p1":
                result.p1_wins += 1
                p1_on_play = False  # Loser chooses, usually goes first
            elif state.winner == "p2":
                result.p2_wins += 1
                p1_on_play = True  # Loser goes first

            logger.info(
                f"Game {game_number}: {game_result.winner_name} wins "
                f"(Score: {result.p1_wins}-{result.p2_wins})"
            )

        # Determine match winner
        if result.p1_wins >= 2:
            result.match_winner_id = "p1"
            result.match_winner_name = p1_name
        elif result.p2_wins >= 2:
            result.match_winner_id = "p2"
            result.match_winner_name = p2_name

        logger.info(
            f"Match complete: {result.match_winner_name} wins "
            f"{result.p1_wins}-{result.p2_wins}"
        )

        return result
