#!/bin/sh
# Run the tests. They need python 3 with markdown and pyyaml (plus git, sqlite3 and openssl):
#   tests/run.sh                    use $KONBINI_TEST_PYTHON, else `python3` if it has them, else the app image
#   KONBINI_TEST_PYTHON=~/venv/bin/python tests/run.sh
#   tests/run.sh --image [IMAGE]    force the app image (default konbini:latest), as uid 1000
# Each test starts its own throwaway vault and listeners; nothing touches a live board.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
if [ "$1" = "--image" ]; then image=${2:-konbini:latest}; py=
else
    py=${KONBINI_TEST_PYTHON:-python3}
    "$py" -c 'import markdown, yaml' 2>/dev/null || { py=; image=konbini:latest; }
fi
for t in "$here"/tests/test_*.py; do
    if [ -n "$py" ]; then
        PYTHONDONTWRITEBYTECODE=1 TZ=UTC "$py" "$t"
    else
        docker run --rm -u 1000:1000 -v "$here":/k:ro -e PYTHONDONTWRITEBYTECODE=1 -e TZ=UTC \
            --entrypoint python3 "$image" "/k/tests/$(basename "$t")"
    fi
done
