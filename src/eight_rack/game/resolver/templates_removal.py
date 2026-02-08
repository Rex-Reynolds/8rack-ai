"""Tier 2 templates for removal spells (used by both 8 Rack and opponents)."""

from __future__ import annotations

from ..actions import Action, ActionResult
from ..state import CardInstance, GameState, Zone


class RemovalTemplatesMixin:
    """Templates for removal and burn spells."""

    def _register_removal_templates(self) -> None:
        self._templates["Fatal Push"] = self._resolve_fatal_push
        self._templates["Bloodchief's Thirst"] = self._resolve_bloodchiefs_thirst
        self._templates["Sheoldred's Edict"] = self._resolve_sheoldreds_edict
        self._templates["Lightning Bolt"] = self._resolve_lightning_bolt
        self._templates["Dismember"] = self._resolve_dismember

    def _resolve_fatal_push(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if not action.targets:
            return ActionResult(success=False, message="No target for Fatal Push")
        for p in state.players:
            target = p.find_card(action.targets[0])
            if target and target.zone == Zone.BATTLEFIELD and target.definition.is_creature:
                if target.definition.cmc <= 2:
                    target.zone = Zone.GRAVEYARD
                    return ActionResult(
                        success=True,
                        message=f"Fatal Push destroys {target.name}",
                        state_changes=[f"{target.name} destroyed"],
                        tier_used=2,
                    )
                return ActionResult(success=False, message=f"{target.name} CMC too high for Fatal Push")
        return ActionResult(success=False, message="Invalid target for Fatal Push")

    def _resolve_bloodchiefs_thirst(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if not action.targets:
            return ActionResult(success=False, message="No target")
        kicked = action.choices.get("kicked", "false") == "true"
        for p in state.players:
            target = p.find_card(action.targets[0])
            if target and target.zone == Zone.BATTLEFIELD:
                if target.definition.is_creature or target.definition.is_planeswalker:
                    if kicked or target.definition.cmc <= 2:
                        target.zone = Zone.GRAVEYARD
                        return ActionResult(
                            success=True,
                            message=f"Bloodchief's Thirst destroys {target.name}",
                            state_changes=[f"{target.name} destroyed"],
                            tier_used=2,
                        )
        return ActionResult(success=False, message="Invalid target")

    def _resolve_sheoldreds_edict(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        import random
        opponent = state.opponent_of(action.player_id)
        mode = action.choices.get("mode", "creature")
        if mode == "creature":
            creatures = [c for c in opponent.battlefield if c.definition.is_creature]
            if creatures:
                sac = random.choice(creatures)
                sac.zone = Zone.GRAVEYARD
                return ActionResult(
                    success=True,
                    message=f"Sheoldred's Edict: {opponent.name} sacrifices {sac.name}",
                    tier_used=2,
                )
        elif mode == "planeswalker":
            pws = [c for c in opponent.battlefield if c.definition.is_planeswalker]
            if pws:
                sac = random.choice(pws)
                sac.zone = Zone.GRAVEYARD
                return ActionResult(
                    success=True,
                    message=f"Sheoldred's Edict: {opponent.name} sacrifices {sac.name}",
                    tier_used=2,
                )
        return ActionResult(
            success=True,
            message="Sheoldred's Edict: nothing to sacrifice",
            tier_used=2,
        )

    def _resolve_lightning_bolt(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        if action.targets:
            target_id = action.targets[0]
            if target_id.startswith("player:"):
                pid = target_id.split(":")[1]
                target_player = state.get_player(pid)
                target_player.life -= 3
                return ActionResult(
                    success=True,
                    message=f"Lightning Bolt deals 3 to {target_player.name}",
                    state_changes=[f"{target_player.name} life: {target_player.life}"],
                    tier_used=2,
                )
            for p in state.players:
                target = p.find_card(target_id)
                if target and target.zone == Zone.BATTLEFIELD:
                    target.damage_marked += 3
                    toughness = int(target.definition.toughness or "0")
                    if target.damage_marked >= toughness:
                        target.zone = Zone.GRAVEYARD
                    return ActionResult(
                        success=True,
                        message=f"Lightning Bolt deals 3 to {target.name}",
                        tier_used=2,
                    )
        opponent = state.opponent_of(action.player_id)
        opponent.life -= 3
        return ActionResult(
            success=True,
            message=f"Lightning Bolt deals 3 to {opponent.name}",
            state_changes=[f"{opponent.name} life: {opponent.life}"],
            tier_used=2,
        )

    def _resolve_dismember(self, state: GameState, action: Action, card: CardInstance) -> ActionResult:
        player = state.get_player(action.player_id)
        player.life -= 4
        if action.targets:
            for p in state.players:
                target = p.find_card(action.targets[0])
                if target and target.zone == Zone.BATTLEFIELD and target.definition.is_creature:
                    toughness = int(target.definition.toughness or "0")
                    if toughness <= 5:
                        target.zone = Zone.GRAVEYARD
                        return ActionResult(
                            success=True,
                            message=f"Dismember: {target.name} gets -5/-5 (destroyed)",
                            state_changes=[f"{target.name} destroyed", f"{player.name} life: {player.life}"],
                            tier_used=2,
                        )
                    else:
                        target.damage_marked += 5
                        return ActionResult(
                            success=True,
                            message=f"Dismember: {target.name} gets -5/-5",
                            state_changes=[f"{player.name} life: {player.life}"],
                            tier_used=2,
                        )
        return ActionResult(success=True, message="Dismember (no target)", tier_used=2)
