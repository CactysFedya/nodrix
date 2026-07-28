#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Usage: scripts/release.sh 1.0.1}"
TAG="v$VERSION"

python scripts/bump_version.py "$VERSION"
python scripts/check_release.py --version-only

if ! grep -Eq "^## (\[$VERSION\]|$VERSION)( |$)" CHANGELOG.md; then
  echo "CHANGELOG.md must contain a section starting with: ## $VERSION or ## [$VERSION]" >&2
  exit 1
fi

git add pyproject.toml src/nodrix/__init__.py src/nodrix/native/CMakeLists.txt src/nodrix/project_templates.py CHANGELOG.md
git commit -m "Release Nodrix $VERSION"
git tag -s "$TAG" -m "Nodrix $VERSION" || git tag -a "$TAG" -m "Nodrix $VERSION"
git push origin main "$TAG"

echo "The Publish workflow will build wheels and upload Nodrix $VERSION to PyPI."
