#!/usr/bin/env bash
# Bump patch version, build, upload to PyPI. No git.
# Usage: ./release.sh                  -> bump patch (0.3.9 -> 0.3.10)
#        ./release.sh 0.4.0            -> set explicit version
# Needs: PYPI_API_TOKEN env var.
set -euo pipefail

cd "$(dirname "$0")"

[[ -n "${PYPI_API_TOKEN:-}" ]] || { echo "PYPI_API_TOKEN not set"; exit 1; }

current=$(grep -oP '^version = "\K[^"]+' pyproject.toml)
if [[ $# -ge 1 ]]; then
    new="$1"
else
    IFS='.' read -r maj min pat <<< "$current"
    new="${maj}.${min}.$((pat + 1))"
fi

echo ">> bump $current -> $new"
sed -i "s/^version = \"${current}\"/version = \"${new}\"/" pyproject.toml

echo ">> build"
rm -rf dist/ build/
python3 -m build --no-isolation

echo ">> upload"
twine upload -u __token__ -p "$PYPI_API_TOKEN" "dist/kivi_ai-${new}"*

echo ">> done: https://pypi.org/project/kivi-ai/${new}/"
