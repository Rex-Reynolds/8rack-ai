#!/usr/bin/env python3
"""Play an interactive game as the 8 Rack pilot against an AI opponent."""

import argparse
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from rich.console import Console

from eight_rack.agents.interactive import InteractivePilot
from eight_rack.agents.opponent import ScriptedOpponent
from eight_rack.agents.pilot import GoldfishOpponent
from eight_rack.cards.database import CardDatabase
from eight_rack.display import VisualDisplay
from eight_rack.game.engine import GameEngine
from eight_rack.game.resolver import Resolver
from eight_rack.game.triggers import TriggerRegistry

console = Console(force_terminal=True)

OPPONENTS = [
    "goldfish", "boros_energy", "ruby_storm", "jeskai_blink",
    "eldrazi_tron", "affinity", "domain_zoo", "amulet_titan",
    "neobrand", "goryos_vengeance", "yawgmoth",
]


def main():
    parser = argparse.ArgumentParser(
        description="Play 8 Rack interactively against an AI opponent"
    )
    parser.add_argument(
        "--opponent", "-o",
        default="goldfish",
        choices=OPPONENTS,
        help="Opponent deck (default: goldfish)",
    )
    parser.add_argument(
        "--no-triggers",
        action="store_true",
        help="Disable trigger registry (use legacy upkeep triggers)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    db_path = project_root / "data" / "cards" / "cards.db"
    deck_path = project_root / "config" / "decks" / "eight_rack.yaml"

    db = CardDatabase(db_path)
    if db.get("The Rack") is None:
        console.print("[red]Card database not populated. Run scripts/sync_cards.py first.[/red]")
        sys.exit(1)

    # Set up trigger registry
    trigger_registry = None if args.no_triggers else TriggerRegistry()
    resolver = Resolver(trigger_registry=trigger_registry)

    # Visual display that doesn't auto-advance (human controls pace)
    observer = VisualDisplay(delay=0, only_main_phases=False)

    engine = GameEngine(db, resolver=resolver, observer=observer)
    deck = engine.build_deck(deck_path)

    pilot = InteractivePilot()

    if args.opponent == "goldfish":
        opponent_agent = GoldfishOpponent()
        swamp_def = db.get("Swamp")
        opponent_deck = [swamp_def] * 60
        opp_name = "Goldfish"
    else:
        opponent_agent = ScriptedOpponent(args.opponent)
        opp_deck_path = project_root / "config" / "decks" / "opponents" / f"{args.opponent}.yaml"
        if not opp_deck_path.exists():
            console.print(f"[red]Opponent deck not found: {opp_deck_path}[/red]")
            sys.exit(1)
        opponent_deck = engine.build_deck(opp_deck_path)
        opp_name = args.opponent.replace("_", " ").title()

    # Create players
    player1 = engine.create_player("p1", "8 Rack (You)", deck)
    player2 = engine.create_player("p2", opp_name, opponent_deck)

    state = engine.setup_game(player1, player2, pilot, opponent_agent)
    agents = {"p1": pilot, "p2": opponent_agent}

    console.print()
    console.print(f"[bold]{'=' * 50}[/bold]")
    console.print(f"[bold]  8 Rack (You) vs {opp_name}[/bold]")
    console.print(f"[bold]{'=' * 50}[/bold]")
    console.print()
    console.print("[dim]  Ctrl+C to concede at any time[/dim]")
    console.print()

    try:
        state = engine.run_game(state, agents)
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[bold]Game ended.[/bold]")
        db.close()
        return

    # Final result
    console.print()
    console.print(f"[bold]{'=' * 50}[/bold]")
    p1, p2 = state.players[0], state.players[1]
    if state.winner == "p1":
        console.print(f"[bold green]  YOU WIN! ({p1.life} life remaining)[/bold green]")
    elif state.winner == "p2":
        console.print(f"[bold red]  {opp_name} wins. ({p2.life} life remaining)[/bold red]")
    else:
        console.print(f"[bold yellow]  DRAW[/bold yellow]")
    console.print(f"  Turns: {state.turn_number}")
    console.print(f"[bold]{'=' * 50}[/bold]")
    console.print()

    db.close()


if __name__ == "__main__":
    main()
