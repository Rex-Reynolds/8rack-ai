"""Rich visual display for game state with mini card rectangles."""

from __future__ import annotations

import os
import shutil
import time

from rich.console import Console
from rich.text import Text

from .cards.models import CardType, Color
from .game.state import CardInstance, GameState, Phase, Zone


# ── Phase display names ──────────────────────────────────────────────

PHASE_DISPLAY = {
    Phase.UNTAP: "Untap",
    Phase.UPKEEP: "Upkeep",
    Phase.DRAW: "Draw",
    Phase.MAIN_1: "Main 1",
    Phase.BEGIN_COMBAT: "Combat",
    Phase.DECLARE_ATTACKERS: "Attackers",
    Phase.DECLARE_BLOCKERS: "Blockers",
    Phase.COMBAT_DAMAGE: "Damage",
    Phase.END_COMBAT: "End Combat",
    Phase.MAIN_2: "Main 2",
    Phase.END_STEP: "End Step",
    Phase.CLEANUP: "Cleanup",
}

# Simplified phase bar (main phases only)
PHASE_BAR_PHASES = [
    Phase.UNTAP, Phase.UPKEEP, Phase.DRAW, Phase.MAIN_1,
    Phase.BEGIN_COMBAT, Phase.MAIN_2, Phase.END_STEP,
]

PHASE_BAR_NAMES = {
    Phase.UNTAP: "Untap",
    Phase.UPKEEP: "Upkeep",
    Phase.DRAW: "Draw",
    Phase.MAIN_1: "Main 1",
    Phase.BEGIN_COMBAT: "Combat",
    Phase.MAIN_2: "Main 2",
    Phase.END_STEP: "End",
}

# Map combat sub-phases to the Combat entry
_COMBAT_PHASES = {
    Phase.BEGIN_COMBAT, Phase.DECLARE_ATTACKERS,
    Phase.DECLARE_BLOCKERS, Phase.COMBAT_DAMAGE, Phase.END_COMBAT,
}


def _term_width() -> int:
    """Get terminal width, defaulting to 100."""
    try:
        return shutil.get_terminal_size((100, 24)).columns
    except Exception:
        return 100


# ── Color / icon helpers ─────────────────────────────────────────────

_COLOR_STYLE = {
    Color.BLACK: "magenta",
    Color.RED: "red",
    Color.WHITE: "bright_white",
    Color.BLUE: "blue",
    Color.GREEN: "green",
}


def _get_card_color(card: CardInstance) -> str:
    """Return a Rich style string for the card's MTG color."""
    colors = card.definition.colors
    if card.definition.is_land:
        return "yellow"
    if len(colors) > 1:
        return "cyan"
    if len(colors) == 1:
        return _COLOR_STYLE.get(colors[0], "bright_black")
    # Colorless / artifact
    return "bright_black"


def _get_type_icon(card: CardInstance) -> str:
    """Return a unicode icon for the card's primary type."""
    d = card.definition
    if d.is_creature:
        return "⚔"
    if d.is_planeswalker:
        return "✦"
    if d.is_artifact:
        return "⚙"
    if d.is_enchantment:
        return "✧"
    if d.is_instant or d.is_sorcery:
        return "★"
    if d.is_land:
        return "◆"
    return " "


# ── Mini card rendering ──────────────────────────────────────────────

CARD_INNER = 15  # inner width for hand cards (visible chars between borders)
CARD_W = CARD_INNER + 2  # total width including border chars

CARD_INNER_BF = 17  # wider inner width for battlefield cards
CARD_W_BF = CARD_INNER_BF + 2  # total battlefield card width

# Counters hidden from display (internal bookkeeping)
_HIDDEN_COUNTERS = {"loyalty", "deathtouch_damage", "animated", "loyalty_used"}


# ── Log filtering ────────────────────────────────────────────────────

_LOG_SUPPRESS = ["Pass priority", "pass_priority"]


