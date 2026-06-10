"""Gesprächslogik — validated Wenn/Dann rule tree (agent_configs.conversation_logic).

Shape (version 1):
    {"version": 1, "blocks": [Rule, ...]}
    Rule    = {id, branches: [Branch, ...]}                 (ordered; first=wenn)
    Branch  = {id, kind: wenn|sonst_wenn|sonst,
               conditions: [str, ...], condition_op: und|oder,   (absent for sonst)
               actions: [Action, ...]}
    Action  = {id, type: ask|say|goto|subrule, text?, target?, rule?}
              goto targets: schritt_2 | schritt_3 | abschluss
              subrule: one nested Rule (depth 1 only, its actions may not nest)

Hard limits keep the compiled prompt block bounded — exceeding any limit is a
422 with a German message (the UI surfaces it inline).
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

MAX_BLOCKS = 10
MAX_BRANCHES = 5
MAX_ACTIONS = 8
MAX_CONDITIONS = 4
MAX_TEXT = 200
MAX_TOTAL_NODES = 80
MAX_COMPILED_CHARS = 4000

GOTO_TARGETS = {"schritt_2", "schritt_3", "abschluss"}
GOTO_LABELS = {
    "schritt_2": "Schritt 2 (Daten aufnehmen)",
    "schritt_3": "Schritt 3 (Termin)",
    "abschluss": "zum Abschluss (Abschluss-Frage + Verabschiedung)",
}


class LogicError(ValueError):
    """Validation failure with a user-facing German message."""


class LogicAction(BaseModel):
    id: str | None = None
    type: str  # ask | say | goto | subrule
    text: str | None = None
    target: str | None = None
    rule: "LogicRule | None" = None
    model_config = {"extra": "ignore"}

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in ("ask", "say", "goto", "subrule"):
            raise ValueError(f"Unbekannter Aktions-Typ: {v}")
        return v


class LogicBranch(BaseModel):
    id: str | None = None
    kind: str = "wenn"  # wenn | sonst_wenn | sonst
    conditions: list[str] = []
    condition_op: str = "und"  # und | oder
    actions: list[LogicAction] = []
    model_config = {"extra": "ignore"}

    @field_validator("kind")
    @classmethod
    def _kind_ok(cls, v: str) -> str:
        if v not in ("wenn", "sonst_wenn", "sonst"):
            raise ValueError(f"Unbekannter Zweig-Typ: {v}")
        return v

    @field_validator("condition_op")
    @classmethod
    def _op_ok(cls, v: str) -> str:
        if v not in ("und", "oder"):
            raise ValueError("Bedingungs-Verknüpfung muss „und“ oder „oder“ sein.")
        return v


class LogicRule(BaseModel):
    id: str | None = None
    branches: list[LogicBranch] = []
    model_config = {"extra": "ignore"}


class ConversationLogic(BaseModel):
    version: int = 1
    blocks: list[LogicRule] = []
    model_config = {"extra": "ignore"}


LogicAction.model_rebuild()


def _count_nodes(rule: LogicRule) -> int:
    n = 1
    for br in rule.branches:
        n += 1 + len(br.conditions)
        for a in br.actions:
            n += 1
            if a.rule:
                n += _count_nodes(a.rule)
    return n


def _validate_rule(rule: LogicRule, *, depth: int) -> None:
    if len(rule.branches) > MAX_BRANCHES:
        raise LogicError(f"Höchstens {MAX_BRANCHES} Zweige pro Regel.")
    sonst_seen = False
    for br in rule.branches:
        if sonst_seen:
            raise LogicError("„Sonst“ muss der letzte Zweig einer Regel sein.")
        if br.kind == "sonst":
            sonst_seen = True
            if br.conditions:
                raise LogicError("Ein „Sonst“-Zweig darf keine Bedingungen haben.")
        else:
            if not [c for c in br.conditions if c.strip()]:
                raise LogicError("Jeder Wenn-/Sonst-wenn-Zweig braucht mindestens eine Bedingung.")
        if len(br.conditions) > MAX_CONDITIONS:
            raise LogicError(f"Höchstens {MAX_CONDITIONS} Bedingungen pro Zweig.")
        for c in br.conditions:
            if len(c) > MAX_TEXT:
                raise LogicError(f"Bedingungen dürfen höchstens {MAX_TEXT} Zeichen haben.")
        if len(br.actions) > MAX_ACTIONS:
            raise LogicError(f"Höchstens {MAX_ACTIONS} Aktionen pro Zweig.")
        for a in br.actions:
            if a.type in ("ask", "say"):
                if not (a.text or "").strip():
                    raise LogicError("Frage-/Hinweis-Aktionen brauchen einen Text.")
                if len(a.text or "") > MAX_TEXT:
                    raise LogicError(f"Aktions-Texte dürfen höchstens {MAX_TEXT} Zeichen haben.")
            elif a.type == "goto":
                if a.target not in GOTO_TARGETS:
                    raise LogicError("„Weiter zu“ muss Schritt 2, Schritt 3 oder Abschluss sein.")
            elif a.type == "subrule":
                if depth >= 1:
                    raise LogicError("Unterregeln können nicht weiter verschachtelt werden.")
                if not a.rule or not a.rule.branches:
                    raise LogicError("Eine Unterregel braucht mindestens einen Zweig.")
                _validate_rule(a.rule, depth=depth + 1)


def validate_conversation_logic(logic: ConversationLogic) -> None:
    """Raises LogicError (→ 422) when the tree violates a structural limit."""
    if len(logic.blocks) > MAX_BLOCKS:
        raise LogicError(f"Höchstens {MAX_BLOCKS} Regeln möglich.")
    total = 0
    for rule in logic.blocks:
        if not rule.branches:
            raise LogicError("Jede Regel braucht mindestens einen Wenn-Zweig.")
        if rule.branches[0].kind == "sonst":
            raise LogicError("Eine Regel kann nicht mit „Sonst“ beginnen.")
        _validate_rule(rule, depth=0)
        total += _count_nodes(rule)
    if total > MAX_TOTAL_NODES:
        raise LogicError(
            f"Die Gesprächslogik ist zu umfangreich ({total} Elemente, max. {MAX_TOTAL_NODES})."
        )


# ─── Deterministic compiler → numbered German prompt block ──────────────────
def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _join_conditions(br: LogicBranch) -> str:
    conds = [_clean(c) for c in br.conditions if _clean(c)]
    sep = " UND " if br.condition_op == "und" else " ODER "
    return sep.join(conds)


def _branch_header(br: LogicBranch) -> str:
    if br.kind == "sonst":
        return "Sonst:"
    if br.kind == "sonst_wenn":
        return f"Sonst, wenn {_join_conditions(br)}:"
    return f"Wenn {_join_conditions(br)}:"


def _action_line(a: LogicAction) -> str | None:
    if a.type == "ask":
        return f"Frage: „{_clean(a.text)}“"
    if a.type == "say":
        return f"Sage/Hinweis: {_clean(a.text)}"
    if a.type == "goto":
        return f"Gehe danach direkt zu {GOTO_LABELS.get(a.target or '', a.target or '')}."
    return None


def _branch_has_content(br: LogicBranch) -> bool:
    return any(
        (_action_line(a) is not None) or (a.type == "subrule" and a.rule and a.rule.branches)
        for a in br.actions
    )


def compile_conversation_logic(logic: ConversationLogic) -> str:
    """Rule tree → numbered German block in the style of the hand-written
    Gesprächsführung sections:

        1. Wenn <Bedingung>:
           1.1 Frage: „…“
           Sonst, wenn <Bedingung>:
           1.2 Sage/Hinweis: …
           1.3 Wenn <Unter-Bedingung>:   (subrule branch)
               - Frage: „…“

    The action counter (n.k) runs across all branches of a rule, so every line
    stays uniquely addressable for the voice model. Empty tree/branches → "".
    """
    out: list[str] = []
    n = 0
    for rule in logic.blocks:
        branches = [b for b in rule.branches if _branch_has_content(b)]
        if not branches:
            continue
        n += 1
        sub = 0
        for idx, br in enumerate(branches):
            header = _branch_header(br)
            out.append(f"{n}. {header}" if idx == 0 else f"   {header}")
            for a in br.actions:
                if a.type == "subrule" and a.rule:
                    for sbr in a.rule.branches:
                        s_lines = [_action_line(x) for x in sbr.actions]
                        s_lines = [x for x in s_lines if x]
                        if not s_lines:
                            continue
                        sub += 1
                        out.append(f"   {n}.{sub} {_branch_header(sbr)}")
                        out.extend(f"       - {x}" for x in s_lines)
                    continue
                line = _action_line(a)
                if line:
                    sub += 1
                    out.append(f"   {n}.{sub} {line}")
    return "\n".join(out).strip()
