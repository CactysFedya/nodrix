# Documentation development

The public site is built twice from the same repository:

```bash
rm -rf docs/_build/site
mkdir -p docs/_build/site/en/latest docs/_build/site/ru/latest
sphinx-build -W --keep-going -b html docs docs/_build/site/en/latest
sphinx-build -W --keep-going -b html docs/ru docs/_build/site/ru/latest
cp docs/_landing/index.html docs/_build/site/index.html
touch docs/_build/site/.nojekyll
python -m http.server 8000 --directory docs/_build/site
```

Open `http://localhost:8000/` and test both language selectors before pushing.
Historical `RELEASE_*.md` files intentionally remain outside the generated site.
