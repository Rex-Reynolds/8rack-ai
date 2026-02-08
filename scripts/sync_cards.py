#!/usr/bin/env python3
"""Sync card data from Scryfall for all decklists."""

import sys
from pathlib import Path

import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from eight_rack.cards.database import CardDatabase


def collect_card_names(decks_dir: Path) -> list[str]:
    """Collect all unique card names from all deck YAML files."""
    names = set()
    for yaml_file in decks_dir.rglob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        for section in ("mainboard", "sideboard"):
            for entry in data.get(section, []):
                names.add(entry["name"])
    return sorted(names)


def main():
    data_dir = project_root / "data" / "cards"
    decks_dir = project_root / "config" / "decks"
    db_path = data_dir / "cards.db"

    db = CardDatabase(db_path)

    print("Collecting card names from decklists...")
    names = collect_card_names(decks_dir)
    print(f"Found {len(names)} unique cards")

    print("Syncing from Scryfall (batch)...")
    results = db.sync_from_collection(names)
    print(f"Synced {len(results)} cards")

    # Report any missing
    missing = set(names) - set(results.keys())
    if missing:
        print(f"\nMissing cards ({len(missing)}):")
        for name in sorted(missing):
            print(f"  - {name}")
    else:
        print("\nAll cards synced successfully!")

    db.close()


if __name__ == "__main__":
    main()
