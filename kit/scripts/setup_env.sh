#!/usr/bin/env bash
# Run from kit after extracting the shared data:
#   source scripts/setup_team.sh
# Ollama must already be running with qwen2.5-coder:7b installed.
# Set OLLAMA_HOST before sourcing if your Ollama uses a different address.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    printf 'Run this with: source scripts/setup_team.sh\n' >&2
    exit 1
fi

_sumqa_setup_team() {
    local sumqa_kit_dir
    sumqa_kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)" || return

    python -m pip install -r "$sumqa_kit_dir/requirements.txt" || return

    export ORKG_ENDPOINT="oxigraph:$sumqa_kit_dir/data/kg/orkg2023/store"
    export DBLP_ENDPOINT="oxigraph:$sumqa_kit_dir/data/kg/dblp2022/store"
    export OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}"

    # The checker expects kit as its working directory. Use a subshell so the
    # caller stays in their current directory while the exports remain active.
    (
        cd -- "$sumqa_kit_dir" || exit 1
        python scripts/check_setup.py || exit
        # check_setup.py reports failed checks in the file but exits with zero.
        python -c 'from pathlib import Path; import sys; sys.exit(0 if Path("SETUP_REPORT.txt").read_text().splitlines()[-1] == "ALL CHECKS PASSED" else 1)'
    ) || return

    printf '\nTeam setup complete. Endpoint settings are active in this terminal.\n'
}

if _sumqa_setup_team; then
    unset -f _sumqa_setup_team
else
    unset -f _sumqa_setup_team
    printf '\nSetup did not pass. Review the errors above and rerun this script after fixing them.\n' >&2
    return 1
fi
