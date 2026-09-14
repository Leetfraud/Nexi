Intent routing layer.

- router.py            → single entry point, decides Tier-1 vs Tier-2, applies confidence gate
- tier1_classifier.py  → scikit-learn rule-based model
- tier2_llm.py         → Ollama/Phi-3 Mini calls via requests
