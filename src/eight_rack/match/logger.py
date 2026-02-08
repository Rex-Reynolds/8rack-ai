"""JSONL game and match logging."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .runner import GameResult, MatchResult

logger = logging.getLogger(__name__)


class MatchLogger:
    """Logs match and game results to JSONL files.

    Files:
    - data/games/matches.jsonl: One line per match result
    - data/games/games.jsonl: One line per game result (with match context)
    """

    def __init__(self, data_dir: Path):
        self.games_dir = data_dir / "games"
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.matches_file = self.games_dir / "matches.jsonl"
        self.games_file = self.games_dir / "games.jsonl"

    def log_match(self, result: MatchResult) -> None:
        """Log a complete match result."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "match_id": result.match_id,
            "p1_name": result.p1_name,
            "p2_name": result.p2_name,
            "p1_deck": result.p1_deck,
            "p2_deck": result.p2_deck,
            "p1_wins": result.p1_wins,
            "p2_wins": result.p2_wins,
            "match_winner": result.match_winner_name,
            "total_games": len(result.games),
        }
        self._append_jsonl(self.matches_file, record)

        # Also log each game
        for game in result.games:
            self.log_game(game, result)

        logger.info(f"Logged match {result.match_id} to {self.matches_file}")

    def log_game(self, game: GameResult, match: MatchResult) -> None:
        """Log a single game result with match context."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "match_id": match.match_id,
            "game_number": game.game_number,
            "p1_name": match.p1_name,
            "p2_name": match.p2_name,
            "p1_deck": match.p1_deck,
            "p2_deck": match.p2_deck,
            "winner": game.winner_name,
            "loser": game.loser_name,
            "turns": game.turns,
            "p1_life": game.p1_life,
            "p2_life": game.p2_life,
            "is_post_sideboard": game.is_post_sideboard,
            "log_lines": len(game.game_log),
        }
        self._append_jsonl(self.games_file, record)

    def _append_jsonl(self, path: Path, record: dict) -> None:
        """Append a single JSON record to a JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def load_matches(self) -> list[dict]:
        """Load all match records from JSONL."""
        if not self.matches_file.exists():
            return []
        records = []
        with open(self.matches_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def load_games(self) -> list[dict]:
        """Load all game records from JSONL."""
        if not self.games_file.exists():
            return []
        records = []
        with open(self.games_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
