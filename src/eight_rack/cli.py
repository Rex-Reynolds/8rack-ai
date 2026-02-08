"""CLI entry point using typer."""

from __future__ import annotations

import typer

app = typer.Typer(name="eight-rack", help="8 Rack AI: MTG Deck Pilot & Tuning System")


@app.command()
def sync():
    """Sync card data from Scryfall."""
    from pathlib import Path
    import yaml
    from .cards.database import CardDatabase

    project_root = Path(__file__).parent.parent.parent
    decks_dir = project_root / "config" / "decks"
    db_path = project_root / "data" / "cards" / "cards.db"

    names = set()
    for yaml_file in decks_dir.rglob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        for section in ("mainboard", "sideboard"):
            for entry in data.get(section, []):
                names.add(entry["name"])

    db = CardDatabase(db_path)
    typer.echo(f"Syncing {len(names)} unique cards...")
    results = db.sync_from_collection(sorted(names))
    typer.echo(f"Synced {len(results)} cards")
    db.close()


@app.command()
def play():
    """Run a single game (8 Rack vs Goldfish)."""
    from pathlib import Path
    from .agents.pilot import DeterministicPilot, GoldfishOpponent
    from .cards.database import CardDatabase
    from .game.engine import GameEngine

    project_root = Path(__file__).parent.parent.parent
    db_path = project_root / "data" / "cards" / "cards.db"
    deck_path = project_root / "config" / "decks" / "eight_rack.yaml"

    db = CardDatabase(db_path)
    if db.get("The Rack") is None:
        typer.echo("Run 'eight-rack sync' first.")
        raise typer.Exit(1)

    engine = GameEngine(db)
    deck = engine.build_deck(deck_path)

    pilot = DeterministicPilot()
    goldfish = GoldfishOpponent()

    swamp_def = db.get("Swamp")
    goldfish_deck = [swamp_def] * 60

    p1 = engine.create_player("p1", "8 Rack", deck)
    p2 = engine.create_player("p2", "Goldfish", goldfish_deck)

    state = engine.setup_game(p1, p2, pilot, goldfish)
    state = engine.run_game(state, {"p1": pilot, "p2": goldfish})

    for entry in state.game_log:
        typer.echo(entry)

    typer.echo(f"\nResult: {'8 Rack wins' if state.winner == 'p1' else 'Goldfish wins' if state.winner == 'p2' else 'Draw'}")
    typer.echo(f"8 Rack: {state.players[0].life} life | Goldfish: {state.players[1].life} life | Turns: {state.turn_number}")
    db.close()


if __name__ == "__main__":
    app()
