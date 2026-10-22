#!/bin/sh
set -u
export TRANSLATION_BATCH_SIZE="${TRANSLATION_BATCH_SIZE:-32}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_DIR" || exit 1

fail() {
    echo
    echo "The setup or translation process failed."
    printf "Press Enter to exit."
    read -r _
    exit 1
}

is_supported_python() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) else 1)' >/dev/null 2>&1
}

PYTHON=""
if [ -x ".venv/bin/python" ]; then
    if is_supported_python ".venv/bin/python"; then
        PYTHON=".venv/bin/python"
    else
        echo "Existing .venv uses an unsupported Python version. Recreating it..."
        rm -rf .venv
    fi
fi

if [ -z "$PYTHON" ]; then
    BOOTSTRAP=""
    for candidate in python3.13 python3.12 python3; do
        candidate_path=$(command -v "$candidate" 2>/dev/null || true)
        if [ -n "$candidate_path" ] && is_supported_python "$candidate_path"; then
            BOOTSTRAP="$candidate_path"
            break
        fi
    done

    if [ -z "$BOOTSTRAP" ] && command -v brew >/dev/null 2>&1; then
        echo "Python 3.12 or 3.13 was not found. Installing Python 3.13 with Homebrew..."
        brew install python@3.13 || fail
        brew_python_prefix=$(brew --prefix python@3.13 2>/dev/null || true)
        if [ -n "$brew_python_prefix" ] && is_supported_python "$brew_python_prefix/bin/python3.13"; then
            BOOTSTRAP="$brew_python_prefix/bin/python3.13"
        fi
    fi

    if [ -z "$BOOTSTRAP" ]; then
        echo "Python 3.12 or 3.13 could not be installed automatically."
        echo "Install Python 3.13 from https://www.python.org/downloads/ or install Homebrew, then run this file again."
        printf "Press Enter to exit."
        read -r _
        exit 1
    fi

    echo "Creating local .venv..."
    "$BOOTSTRAP" -m venv .venv || fail
    [ -x ".venv/bin/python" ] || fail
    PYTHON=".venv/bin/python"
fi
BACKEND_ARG=""
if [ "$#" -gt 0 ]; then
    BACKEND_ARG="--backend $1"
fi

echo "Using Python interpreter:"
"$PYTHON" --version
"$PYTHON" -c 'import sys; print(sys.executable)' || fail

echo "Installing requirements..."
# shellcheck disable=SC2086
"$PYTHON" resources/install_requirements.py $BACKEND_ARG || fail

echo
echo "Starting translation..."
"$PYTHON" resources/ORAS-TR.py || fail

echo
echo "Translation finished."
printf "Press Enter to exit."
read -r _
