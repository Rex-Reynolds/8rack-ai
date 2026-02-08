#!/usr/bin/env python3
"""Run a game or best-of-3 match: 8 Rack vs an opponent."""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from eight_rack.agents.pilot import DeterministicPilot, GoldfishOpponent
from eight_rack.agents.opponent import ScriptedOpponent
from eight_rack.cards.database import CardDatabase
from eight_rack.game.engine import GameEngine
from eight_rack.game.resolver import Resolver


def main():
    parser = argparse.ArgumentParser(description="Run a game or Bo3 match")
    parser.add_argument(
        "--opponent", "-o",
        default="goldfish",
        help="Opponent type: goldfish, boros_energy, ruby_storm, etc.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--visual", action="store_true", help="Show ASCII board display")
    parser.add_argument("--bo3", action="store_true", help="Run best-of-3 match")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between visual frames (seconds)")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    db_path = project_root / "data" / "cards" / "cards.db"
    deck_path = project_root / "config" / "decks" / "eight_rack.yaml"

    db = CardDatabase(db_path)
    if db.get("The Rack") is None:
        print("Card database not populated. Run scripts/sync_cards.py first.")
        sys.exit(1)

    # Set up visual display if requested
    observer = None
    if args.visual:
        from eight_rack.display import VisualDisplay
        observer = VisualDisplay(delay=args.delay)

    engine = GameEngine(db, observer=observer)
    deck = engine.build_deck(deck_path)
    print(f"Loaded 8 Rack deck: {len(deck)} cards")

    pilot = DeterministicPilot()

    if args.opponent == "goldfish":
        opponent_agent = GoldfishOpponent()
        swamp_def = db.get("Swamp")
        opponent_deck = [swamp_def] * 60
        opp_name = "Goldfish"
        opp_sideboard = []
    else:
        opponent_agent = ScriptedOpponent(args.opponent)
        opp_deck_path = project_root / "config" / "decks" / "opponents" / f"{args.opponent}.yaml"
        if not opp_deck_path.exists():
            print(f"Opponent deck not found: {opp_deck_path}")
            sys.exit(1)
        opponent_deck = engine.build_deck(opp_deck_path)
        opp_sideboard = engine.build_sideboard(opp_deck_path)
        opp_name = args.opponent.replace("_", " ").title()
        print(f"Loaded {opp_name} deck: {len(opponent_deck)} cards")

    if args.bo3:
        _run_bo3(engine, deck, deck_path, opponent_deck, opp_sideboard, pilot, opponent_agent, opp_name, db)
    else:
        _run_single_game(engine, deck, opponent_deck, pilot, opponent_agent, opp_name, db)


def _run_single_game(engine, deck, opponent_deck, pilot, opponent_agent, opp_name, db):
    """Run a single game."""
    player1 = engine.create_player("p1", "8 Rack", deck)
    player2 = engine.create_player("p2", opp_name, opponent_deck)

    state = engine.setup_game(player1, player2, pilot, opponent_agent)
    agents = {"p1": pilot, "p2": opponent_agent}

    print(f"\n=== {player1.name} vs {player2.name} ===\n")
    state = engine.run_game(state, agents)

    if not engine.observer:
        # Print log if not visual mode
        log = state.game_log
        if len(log) > 50:
            print(f"... ({len(log) - 30} earlier entries omitted)")
            for entry in log[-30:]:
                print(entry)
        else:
            for entry in log:
                print(entry)

    print(f"\n=== RESULT ===")
    print(f"8 Rack life: {state.players[0].life}")
    print(f"{opp_name} life: {state.players[1].life}")
    winner_name = "8 Rack" if state.winner == "p1" else opp_name if state.winner == "p2" else "Draw"
    print(f"Winner: {winner_name}")
    print(f"Turns: {state.turn_number}")

    db.close()


def _run_bo3(engine, deck, deck_path, opponent_deck, opp_sideboard, pilot, opponent_agent, opp_name, db):
    """Run a best-of-3 match."""
    from eight_rack.match.runner import MatchRunner
    from eight_rack.match.sideboard import SideboardManager
    from eight_rack.match.logger import MatchLogger

    pilot_sideboard = engine.build_sideboard(deck_path)
    sb_manager = SideboardManager()
    runner = MatchRunner(engine, sideboard_manager=sb_manager)

    print(f"\n=== Best-of-3: 8 Rack vs {opp_name} ===\n")

    result = runner.run_match(
        p1_name="8 Rack",
        p2_name=opp_name,
        p1_mainboard=deck,
        p2_mainboard=opponent_deck,
        p1_sideboard=pilot_sideboard,
        p2_sideboard=opp_sideboard,
        p1_agent=pilot,
        p2_agent=opponent_agent,
        p1_deck_name="8 Rack",
        p2_deck_name=opp_name,
    )

    # Log results
    data_dir = Path(__file__).parent.parent / "data"
    match_logger = MatchLogger(data_dir)
    match_logger.log_match(result)

    # Print match summary
    print(f"\n{'=' * 50}")
    print(f"  MATCH RESULT: {result.match_winner_name} wins {result.p1_wins}-{result.p2_wins}")
    print(f"{'=' * 50}")
    for game in result.games:
        sb_tag = " (post-SB)" if game.is_post_sideboard else " (pre-SB)"
        print(f"  Game {game.game_number}{sb_tag}: "
              f"{game.winner_name} wins on turn {game.turns} "
              f"({game.p1_life} vs {game.p2_life} life)")
    print()

    db.close()


if __name__ == "__main__":
    main()
