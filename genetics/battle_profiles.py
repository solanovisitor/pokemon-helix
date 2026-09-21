"""Immutable game rules derived from accepted fictional expression, never DNA.

This policy makes no inference and mutates no store. A native package retains
its resulting bytes and explicitly migrates saved progress before using them.
Changing a policy requires a new version; accepted profiles are not rewritten.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from genetics.expression import ExpressionBody, TRAIT_ANCHORS
from genetics.primers import VirtualGenome, canonical, digest, hash_id

BATTLE_POLICY_VERSION = "aurora-expression-battle-v1"
EXPRESSION_VERSION = "aurora-adventure-expression-v1"
STAT_ORDER = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
STAT_INPUTS = {
    "hp": ("body_size", "body_protection"),
    "attack": ("appendage_development", "territoriality"),
    "defense": ("body_protection", "camouflage"),
    "speed": ("elongation", "nocturnality"),
    "sp_attack": ("bioluminescence", "curiosity"),
    "sp_defense": ("cold_tolerance", "aurora_sensitivity"),
}
LEGAL_TYPES = frozenset(("TYPE_NORMAL", "TYPE_WATER", "TYPE_ICE", "TYPE_PSYCHIC"))
LEGAL_MOVES = frozenset(("MOVE_TACKLE", "MOVE_WATER_GUN", "MOVE_QUICK_ATTACK", "MOVE_CONFUSION", "MOVE_SWIFT", "MOVE_GROWL", "MOVE_HARDEN"))
TRAIT_NAMES_PT = dict(zip(TRAIT_ANCHORS, (
    "Tamanho", "Corpo alongado", "Nadadeiras e membros", "Proteção do corpo",
    "Cor", "Contraste", "Desenhos do corpo", "Luz própria", "Afinidade com água",
    "Conforto no frio", "Hábitos noturnos", "Camuflagem", "Curiosidade",
    "Sociabilidade", "Defesa do território", "Percepção de sinais")))
STAT_NAMES_PT = {"hp": "Pontos de vida", "attack": "Ataque", "defense": "Defesa", "speed": "Velocidade",
                 "sp_attack": "Ataque especial", "sp_defense": "Defesa especial"}
TYPE_NAMES_PT = {"TYPE_NORMAL": "Normal", "TYPE_WATER": "Água", "TYPE_ICE": "Gelo", "TYPE_PSYCHIC": "Psíquico"}
MOVE_NAMES_PT = {"MOVE_TACKLE": "Investida", "MOVE_WATER_GUN": "Jato de água", "MOVE_QUICK_ATTACK": "Ataque rápido",
                 "MOVE_CONFUSION": "Confusão", "MOVE_SWIFT": "Estrelas", "MOVE_GROWL": "Rosnado", "MOVE_HARDEN": "Endurecer"}


def _bound_expression(individual: dict, expression: dict, expression_sha256: str) -> dict:
    if not isinstance(individual, dict) or not isinstance(expression, dict):
        raise ValueError("individual and accepted expression objects required")
    if len(canonical(individual)) > 32768 or len(canonical(expression)) > 65536:
        raise ValueError("individual or accepted expression exceeds contract bounds")
    hash_id(expression_sha256)
    for key in ("id", "adventure_id", "genome_sha256"):
        hash_id(individual.get(key))
    if (type(individual.get("schema_version")) is not int or individual["schema_version"] != 1
            or VirtualGenome.from_dict(individual.get("genotype")).sha256 != individual["genome_sha256"]):
        raise ValueError("unsupported individual schema or changed genome")
    if (type(expression.get("schema_version")) is not int or expression["schema_version"] != 1
            or expression.get("individual_id") != individual["id"]
            or expression.get("adventure_id") != individual["adventure_id"]
            or expression.get("genome_sha256") != individual["genome_sha256"]
            or sha256(canonical(expression)).hexdigest() != expression_sha256):
        raise ValueError("accepted expression checksum or individual binding changed")
    return ExpressionBody.model_validate(expression.get("expression")).model_dump(mode="json")


def derive_battle_profile(individual: dict, expression: dict, *, expression_sha256: str) -> dict:
    """Apply frozen game balancing to validated model-authored expression scores.

    The input checksum is the exact accepted profile object checksum. The full
    individual is bound separately, including primer ancestry and pedigree.
    """
    body = _bound_expression(individual, expression, expression_sha256)
    scores = body["scores"]
    stats = {stat: 40 + sum(scores[trait] for trait in traits) // 4 for stat, traits in STAT_INPUTS.items()}
    primary = "TYPE_WATER" if scores["aquatic_affinity"] >= 50 else "TYPE_NORMAL"
    secondary = ("TYPE_ICE" if scores["cold_tolerance"] >= 75 else
                 "TYPE_PSYCHIC" if scores["aurora_sensitivity"] >= 75 else primary)
    types = [primary] if secondary == primary else [primary, secondary]
    moves = ["MOVE_TACKLE", "MOVE_WATER_GUN" if scores["aquatic_affinity"] >= 50 else "MOVE_QUICK_ATTACK",
             "MOVE_CONFUSION" if scores["aurora_sensitivity"] >= 60 else "MOVE_SWIFT",
             "MOVE_GROWL" if scores["sociability"] >= 50 else "MOVE_HARDEN"]
    trait_effects = {}
    for trait, score in scores.items():
        targets = [stat for stat, traits in STAT_INPUTS.items() if trait in traits]
        rules = [f"{stat}=40+({'+'.join(STAT_INPUTS[stat])})//4" for stat in targets]
        explanation = [f"Ajuda a definir {STAT_NAMES_PT[stat].lower()} ({stats[stat]})." for stat in targets]
        if trait == "aquatic_affinity":
            rules += ["primary_type: WATER at >=50, otherwise NORMAL", "move2: WATER_GUN at >=50, otherwise QUICK_ATTACK"]
            explanation += [f"Escolhe o tipo {TYPE_NAMES_PT[primary]} e o golpe {MOVE_NAMES_PT[moves[1]]}."]
        if trait == "cold_tolerance":
            rules += ["secondary_type: ICE at >=75; takes precedence over PSYCHIC"]
            explanation += ["A partir de 75, acrescenta o tipo Gelo."]
        if trait == "aurora_sensitivity":
            rules += ["secondary_type: PSYCHIC at >=75 when cold_tolerance<75", "move3: CONFUSION at >=60, otherwise SWIFT"]
            explanation += [f"Escolhe o golpe {MOVE_NAMES_PT[moves[2]]}. A partir de 75, acrescenta Psíquico se não houver tipo Gelo."]
        if trait == "sociability":
            rules += ["move4: GROWL at >=50, otherwise HARDEN"]
            explanation += [f"Define como se protege: {MOVE_NAMES_PT[moves[3]]}."]
        if not rules:
            explanation = ["Faz parte da aparência guardada. Cores e desenhos não mudam força, tipos ou golpes."]
        trait_effects[trait] = {"name_pt": TRAIT_NAMES_PT[trait], "score": score,
                                "role": "combat" if rules else "cosmetic", "rules": rules,
                                "explanation_pt": " ".join(explanation)}
    payload = {
        "schema_version": 1, "policy_version": BATTLE_POLICY_VERSION,
        "individual_id": individual["id"], "adventure_id": individual["adventure_id"],
        "individual_sha256": digest(individual), "genome_sha256": individual["genome_sha256"],
        "expression_sha256": expression_sha256, "expression_version": EXPRESSION_VERSION,
        "base_stats": stats, "types": types, "moves": moves,
        "ability": "ABILITY_ILLUMINATE", "growth_rate": "GROWTH_MEDIUM_FAST",
        "trait_effects": trait_effects,
        "descriptive_roles": {
            "silhouette": "A forma visível acompanha a arte aceita; os números de tamanho e proteção definem seus efeitos.",
            "palette": "As cores identificam este companheiro; não alteram a batalha.",
            "patterns": "As marcas identificam este companheiro; não alteram a batalha.",
            "inherited_cues": "Mostram semelhanças da família; não somam bônus além das características acima.",
            "rationale": "Explica a interpretação criativa; não é uma regra de combate.",
            "ability": "Illuminate é a habilidade original mantida. Esta ficha não cria habilidades ou efeitos passivos novos.",
        },
        "migration": {"policy": "explicit-save-migration-required", "preserve": ["experience", "level", "learned_moves", "evs", "ivs", "nature"],
                      "new_moves": "initial-creation-only", "growth_curve": "unchanged-medium-fast",
                      "revisions": "new-immutable-profile-and-explicit-migration"},
    }
    return payload | {"profile_sha256": digest(payload)}


def validate_battle_profile(profile: dict, *, individual: dict, expression: dict, expression_sha256: str) -> dict:
    """Reject tampering even when an attacker recalculates the outer checksum."""
    if not isinstance(profile, dict) or len(canonical(profile)) > 32768:
        raise ValueError("bounded battle profile object required")
    expected = derive_battle_profile(individual, expression, expression_sha256=expression_sha256)
    if canonical(profile) != canonical(expected):
        raise ValueError("battle profile differs from its bound versioned expression policy")
    return json.loads(canonical(expected))


def native_battle_fields(profile: dict) -> dict:
    """Bounded symbols for C export; validate complete binding before calling."""
    if (not isinstance(profile, dict) or type(profile.get("schema_version")) is not int or profile["schema_version"] != 1
            or profile.get("policy_version") != BATTLE_POLICY_VERSION
            or profile.get("profile_sha256") != digest({k: v for k, v in profile.items() if k != "profile_sha256"})):
        raise ValueError("invalid native battle profile checksum/version")
    stats, types, moves = profile.get("base_stats"), profile.get("types"), profile.get("moves")
    if (not isinstance(stats, dict) or set(stats) != set(STAT_ORDER)
            or any(type(value) is not int or not 40 <= value <= 90 for value in stats.values())
            or not isinstance(types, list) or not 1 <= len(types) <= 2 or any(not isinstance(value, str) for value in types)
            or len(set(types)) != len(types)
            or any(value not in LEGAL_TYPES for value in types)
            or not isinstance(moves, list) or len(moves) != 4 or any(not isinstance(value, str) for value in moves)
            or len(set(moves)) != 4
            or any(value not in LEGAL_MOVES for value in moves)
            or profile.get("growth_rate") != "GROWTH_MEDIUM_FAST" or profile.get("ability") != "ABILITY_ILLUMINATE"):
        raise ValueError("unsupported native stats, types, moves, growth or ability")
    return {"base_stats": [stats[key] for key in STAT_ORDER], "types": list(types) if len(types) == 2 else types * 2, "moves": list(moves)}


def save_battle_profile(profile: dict, path: str | Path) -> None:
    """Retain a validated contract without replacing an existing revision."""
    native_battle_fields(profile)
    from genetics.adventures import _write_once
    _write_once(Path(path), canonical(profile))
