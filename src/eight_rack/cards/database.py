"""Card database with Scryfall sync and SQLite cache."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import httpx

from .models import CardDefinition

logger = logging.getLogger(__name__)

SCRYFALL_API = "https://api.scryfall.com"
# Scryfall asks for 50-100ms between requests
SCRYFALL_DELAY = 0.1


class CardDatabase:
    """SQLite-backed card database with Scryfall sync."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._cache: dict[str, CardDefinition] = {}

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                name TEXT PRIMARY KEY,
                data JSON NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self.conn.commit()

    def get(self, name: str) -> CardDefinition | None:
        """Get a card by exact name or front-face name, from cache or DB."""
        if name in self._cache:
            return self._cache[name]

        row = self.conn.execute(
            "SELECT data FROM cards WHERE name = ?", (name,)
        ).fetchone()
        if row:
            card = CardDefinition.model_validate_json(row["data"])
            self._cache[name] = card
            return card

        # Try matching as front face of a DFC/split card (name // back_name)
        row = self.conn.execute(
            "SELECT data FROM cards WHERE name LIKE ?", (f"{name} //%",)
        ).fetchone()
        if row:
            card = CardDefinition.model_validate_json(row["data"])
            self._cache[name] = card
            return card
        return None

    def put(self, card: CardDefinition) -> None:
        """Store a card in the database."""
        self.conn.execute(
            "INSERT OR REPLACE INTO cards (name, data, updated_at) VALUES (?, ?, ?)",
            (card.name, card.model_dump_json(), time.time()),
        )
        self.conn.commit()
        self._cache[card.name] = card

    def sync_card(self, name: str, client: httpx.Client | None = None) -> CardDefinition:
        """Fetch a card from Scryfall and cache it."""
        existing = self.get(name)
        if existing:
            return existing

        logger.info(f"Fetching card from Scryfall: {name}")
        own_client = client is None
        if own_client:
            client = httpx.Client()
        try:
            resp = client.get(
                f"{SCRYFALL_API}/cards/named",
                params={"exact": name},
            )
            resp.raise_for_status()
            data = resp.json()
            card = CardDefinition.from_scryfall(data)
            self.put(card)
            return card
        finally:
            if own_client:
                client.close()

    def sync_decklist(self, card_names: list[str]) -> dict[str, CardDefinition]:
        """Sync all cards in a decklist from Scryfall."""
        unique_names = sorted(set(card_names))
        results = {}
        with httpx.Client() as client:
            for name in unique_names:
                card = self.sync_card(name, client)
                results[name] = card
                time.sleep(SCRYFALL_DELAY)
        return results

    def sync_from_collection(self, card_names: list[str]) -> dict[str, CardDefinition]:
        """Sync using Scryfall's collection endpoint (batch, up to 75 at a time)."""
        unique_names = sorted(set(card_names))
        results = {}

        # First check cache/DB
        to_fetch = []
        for name in unique_names:
            card = self.get(name)
            if card:
                results[name] = card
            else:
                to_fetch.append(name)

        if not to_fetch:
            return results

        # Batch fetch via collection endpoint
        with httpx.Client() as client:
            for i in range(0, len(to_fetch), 75):
                batch = to_fetch[i : i + 75]
                identifiers = [{"name": n} for n in batch]
                resp = client.post(
                    f"{SCRYFALL_API}/cards/collection",
                    json={"identifiers": identifiers},
                )
                resp.raise_for_status()
                data = resp.json()

                for card_data in data.get("data", []):
                    card = CardDefinition.from_scryfall(card_data)
                    self.put(card)
                    results[card.name] = card

                not_found_names = []
                for not_found in data.get("not_found", []):
                    nf_name = not_found.get("name", str(not_found))
                    not_found_names.append(nf_name)
                    logger.debug(f"Collection miss: {nf_name}")

                if i + 75 < len(to_fetch):
                    time.sleep(SCRYFALL_DELAY)

            # Retry missing cards via fuzzy named endpoint (handles DFCs/split cards)
            still_missing = [n for n in to_fetch if n not in results]
            for name in still_missing:
                try:
                    time.sleep(SCRYFALL_DELAY)
                    resp = client.get(
                        f"{SCRYFALL_API}/cards/named",
                        params={"fuzzy": name},
                    )
                    if resp.status_code == 200:
                        card_data = resp.json()
                        card = CardDefinition.from_scryfall(card_data)
                        self.put(card)
                        results[name] = card
                        # Also cache under front-face name
                        if " // " in card.name and name != card.name:
                            self._cache[name] = card
                        logger.info(f"Fetched DFC/split card: {name} -> {card.name}")
                    else:
                        logger.warning(f"Card not found: {name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch {name}: {e}")

        return results

    def all_cards(self) -> list[CardDefinition]:
        """Return all cached cards."""
        rows = self.conn.execute("SELECT data FROM cards").fetchall()
        return [CardDefinition.model_validate_json(row["data"]) for row in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
