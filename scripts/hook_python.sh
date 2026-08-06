#!/usr/bin/env sh
# Resolve the interpreter the pre-commit hooks run under, then exec it.
#
# The hooks used to hardcode `./.venv/bin/<tool>`. That works on the maintainer's
# machine and nowhere else: a fresh clone, a venv somewhere other than ./.venv,
# or a `uv run`-centric workflow all hit a path that does not exist. CI does its
# own `source .venv/bin/activate`, so the divergence never showed up there.
#
# Why that matters more here than in most repos: this project has no branch
# protection by choice, so these hooks are the ONLY thing standing between a real
# identity and a public push (see check_real_identities.py). A hook that cannot
# start is a hook that is not protecting anything — and the way people get past a
# hook that will not start is `--no-verify`, which switches off the identity
# guard as well.
#
# Order is deliberate: an ACTIVE virtualenv wins, because that is the environment
# the person is working in and the one whose packages match what they just ran.
# The repo venv is next. `uv run` is the fallback that makes a clean clone work
# without a manual install step. A bare python3 is last and may well lack the
# tools — it will say so itself, which is a better failure than "not found".
set -eu

if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
	exec "${VIRTUAL_ENV}/bin/python" "$@"
fi

if [ -x ".venv/bin/python" ]; then
	exec ".venv/bin/python" "$@"
fi

if command -v uv >/dev/null 2>&1 && [ -f "pyproject.toml" ]; then
	exec uv run python "$@"
fi

if command -v python3 >/dev/null 2>&1; then
	exec python3 "$@"
fi

# Ours, not "black: command not found" — the reader has to know that the guard
# did not run, and that skipping it is not the fix.
echo "pre-commit: no Python interpreter found." >&2
echo "  Tried: \$VIRTUAL_ENV, ./.venv, 'uv run', python3." >&2
echo "  Create one with 'uv venv && uv sync' (or 'python3 -m venv .venv')." >&2
echo "  Do NOT reach for --no-verify: it also skips the real-identity guard," >&2
echo "  and a pushed identity cannot be taken back." >&2
exit 1
