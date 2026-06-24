## 1. Simplify DSPy Pipeline

- [ ] 1.1 Remove QueryAnalyzer call in `_forward_impl()` — use raw question directly
- [ ] 1.2 Remove ContextAssembler call in `_forward_impl()` — use all chunks directly
- [ ] 1.3 Verify ChainOfThought still produces `reasoning` output (CoT display preserved)
- [ ] 1.4 Update unit tests for `module.py` (remove QueryAnalyzer/ContextAssembler mock expectations)
- [ ] 1.5 Update integration tests for DSPy pipeline behavior
- [ ] 1.6 Run full test suite (unit + integration) — ensure zero regressions
- [ ] 1.7 Run lint + typecheck on modified files
