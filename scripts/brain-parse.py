"""Lit le flux d'événements d'opencode et n'en garde que la réponse du modèle.

Séparé de brain.sh parce qu'un parseur inline dans un `python3 -c '…'` ne peut pas
contenir d'apostrophe, ce qui interdit d'écrire du français correct dans ses messages.

Trois choses sortent d'ici : la réponse sur stdout (c'est elle que le pipeline lit),
un décompte des jetons et du coût sur stderr, et un diagnostic quand la réponse est
vide — le cas le plus déroutant, puisque rien ne distingue à l'œil nu un modèle qui a
échoué d'un modèle qui a passé vingt minutes à réfléchir sans jamais répondre.
"""

import json
import sys

parts: dict[str, str] = {}      # id -> texte ; un part réémis en streaming ne compte qu'une fois
reasoning: dict[str, str] = {}  # idem pour le raisonnement : jamais renvoyé, mais mesuré
errors: list[str] = []
used = {"in": 0, "out": 0, "reasoning": 0, "cost": 0.0}
served = ""  # le modèle qui a réellement répondu, tel qu'opencode le nomme

def _find_model(node) -> str:
    """Cherche modelID/providerID n'importe où dans un événement, sans en présumer la forme."""
    if isinstance(node, dict):
        if node.get("modelID"):
            provider = node.get("providerID")
            variant = node.get("variant")
            name = f"{provider}/{node['modelID']}" if provider else str(node["modelID"])
            return f"{name} ({variant})" if variant and variant != "default" else name
        for value in node.values():
            found = _find_model(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_model(value)
            if found:
                return found
    return ""


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue

    if not served:
        # Quand BRAIN_MODEL est vide, opencode prend le dernier modèle choisi dans son
        # TUI — un état invisible depuis ici. Il le nomme dans ses événements : c'est la
        # seule façon de savoir, six mois plus tard, qui a décidé un montage.
        found = _find_model(event)
        if found:
            served = found

    if event.get("type") == "error":
        # opencode écrit ses erreurs dans le flux, pas sur stderr : sans ça, un modèle
        # inconnu ou un quota dépassé ressemble à une réponse vide.
        errors.append(str((event.get("error") or {}).get("data", {}).get("message", "?")))
        continue

    part = event.get("part") or {}
    kind = part.get("type")
    if event.get("type") == "text" and kind == "text":
        parts[part.get("id")] = part.get("text", "")
    elif kind == "reasoning":
        reasoning[part.get("id")] = part.get("text", "")
    elif kind == "step-finish":
        tokens = part.get("tokens") or {}
        used["in"] += tokens.get("input", 0)
        used["out"] += tokens.get("output", 0)
        used["reasoning"] += tokens.get("reasoning", 0)
        used["cost"] += part.get("cost") or 0

answer = "".join(parts.values())
thought = "".join(reasoning.values())

note = f"{served or 'modèle inconnu'} — {used['in']} jetons lus, {used['out']} écrits"
if used["reasoning"]:
    note += f", dont {used['reasoning']} de raisonnement"
elif thought:
    note += f", plus {len(thought) // 1024} Ko de raisonnement"
if used["cost"]:
    note += f" — {used['cost']:.4f} $"
print(f"brain: {note}", file=sys.stderr)

if not answer.strip():
    detail = " ; ".join(errors)
    if not detail and thought:
        # Le cas Qwen3.8-Max : vingt minutes de réflexion, zéro caractère de réponse.
        detail = (f"{len(thought) // 1024} Ko de raisonnement et aucune réponse — c'est un "
                  "modèle à raisonnement, coupe-le (--variant minimal, enable_thinking:false) "
                  "ou prends-en un autre")
    print(f"brain.sh: rien reçu ({detail or 'réponse vide'}). Le modèle s'écrit "
          "provider/modèle, p.ex. openrouter/z-ai/glm-5.2.", file=sys.stderr)
    sys.exit(1)

sys.stdout.write(answer)