def filter_log(entries: list[str], max_entries: int = 8) -> list[str]:
    """Filter out auto-pass spam from log entries and return the last N."""
    return [e for e in entries if not any(p in e for p in _LOG_SUPPRESS)][-max_entries:]


# ── Card rendering helpers ───────────────────────────────────────────

def _truncate(name: str, width: int = CARD_INNER) -> str:
    """Truncate a card name to fit inside the mini card."""
    if len(name) <= width:
        return name.ljust(width)
    # Try to break at a word boundary
    if width >= 8 and " " in name[:width]:
        # Find last space that fits
        last_space = name[:width - 1].rfind(" ")
        if last_space > width // 2:
            return name[:last_space].ljust(width)
    return name[: width - 1] + "…"


def _compact_mana(cost: str) -> str:
    """Convert '{1}{B}{B}' → '1BB', '{X}{R}' → 'XR', etc."""
    return cost.replace("{", "").replace("}", "")


def _name_line(card: CardInstance, inner_width: int = CARD_INNER, in_hand: bool = False) -> str:
    """Build the name line, with mana cost right-aligned for hand non-lands."""
    d = card.definition
    if in_hand and not d.is_land and d.mana_cost:
        cost = _compact_mana(d.mana_cost)
        # Space needed: name + at least 1 space + cost
        max_name = inner_width - len(cost) - 1
        if max_name >= 4:
            name = _truncate(card.name, max_name)
            return f"{name} {cost}".ljust(inner_width)
    return _truncate(card.name, inner_width)


def _stats_line(card: CardInstance, in_hand: bool = False, inner_width: int = CARD_INNER) -> str:
    """Build the inner stats line for a mini card."""
    d = card.definition
    if d.is_creature:
        p = int(d.power or "0") + card.counters.get("p1p1", 0)
        t = int(d.toughness or "0") + card.counters.get("p1p1", 0)
        sick = " ⏳" if card.sick else ""
        core = f"⚔ {p}/{t}{sick}"
    elif d.is_planeswalker:
        loy = card.counters.get("loyalty", d.loyalty or "?")
        core = f"✦ [{loy}]"
    elif in_hand and (d.is_instant or d.is_sorcery):
        core = f"★ {'instant' if d.is_instant else 'sorcery'}"
    elif d.is_artifact:
        core = "⚙"
    elif d.is_enchantment:
        core = "✧"
    elif d.is_land:
        core = "◆"
    else:
        core = _get_type_icon(card)

    # Append visible counters for battlefield cards (wider cards have room)
    if not in_hand and inner_width > CARD_INNER:
        visible = {k: v for k, v in card.counters.items() if k not in _HIDDEN_COUNTERS and v}
        if visible:
            counter_str = " ".join(f"{k}:{v}" for k, v in visible.items())
            core += f" ✧{counter_str}"

    # Pad / truncate to inner width
    if len(core) > inner_width:
        core = core[:inner_width]
    return core.ljust(inner_width)


def _render_mini_card(
    card: CardInstance,
    is_tapped: bool = False,
    face_down: bool = False,
    in_hand: bool = False,
    inner_width: int = CARD_INNER,
) -> list[str]:
    """Return 4 strings (top/name/stats/bot) with Rich markup for one mini card."""
    color = _get_card_color(card)
    dash = "─" * inner_width
    fill = "░" * inner_width

    if face_down:
        return [
            f"[{color}]┌{dash}┐[/{color}]",
            f"[{color}]│[/{color}][dim]{fill}[/dim][{color}]│[/{color}]",
            f"[{color}]│[/{color}][dim]{fill}[/dim][{color}]│[/{color}]",
            f"[{color}]└{dash}┘[/{color}]",
        ]

    # Content width is inner_width - 1 to account for the leading space
    content_w = inner_width - 1
    name_str = _name_line(card, inner_width=content_w, in_hand=in_hand)
    stats = _stats_line(card, in_hand=in_hand, inner_width=content_w)

    if is_tapped:
        tdash = "┄" * inner_width
        return [
            f"[{color} dim]┌{tdash}┐[/{color} dim]",
            f"[{color} dim]┊[/{color} dim] {name_str}[{color} dim]┊[/{color} dim]",
            f"[{color} dim]┊[/{color} dim] {stats}[{color} dim]┊[/{color} dim]",
            f"[{color} dim]└{tdash}┘[/{color} dim]",
        ]

    return [
        f"[{color}]┌{dash}┐[/{color}]",
        f"[{color}]│[/{color}] {name_str}[{color}]│[/{color}]",
        f"[{color}]│[/{color}] {stats}[{color}]│[/{color}]",
        f"[{color}]└{dash}┘[/{color}]",
    ]


