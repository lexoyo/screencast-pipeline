"""Appelle un endpoint OpenAI-compatible et rend la réponse du modèle sur stdout.

Pour un fournisseur qu'opencode ne connaît pas : ni agent, ni outils, ni session —
une question, une réponse. Le prompt arrive sur stdin plutôt qu'en argument, parce
qu'il pèse couramment 200 Ko et contient tout ce qu'un shell interprète.
"""

import json
import sys
import urllib.request

base, key, model = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
prompt = sys.stdin.read()

body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
request = urllib.request.Request(
    f"{base}/chat/completions",
    data=body,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
)

try:
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.load(response)
except Exception as exc:
    detail = getattr(exc, "read", lambda: b"")()[:400].decode(errors="replace")
    print(f"brain.sh: {base} a refusé la requête ({exc}) {detail}", file=sys.stderr)
    sys.exit(1)

usage = data.get("usage") or {}
if usage:
    print(f"brain: {usage.get('prompt_tokens', '?')} jetons lus, "
          f"{usage.get('completion_tokens', '?')} écrits", file=sys.stderr)

answer = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
if not answer.strip():
    print(f"brain.sh: réponse vide de {model} ({json.dumps(data)[:300]})", file=sys.stderr)
    sys.exit(1)

sys.stdout.write(answer)
