#!/bin/bash
# Check if a hook is enabled in meta-process.yaml
#
# Usage (source this in other hooks):
#   source "$(dirname "$0")/check-hook-enabled.sh"
#   if ! is_hook_enabled "protect_main"; then
#       exit 0  # Hook disabled, skip
#   fi
#
# Or check directly:
#   ./check-hook-enabled.sh protect_main  # exits 0 if enabled

# Get repo root
get_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$(dirname "$0")")"
}

# Check if a hook is enabled
# Returns 0 (true) if enabled, 1 (false) if disabled
is_hook_enabled() {
    local hook_name="$1"
    local repo_root
    repo_root=$(get_repo_root)

    # Use Python helper if available (more reliable YAML parsing)
    if [[ -f "$repo_root/scripts/meta_config.py" ]]; then
        python "$repo_root/scripts/meta_config.py" --hook "$hook_name" 2>/dev/null
        return $?
    fi

    # Fallback: grep for the setting in meta-process.yaml
    local config_file="$repo_root/meta-process.yaml"
    if [[ ! -f "$config_file" ]]; then
        # No config file = all hooks enabled by default
        return 0
    fi

    # Simple grep-based check (not perfect but works for basic cases)
    # Look for "hook_name: false" under hooks section
    if grep -A 50 "^hooks:" "$config_file" 2>/dev/null | grep -q "^\s*${hook_name}:\s*false"; then
        return 1  # Disabled
    fi

    return 0  # Enabled (default)
}

# If called directly (not sourced), check the hook
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ -z "$1" ]]; then
        echo "Usage: $0 <hook_name>" >&2
        exit 1
    fi
    is_hook_enabled "$1"
    exit $?
fi