def _render_card_row(
    cards: list[CardInstance],
    face_down: bool = False,
    in_hand: bool = False,
    width: int = 0,
    inner_width: int = CARD_INNER,
    max_per_row: int = 0,
) -> list[str]:
    """Render a horizontal row of mini cards, centered in `width`.

    If max_per_row > 0 and there are more cards than that, wraps into
    multiple rows.
    """
    if not cards:
        return []

    card_total_w = inner_width + 2  # total width including border chars

    # Split into chunks if max_per_row is set
    if max_per_row > 0 and len(cards) > max_per_row:
        all_lines: list[str] = []
        for start in range(0, len(cards), max_per_row):
            chunk = cards[start:start + max_per_row]
            all_lines.extend(
                _render_card_row(chunk, face_down=face_down, in_hand=in_hand,
                                 width=width, inner_width=inner_width, max_per_row=0)
            )
        return all_lines

    rendered = [
        _render_mini_card(c, is_tapped=c.tapped, face_down=face_down,
                          in_hand=in_hand, inner_width=inner_width)
        for c in cards
    ]

    num_lines = len(rendered[0])
    lines = [""] * num_lines
    for i, mc in enumerate(rendered):
        sep = "  " if i > 0 else ""
        for j in range(num_lines):
            lines[j] += sep + mc[j]

    # Center the row if width is given
    if width > 0:
        vis_w = len(cards) * card_total_w + (len(cards) - 1) * 2
        pad = max(0, (width - vis_w) // 2)
        pad_str = " " * pad
        lines = [pad_str + l for l in lines]

    return lines


# ── Phase bar ────────────────────────────────────────────────────────

def _render_phase_bar(phase: Phase) -> str:
    """Return a Rich-markup phase tracker string."""
    parts = []
    for p in PHASE_BAR_PHASES:
        name = PHASE_BAR_NAMES[p]
        is_active = (phase == p) or (p == Phase.BEGIN_COMBAT and phase in _COMBAT_PHASES)
        if is_active:
            parts.append(f"[bold bright_white]●{name}[/bold bright_white]")
        else:
            parts.append(f"[dim]{name}[/dim]")
    return " ─ ".join(parts)


# ── Info bar ─────────────────────────────────────────────────────────

def _life_color(life: int) -> str:
    if life <= 5:
        return "red"
    if life <= 10:
        return "yellow"
    return "green"


def _mana_pool_str(player) -> str:
    """Return a compact mana pool string like 'B2C1' or empty if pool is empty."""
    pool = player.mana_pool
    if pool.total() == 0:
        return ""
    parts = []
    for letter, attr in [("W", "white"), ("U", "blue"), ("B", "black"),
                          ("R", "red"), ("G", "green"), ("C", "colorless")]:
        val = getattr(pool, attr)
        if val > 0:
            parts.append(f"{letter}{val}")
    return "".join(parts)


def _render_info_bar(player, is_opponent: bool = False) -> str:
    """Return Rich markup for a player's stat line."""
    lc = _life_color(player.life)
    parts = [
        f"[{lc} bold]♥ {player.life}[/{lc} bold]",
    ]

    # Mana pool (when non-empty)
    mana = _mana_pool_str(player)
    if mana:
        parts.append(f"[bright_cyan]Mana {mana}[/bright_cyan]")

    parts.append(f"[bright_black]Lib {len(player.library)}[/bright_black]")

    # Graveyard with top card names
    gy = player.graveyard
    gy_count = len(gy)
    if gy_count > 0:
        top_names = [c.name for c in gy[-3:]]
        top_names.reverse()  # most recent first
        gy_str = ", ".join(top_names)
        parts.append(f"[bright_black]GY {gy_count}: {gy_str}[/bright_black]")
    else:
        parts.append(f"[bright_black]GY 0[/bright_black]")

    if is_opponent:
        parts.append(f"[bright_black]Hand {player.hand_size}[/bright_black]")
    return "   ".join(parts)


# ── Full board render ────────────────────────────────────────────────

def render_board(state: GameState, width: int | None = None) -> str:
    """Render the full game board as a string with Rich markup."""
    w = width or _term_width()
    inner = w - 4  # space inside the frame borders + padding

    # Calculate max cards per row for battlefield (wider cards)
    bf_max = max(3, (w - 4) // (CARD_W_BF + 2))

    p1 = state.players[0]  # pilot (bottom)
    p2 = state.players[1]  # opponent (top)
    active_id = state.active_player.id
    priority_id = state.priority_player.id

    lines: list[str] = []

    def frame_line(content: str) -> str:
        """Wrap content in the side borders: | content ... |"""
        return f"[dim]│[/dim]  {content}"

    def blank() -> str:
        return frame_line("")

    def _player_label(player, is_opponent: bool = False) -> str:
        """Build a player name label with turn/priority indicators."""
        is_active = player.id == active_id
        has_priority = player.id == priority_id
        info = _render_info_bar(player, is_opponent=is_opponent)
        arrow = "[bold bright_yellow]▶ [/bold bright_yellow]" if is_active else "  "
        prio = "  [bold bright_white]*[/bold bright_white]" if has_priority else ""
        name_style = "bold bright_white" if is_active else "bold cyan"
        return f"{arrow}[{name_style}]{player.name}[/{name_style}]{prio}      {info}"

    # ── Top border ──
    phase_bar = _render_phase_bar(state.phase)
    turn_label = f" Turn {state.turn_number} "
    lines.append(f"[bold]┌─{turn_label}── {phase_bar} {'─' * max(1, w - 70)}┐[/bold]")

    lines.append(blank())

    # ── Opponent section ──
    lines.append(frame_line(_player_label(p2, is_opponent=True)))
    lines.append(blank())

    # Opponent hand (face-down)
    if p2.hand:
        for line in _render_card_row(p2.hand, face_down=True, width=inner):
            lines.append(frame_line(line))
        lines.append(blank())

    # Opponent battlefield: creatures, other, lands (wider cards)
    bf2 = p2.battlefield
    creatures2 = [c for c in bf2 if c.definition.is_creature]
    other2 = [c for c in bf2 if not c.definition.is_land and not c.definition.is_creature]
    lands2 = [c for c in bf2 if c.definition.is_land]

    for group in [creatures2, other2, lands2]:
        if group:
            for line in _render_card_row(group, width=inner,
                                         inner_width=CARD_INNER_BF, max_per_row=bf_max):
                lines.append(frame_line(line))

    if not bf2:
        lines.append(frame_line("[dim](no permanents)[/dim]"))

    # ── Combat zone divider ──
    lines.append(blank())
    label = "  ⚔  COMBAT ZONE  ⚔  "
    label_len = len(label)
    eq_left = max(2, (inner - label_len) // 2)
    eq_right = max(2, inner - label_len - eq_left)
    lines.append(frame_line(
        f"[bold red]{'─' * eq_left}[/bold red]"
        f"[bold bright_red]{label}[/bold bright_red]"
        f"[bold red]{'─' * eq_right}[/bold red]"
    ))
    lines.append(blank())

    # ── Stack display (between combat zone and pilot battlefield) ──
    if state.stack:
        items = " → ".join(i.description for i in reversed(state.stack))
        lines.append(frame_line(
            f"[bold yellow]Stack ({len(state.stack)}):[/bold yellow] {items}"
        ))
        lines.append(blank())

    # ── Pilot section ──
    bf1 = p1.battlefield
    lands1 = [c for c in bf1 if c.definition.is_land]
    creatures1 = [c for c in bf1 if c.definition.is_creature]
    other1 = [c for c in bf1 if not c.definition.is_land and not c.definition.is_creature]

    for group in [lands1, other1, creatures1]:
        if group:
            for line in _render_card_row(group, width=inner,
                                         inner_width=CARD_INNER_BF, max_per_row=bf_max):
                lines.append(frame_line(line))

    if not bf1:
        lines.append(frame_line("[dim](no permanents)[/dim]"))

    lines.append(blank())
    lines.append(frame_line(_player_label(p1, is_opponent=False)))
    lines.append(blank())

    # Pilot hand (face-up, default narrow width, wrapping for narrow terminals)
    if p1.hand:
        hand_max = max(3, (w - 4) // (CARD_W + 2))
        for line in _render_card_row(p1.hand, face_down=False, in_hand=True, width=inner,
                                     max_per_row=hand_max):
            lines.append(frame_line(line))

    # ── Bottom border ──
    lines.append(blank())
    lines.append(f"[bold]└{'─' * (w - 2)}┘[/bold]")

    return "\n".join(lines)


# ── Screen helpers ───────────────────────────────────────────────────

def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


# ── Observer class ───────────────────────────────────────────────────

class VisualDisplay:
    """Hooks into game engine to show visual board state via Rich."""

    def __init__(self, delay: float = 0.15, only_main_phases: bool = False):
        self.delay = delay
        self.only_main_phases = only_main_phases
        self._last_log_idx = 0
        self._console = Console(force_terminal=True)

    def _print_board(self, state: GameState) -> None:
        board = render_board(state)
        self._console.print(board)

    def _print_log(self, state: GameState) -> None:
        new_entries = state.game_log[self._last_log_idx:]
        if new_entries:
            filtered = filter_log(new_entries)
            if filtered:
                w = _term_width()
                self._console.print(f"  [dim]{'─' * (w - 6)}[/dim]")
                for entry in filtered[-5:]:
                    self._console.print(f"  {entry}")
        self._last_log_idx = len(state.game_log)

    def on_phase_change(self, state: GameState) -> None:
        """Called when the phase changes."""
        if self.only_main_phases and state.phase not in (
            Phase.MAIN_1, Phase.MAIN_2, Phase.DECLARE_ATTACKERS,
            Phase.UPKEEP, Phase.CLEANUP,
        ):
            return

        clear_screen()
        self._print_board(state)
        self._print_log(state)

        if self.delay > 0:
            time.sleep(self.delay)

    def on_action(self, state: GameState, action_desc: str) -> None:
        """Called when an action is taken."""
        clear_screen()
        self._print_board(state)
        self._console.print(f"\n  [bold]>> {action_desc}[/bold]")
        self._print_log(state)

        if self.delay > 0:
            time.sleep(self.delay)

    def show_result(self, state: GameState) -> None:
        """Show final game result."""
        clear_screen()
        self._print_board(state)
        self._console.print()
        p1, p2 = state.players[0], state.players[1]
        if state.winner == "p1":
            self._console.print(f"  [bold green]{p1.name} WINS![/bold green]")
        elif state.winner == "p2":
            self._console.print(f"  [bold green]{p2.name} WINS![/bold green]")
        else:
            self._console.print(f"  [bold yellow]DRAW[/bold yellow]")
        self._console.print(f"  Turns: {state.turn_number}")
        self._console.print()
