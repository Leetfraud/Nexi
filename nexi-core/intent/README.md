# Intent routing

Transcript in, `Action` out. Entry point is `router.route(text)`, or
`router.route_detailed(text)` if you also want to know which tier answered.

- `router.py` — wake word, tier selection, confidence gate
- `tier1_classifier.py` — TF-IDF + logistic regression over a seed corpus, plus regex slot extraction
- `tier2_llm.py` — Ollama call via `requests`, JSON-constrained

## Routing

1. Strip a leading greeting and wake word.
2. Tier 1 classifies. If it is confident (≥ `TIER1_THRESHOLD`, 0.55) and
   extracted the slot its type needs, that answer is used.
3. Otherwise Tier 2 gets a turn. If Ollama is unreachable, Tier 1's answer
   stands rather than failing the command.
4. Anything below `CONFIDENCE_FLOOR` (0.5) gets `requires_confirmation`.

Diagnostics (`tier`, `wake_word`) live on `router.Routed`, not on `Action` —
the mirrored contract carries only what nexi-ui executes.

## Wake word

Whisper does not know the name and renders it inconsistently — "Nexzy",
"Nexy", and "next" all showed up in real mic tests of "Hey Nexi". The wake word
is therefore matched by similarity (`difflib`, ratio ≥ 0.6), not equality. A
literal `"nexi" in text` check would miss most takes.

The wake word is currently optional: a bare "open chrome" still routes. It is
recorded on `Routed.wake_word` so it can be enforced later without changing the
schema.

## Tier 2 model

`Context.txt` specifies Phi-3 Mini. The default here is `gemma3:4b` because
that is what is pulled locally. Override per machine:

```sh
export NEXI_OLLAMA_MODEL=phi3:mini      # default gemma3:4b
export NEXI_OLLAMA_URL=http://localhost:11434
export NEXI_OLLAMA_TIMEOUT=30
```

Measured latency on an M-series Mac: ~2s warm, ~7.5s on the first call while
the model loads — inside the <8s budget, but the first call is close to it.

## Run it

```sh
.venv/bin/python -m pip install -r requirements-intent.txt
.venv/bin/python intent_demo.py --text "open chrome"   # no microphone needed
.venv/bin/python intent_demo.py                        # speak instead
.venv/bin/python intent_demo.py --text "..." --no-tier2  # Tier 1 only
```
