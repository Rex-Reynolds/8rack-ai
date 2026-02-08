"""Interactive (human-in-the-loop) pilot agent for CLI play."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.text import Text

from ..display import render_board, clear_screen, filter_log
from ..game.actions import Action, ActionType
from ..game.state import CardInstance, GameState, Phase

console = Console(force_terminal=True)

# Action types that are "auto-pass" — if these are the only options, skip the prompt
_SKIP_PHASES = {Phase.UNTAP, Phase.CLEANUP}

# Display order for action grouping
_ACTION_GROUP_ORDER = [
    ActionType.CAST_SPELL,
    ActionType.PLAY_LAND,
    ActionType.ACTIVATE_ABILITY,
    ActionType.ATTACK,
    ActionType.BLOCK,
    ActionType.DISCARD,
]

_ACTION_GROUP_NAMES = {
    ActionType.CAST_SPELL: "Spells",
    ActionType.PLAY_LAND: "Lands",
    ActionType.ACTIVATE_ABILITY: "Abilities",
    ActionType.ATTACK: "Attackers",
    ActionType.BLOCK: "Blockers",
    ActionType.DISCARD: "Discard",
}


class InteractivePilot:
    """Human-controlled pilot that prompts for every priority decision.

    Displays the board via Rich, lists legal actions, and reads input from stdin.
    """

    def __init__(self, auto_pass_empty: bool = True):
        self._auto_pass_empty = auto_pass_empty

    @property
    def name(self) -> str:
        return "8 Rack Pilot (You)"

    def choose_mulligan(self, hand: list[str], mulligans: int) -> bool:
        console.print()
        console.print(f"[bold]Opening hand ({7 - mulligans} cards):[/bold]")
        for i, name in enumerate(hand):
            console.print(f"  {i + 1}. {name}")
        console.print()
        choice = _prompt("[bold]Keep or Mulligan?[/bold] (k/m): ", valid={"k", "m"})
        return choice == "m"

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        console.print()
        console.print(f"[bold]Choose {count} card(s) to put on bottom:[/bold]")
        for i, card in enumerate(hand):
            console.print(f"  {i}. {card.name}")
        chosen: list[str] = []
        while len(chosen) < count:
            remaining = count - len(chosen)
            idx = _prompt_int(f"  Card to bottom ({remaining} remaining, 0-{len(hand) - 1}): ", 0, len(hand) - 1)
            card_id = hand[idx].id
            if card_id in chosen:
                console.print("  [red]Already selected that card.[/red]")
                continue
            chosen.append(card_id)
        return chosen

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        if not legal_actions:
            return Action(type=ActionType.PASS_PRIORITY, player_id="")

        # Auto-pass in bookkeeping phases or when pass is the only option
        if len(legal_actions) == 1 and legal_actions[0].type == ActionType.PASS_PRIORITY:
            return legal_actions[0]

        # Auto-pass in phases where you rarely want to act
        if self._auto_pass_empty and state.phase in _SKIP_PHASES:
            pass_action = next((a for a in legal_actions if a.type == ActionType.PASS_PRIORITY), None)
            if pass_action:
                return pass_action

        # On opponent's turn, auto-pass if we have no meaningful actions
        if self._auto_pass_empty and state.active_player.id != legal_actions[0].player_id:
            non_pass = [a for a in legal_actions if a.type != ActionType.PASS_PRIORITY]
            if not non_pass:
                pass_action = next((a for a in legal_actions if a.type == ActionType.PASS_PRIORITY), None)
                if pass_action:
                    return pass_action

        # Show board
        clear_screen()
        console.print(render_board(state))

        # Show recent log (filtered)
        recent = filter_log(state.game_log)
        if recent:
            console.print(f"\n  [dim]{'─' * 60}[/dim]")
            for entry in recent:
                console.print(f"  [dim]{entry}[/dim]")

        # Show stack
        if state.stack:
            console.print(f"\n  [bold yellow]Stack ({len(state.stack)}):[/bold yellow]")
            for i, item in enumerate(reversed(state.stack)):
                console.print(f"    {i + 1}. {item.description}")

        # Show combat info
        if state.combat.attackers:
            console.print(f"\n  [bold red]Attackers:[/bold red]")
            for atk_id in state.combat.attackers:
                for p in state.players:
                    c = p.find_card(atk_id)
                    if c:
                        console.print(f"    {c.name} ({c.definition.power}/{c.definition.toughness})")
            if state.combat.blockers:
                console.print(f"  [bold blue]Blockers:[/bold blue]")
                for blk_id, atk_id in state.combat.blockers.items():
                    blk = atk = None
                    for p in state.players:
                        blk = blk or p.find_card(blk_id)
                        atk = atk or p.find_card(atk_id)
                    if blk and atk:
                        console.print(f"    {blk.name} blocking {atk.name}")

        # Show legal actions (grouped)
        _display_grouped_actions(legal_actions)

        console.print()
        idx = _prompt_int(f"  Choose action (0-{len(legal_actions) - 1}): ", 0, len(legal_actions) - 1)
        return legal_actions[idx]

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            console.print(f"  [bold]Only option: {candidates[0].name}[/bold]")
            return candidates[0].id

        console.print(f"\n  [bold]Search — choose a card to put onto the battlefield:[/bold]")
        for i, card in enumerate(candidates):
            info = f"{card.name} ({card.definition.type_line}"
            if card.definition.mana_cost:
                info += f", {card.definition.mana_cost}"
            info += ")"
            console.print(f"    [bold]{i}[/bold]) {info}")

        console.print()
        idx = _prompt_int(f"  Choose card (0-{len(candidates) - 1}): ", 0, len(candidates) - 1)
        return candidates[idx].id

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        if not opponent_hand:
            return None
        if len(opponent_hand) == 1:
            console.print(f"  [bold]Only target: {opponent_hand[0].name}[/bold]")
            return opponent_hand[0].id

        console.print(f"\n  [bold]Opponent's hand (choose a card to discard):[/bold]")
        for i, card in enumerate(opponent_hand):
            info = f"{card.name} ({card.definition.type_line}"
            if card.definition.mana_cost:
                info += f", {card.definition.mana_cost}"
            info += ")"
            console.print(f"    [bold]{i}[/bold]) {info}")

        console.print()
        idx = _prompt_int(f"  Choose discard target (0-{len(opponent_hand) - 1}): ", 0, len(opponent_hand) - 1)
        return opponent_hand[idx].id

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        if not hand:
            return None
        if len(hand) == 1:
            console.print(f"  [bold]Only card: {hand[0].name}[/bold]")
            return hand[0].id

        console.print(f"\n  [bold]Choose a card to discard from your hand:[/bold]")
        for i, card in enumerate(hand):
            info = f"{card.name} ({card.definition.type_line}"
            if card.definition.mana_cost:
                info += f", {card.definition.mana_cost}"
            info += ")"
            console.print(f"    [bold]{i}[/bold]) {info}")

        console.print()
        idx = _prompt_int(f"  Choose card to discard (0-{len(hand) - 1}): ", 0, len(hand) - 1)
        return hand[idx].id

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            console.print(f"  [bold]Only option: {candidates[0].name}[/bold]")
            return candidates[0].id

        console.print(f"\n  [bold]Choose a permanent to sacrifice:[/bold]")
        for i, card in enumerate(candidates):
            info = f"{card.name} ({card.definition.type_line}"
            if card.definition.is_creature:
                p = int(card.definition.power or 0) + card.counters.get("p1p1", 0)
                t = int(card.definition.toughness or 0) + card.counters.get("p1p1", 0)
                info += f", {p}/{t}"
            info += ")"
            console.print(f"    [bold]{i}[/bold]) {info}")

        console.print()
        idx = _prompt_int(f"  Choose permanent to sacrifice (0-{len(candidates) - 1}): ", 0, len(candidates) - 1)
        return candidates[idx].id


def _display_grouped_actions(actions: list[Action]) -> None:
    """Display actions grouped by type with section headers.

    Actions keep their original indices so the prompt works identically.
    """
    console.print(f"\n  [bold]Legal Actions:[/bold]")

    # Build index mapping: action_type -> list of (original_index, action)
    groups: dict[ActionType, list[tuple[int, Action]]] = {}
    pass_entries: list[tuple[int, Action]] = []

    for i, action in enumerate(actions):
        if action.type == ActionType.PASS_PRIORITY:
            pass_entries.append((i, action))
        else:
            groups.setdefault(action.type, []).append((i, action))

    # Display groups in defined order
    for action_type in _ACTION_GROUP_ORDER:
        if action_type not in groups:
            continue
        header = _ACTION_GROUP_NAMES[action_type]
        console.print(f"    [dim]-- {header} --[/dim]")
        for idx, action in groups[action_type]:
            tag = _action_tag(action)
            console.print(f"      [bold]{idx}[/bold]) {tag}{action.description or str(action)}")

    # Display any remaining action types not in the order list
    for action_type, entries in groups.items():
        if action_type in _ACTION_GROUP_NAMES:
            continue
        for idx, action in entries:
            tag = _action_tag(action)
            console.print(f"      [bold]{idx}[/bold]) {tag}{action.description or str(action)}")

    # Pass always last, no header
    for idx, action in pass_entries:
        tag = _action_tag(action)
        console.print(f"      [bold]{idx}[/bold]) {tag}{action.description or str(action)}")


def _action_tag(action: Action) -> str:
    """Return a colored tag prefix for action type."""
    match action.type:
        case ActionType.PLAY_LAND:
            return "[yellow][LAND][/yellow] "
        case ActionType.CAST_SPELL:
            return "[green][CAST][/green] "
        case ActionType.ACTIVATE_ABILITY:
            return "[cyan][ABILITY][/cyan] "
        case ActionType.ATTACK:
            return "[red][ATTACK][/red] "
        case ActionType.BLOCK:
            return "[blue][BLOCK][/blue] "
        case ActionType.PASS_PRIORITY:
            return "[dim][PASS][/dim] "
        case ActionType.DISCARD:
            return "[magenta][DISCARD][/magenta] "
        case _:
            return ""


def _prompt(msg: str, valid: set[str] | None = None) -> str:
    """Prompt user for input, optionally validating against a set."""
    while True:
        try:
            console.print(msg, end="")
            val = input().strip().lower()
            if valid is None or val in valid:
                return val
            console.print(f"  [red]Invalid input. Choose from: {', '.join(sorted(valid))}[/red]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [bold]Conceding.[/bold]")
            sys.exit(0)


def _prompt_int(msg: str, lo: int, hi: int) -> int:
    """Prompt user for an integer in [lo, hi]."""
    while True:
        try:
            console.print(msg, end="")
            val = input().strip()
            n = int(val)
            if lo <= n <= hi:
                return n
            console.print(f"  [red]Choose a number between {lo} and {hi}.[/red]")
        except ValueError:
            console.print(f"  [red]Enter a number.[/red]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [bold]Conceding.[/bold]")
            sys.exit(0)
