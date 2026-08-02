.PHONY: install test native-test build check clean

install:
	python -m pip install -e ".[dev,all]"
	python setup.py build_ext --inplace

test:
	pytest -q

native-test:
	cmake -S src/nodrix/native -B build/native -DCMAKE_BUILD_TYPE=Release
	cmake --build build/native --parallel 2
	ctest --test-dir build/native --output-on-failure

build: clean
	python -m build

check:
	python scripts/check_release.py --version-only
	python -m twine check dist/*

clean:
	rm -rf build dist wheelhouse .pytest_cache .ruff_cache *.egg-info src/*.egg-info
	rm -rf packages/*/build packages/*/dist packages/*/src/*.egg-info
	find src tests packages examples scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	find src packages -type f \( -name '*.so' -o -name '*.pyd' -o -name '*.dylib' \) -delete
