# Contributing to documentation

## Rules

- Document only behavior present in the target branch.
- Use `Plyctl`, `plyctl`, and `plyctl.dev/v2` for new public examples.
- Explain compatibility identifiers instead of silently rewriting them.
- Put tutorials, how-to guides, concepts, and references in their matching sections.
- Every command example should be runnable or clearly marked as schematic.
- Keep English and Russian page paths aligned where practical.
- Do not add one navigation page per patch release; update the current release page and GitHub release notes.

## Local build

```bash
python -m pip install -e '.[docs]'
sphinx-build -W --keep-going -b html docs docs/_build/site/en/latest
sphinx-build -W --keep-going -b html docs/ru docs/_build/site/ru/latest
```

Local building is optional for simple Markdown edits. The `Documentation` GitHub Actions workflow builds both languages and treats warnings as errors.

## Pull request checklist

- English build passes.
- Russian build passes.
- New toctree entries resolve.
- Code examples match current APIs.
- Branch/version labels are correct.
- No legacy release pages leak into navigation or search.
