# Contributing to Nodrix

Nodrix accepts bug fixes, documentation improvements, performance work, new typed-message codecs, and carefully scoped runtime features.

## Development setup

```bash
git clone https://github.com/CactysFedya/nodrix.git
cd nodrix
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,all]"
python setup.py build_ext --inplace
pytest -q
```

Native core tests:

```bash
make native-test
```

## Pull requests

Keep changes focused. Include a regression test for bug fixes and describe any effect on payload copies, queue behavior, ABI, message schemas, memory domains, or network compatibility.

Public Python API and Plugin ABI 1.0 are compatibility surfaces. Breaking changes require an explicit design discussion and a major release.

Do not commit generated wheels, native extension binaries, run artifacts, recordings, models, datasets, tokens, or passwords.
