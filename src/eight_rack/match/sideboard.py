"""Sideboard manager: LLM-driven for pilot, heuristic for opponents."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from ..cards.models import CardDefinition
from ..llm.client import LLMClient

logger = logging.getLogger(__name__)


# --- Structured output models ---


class SideboardSwap(BaseModel):
    """A single card swap: bring one in, take one out."""

    card_in: str = Field(description="Card name to bring in from sideboard")
    card_out: str = Field(description="Card name to remove from mainboard")
    reason: str = Field(description="Brief reason for this swap")


class SideboardPlan(BaseModel):
    """Full sideboard plan for a matchup."""

    swaps: list[SideboardSwap] = Field(
        default_factory=list,
        description="List of card swaps to make. Empty if no changes needed.",
    )
    reasoning: str = Field(
        default="",
        description="Overall sideboarding reasoning for this matchup",
    )


# --- Heuristic sideboard guides ---

# Pre-built sideboard plans for common matchups (opponent archetype -> swaps)
# Format: {archetype: [(in_name, out_name), ...]}
EIGHT_RACK_SB_GUIDES: dict[str, list[tuple[str, str]]] = {
    "boros_energy": [
        ("Fatal Push", "Wrench Mind"),
        ("Bontu's Last Reckoning", "Raven's Crime"),
        ("Bontu's Last Reckoning", "Raven's Crime"),
        ("Ensnaring Bridge", "Funeral Charm"),
    ],
    "ruby_storm": [
        ("Damping Sphere", "Fatal Push"),
        ("Damping Sphere", "Bloodchief's Thirst"),
        ("Leyline of the Void", "Sheoldred's Edict"),
        ("Leyline of the Void", "Funeral Charm"),
        ("Leyline of the Void", "Funeral Charm"),
        ("Leyline of the Void", "Raven's Crime"),
    ],
    "jeskai_blink": [
        ("Nihil Spellbomb", "Raven's Crime"),
        ("Nihil Spellbomb", "Raven's Crime"),
        ("The Rack", "Funeral Charm"),
    ],
    "eldrazi_tron": [
        ("Damping Sphere", "Fatal Push"),
        ("Damping Sphere", "Bloodchief's Thirst"),
        ("Pithing Needle", "Sheoldred's Edict"),
    ],
    "affinity": [
        ("Engineered Explosives", "Raven's Crime"),
        ("Chalice of the Void", "Raven's Crime"),
        ("Fatal Push", "Wrench Mind"),
    ],
    "domain_zoo": [
        ("Fatal Push", "Wrench Mind"),
        ("Bontu's Last Reckoning", "Raven's Crime"),
        ("Bontu's Last Reckoning", "Raven's Crime"),
        ("Ensnaring Bridge", "Funeral Charm"),
    ],
    "amulet_titan": [
        ("Damping Sphere", "Fatal Push"),
        ("Damping Sphere", "Bloodchief's Thirst"),
        ("Ashiok, Dream Render", "Sheoldred's Edict"),
        ("Pithing Needle", "Funeral Charm"),
    ],
    "neobrand": [
        ("Leyline of the Void", "Fatal Push"),
        ("Leyline of the Void", "Bloodchief's Thirst"),
        ("Leyline of the Void", "Sheoldred's Edict"),
        ("Leyline of the Void", "Funeral Charm"),
        ("Nihil Spellbomb", "Raven's Crime"),
        ("Nihil Spellbomb", "Raven's Crime"),
    ],
    "goryos_vengeance": [
        ("Leyline of the Void", "Fatal Push"),
        ("Leyline of the Void", "Bloodchief's Thirst"),
        ("Leyline of the Void", "Sheoldred's Edict"),
        ("Leyline of the Void", "Wrench Mind"),
        ("Nihil Spellbomb", "Raven's Crime"),
        ("Nihil Spellbomb", "Raven's Crime"),
    ],
    "yawgmoth": [
        ("Nihil Spellbomb", "Raven's Crime"),
        ("Nihil Spellbomb", "Raven's Crime"),
        ("Bontu's Last Reckoning", "Funeral Charm"),
        ("Bontu's Last Reckoning", "Funeral Charm"),
        ("Ensnaring Bridge", "Wrench Mind"),
    ],
}


class SideboardManager:
    """Manages sideboard decisions between games.

    For the 8 Rack pilot: uses heuristic guides first, falls back to LLM.
    For opponents: uses simple heuristic (no sideboarding by default).
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client

    def sideboard(
        self,
        *,
        mainboard: list[CardDefinition],
        sideboard: list[CardDefinition],
        opponent_deck_name: str,
        game_results: list,
        is_pilot: bool,
    ) -> tuple[list[CardDefinition], list[CardDefinition]]:
        """Perform sideboard swaps, returning (new_mainboard, new_sideboard).

        Args:
            mainboard: Current mainboard card definitions
            sideboard: Current sideboard card definitions
            opponent_deck_name: Name of the opponent's deck archetype
            game_results: Results of previous games in this match
            is_pilot: True if this is the 8 Rack pilot, False for opponent

        Returns:
            Tuple of (updated_mainboard, updated_sideboard)
        """
        if is_pilot:
            return self._pilot_sideboard(
                mainboard, sideboard, opponent_deck_name, game_results
            )
        else:
            # Opponents don't sideboard in our simulation (simplification)
            return list(mainboard), list(sideboard)

    def _pilot_sideboard(
        self,
        mainboard: list[CardDefinition],
        sideboard: list[CardDefinition],
        opponent_deck_name: str,
        game_results: list,
    ) -> tuple[list[CardDefinition], list[CardDefinition]]:
        """Sideboard for the 8 Rack pilot."""
        # Normalize archetype name
        archetype = opponent_deck_name.lower().replace(" ", "_")

        # Try heuristic guide first
        if archetype in EIGHT_RACK_SB_GUIDES:
            return self._apply_heuristic_swaps(
                mainboard, sideboard, archetype
            )

        # Fall back to LLM if available
        if self.llm_client:
            return self._llm_sideboard(
                mainboard, sideboard, opponent_deck_name, game_results
            )

        # No guide, no LLM - return unchanged
        logger.warning(
            f"No sideboard guide for '{archetype}' and no LLM available"
        )
        return list(mainboard), list(sideboard)

    def _apply_heuristic_swaps(
        self,
        mainboard: list[CardDefinition],
        sideboard: list[CardDefinition],
        archetype: str,
    ) -> tuple[list[CardDefinition], list[CardDefinition]]:
        """Apply pre-built sideboard swaps."""
        swaps = EIGHT_RACK_SB_GUIDES[archetype]
        new_main = list(mainboard)
        new_sb = list(sideboard)

        for card_in_name, card_out_name in swaps:
            # Find card to bring in from sideboard
            in_card = None
            for i, card in enumerate(new_sb):
                if card.name == card_in_name:
                    in_card = new_sb.pop(i)
                    break

            # Find card to take out from mainboard
            out_card = None
            for i, card in enumerate(new_main):
                if card.name == card_out_name:
                    out_card = new_main.pop(i)
                    break

            if in_card and out_card:
                new_main.append(in_card)
                new_sb.append(out_card)
                logger.info(f"  SB: -{card_out_name} +{card_in_name}")
            else:
                if not in_card:
                    logger.debug(f"  SB skip: {card_in_name} not in sideboard")
                if not out_card:
                    logger.debug(f"  SB skip: {card_out_name} not in mainboard")

        logger.info(
            f"Sideboard complete: {len(new_main)} main, {len(new_sb)} side"
        )
        return new_main, new_sb

    def _llm_sideboard(
        self,
        mainboard: list[CardDefinition],
        sideboard: list[CardDefinition],
        opponent_deck_name: str,
        game_results: list,
    ) -> tuple[list[CardDefinition], list[CardDefinition]]:
        """Use LLM to decide sideboard swaps."""
        main_names = sorted(set(c.name for c in mainboard))
        sb_names = sorted(set(c.name for c in sideboard))
        main_counts = {}
        for c in mainboard:
            main_counts[c.name] = main_counts.get(c.name, 0) + 1
        sb_counts = {}
        for c in sideboard:
            sb_counts[c.name] = sb_counts.get(c.name, 0) + 1

        main_str = ", ".join(f"{v}x {k}" for k, v in sorted(main_counts.items()))
        sb_str = ", ".join(f"{v}x {k}" for k, v in sorted(sb_counts.items()))

        # Summarize previous games
        game_summary = ""
        for gr in game_results:
            game_summary += (
                f"Game {gr.game_number}: "
                f"{'Won' if gr.winner_name == '8 Rack' else 'Lost'} "
                f"(turn {gr.turns})\n"
            )

        prompt = f"""You are sideboarding for 8 Rack (Modern MTG) against {opponent_deck_name}.

Current mainboard: {main_str}
Current sideboard: {sb_str}

Previous games this match:
{game_summary if game_summary else "No previous games."}

Decide which cards to swap. Each swap brings one card IN from sideboard and takes one card OUT from mainboard. You can make 0-6 swaps. Keep the total at 60 mainboard / 15 sideboard.

Consider:
- Against aggro: bring in removal, Ensnaring Bridge, Bontu's Last Reckoning
- Against combo: bring in Damping Sphere, Leyline of the Void, Chalice
- Against graveyard: bring in Leyline of the Void, Nihil Spellbomb
- Against control: keep discard dense, consider Liliana of the Dark Realms
- Cut weak cards for the matchup (e.g., Raven's Crime vs fast aggro)"""

        try:
            plan = self.llm_client.query(
                response_model=SideboardPlan,
                system="You are an expert 8 Rack pilot making sideboard decisions.",
                messages=[{"role": "user", "content": prompt}],
                model="sonnet",
                max_tokens=512,
            )
            logger.info(f"LLM sideboard plan: {plan.reasoning}")

            # Apply the LLM's swaps
            new_main = list(mainboard)
            new_sb = list(sideboard)

            for swap in plan.swaps:
                in_card = None
                for i, card in enumerate(new_sb):
                    if card.name == swap.card_in:
                        in_card = new_sb.pop(i)
                        break

                out_card = None
                for i, card in enumerate(new_main):
                    if card.name == swap.card_out:
                        out_card = new_main.pop(i)
                        break

                if in_card and out_card:
                    new_main.append(in_card)
                    new_sb.append(out_card)
                    logger.info(
                        f"  SB: -{swap.card_out} +{swap.card_in} ({swap.reason})"
                    )

            # Validate deck sizes
            if len(new_main) != len(mainboard):
                logger.warning(
                    f"Sideboard changed deck size! "
                    f"{len(new_main)} != {len(mainboard)}. Reverting."
                )
                return list(mainboard), list(sideboard)

            return new_main, new_sb

        except Exception as e:
            logger.warning(f"LLM sideboard failed: {e}. No changes.")
            return list(mainboard), list(sideboard)
