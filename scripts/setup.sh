#!/usr/bin/env bash
# Forge Installer
#
# Usage:  ./scripts/setup.sh --help
# Dev:    ./scripts/setup.sh --local
#
# To change the repo URL, update FORGE_REPO below (all derived URLs follow).
#
# Options:
#   --uninstall       Remove Forge completely (keeps project-local .forge/ dirs)
#   --purge           With --uninstall: also remove project-local .forge/ dirs
#   --local           Install from current directory in editable mode (for development)
#   --no-modify-path  Don't modify shell profile
#   --version X.Y.Z   Install specific version
#   --help            Show this help

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
FORGE_HOME="${FORGE_HOME:-$HOME/.forge}"
FORGE_BIN="$FORGE_HOME/bin"
FORGE_PACKAGE="multi-forge"
FORGE_REPO="https://github.com/hapa1i/multi-forge.git"
# Derived: raw content URL for curl-pipe-bash install (strips .git suffix)
FORGE_RAW_URL="https://raw.githubusercontent.com/${FORGE_REPO#https://github.com/}"
FORGE_RAW_URL="${FORGE_RAW_URL%.git}"
FORGE_SETUP_URL="$FORGE_RAW_URL/main/scripts/setup.sh"
FORGE_VERSION="${FORGE_VERSION:-main}"
MODIFY_PATH=true
UNINSTALL=false
PURGE=false
YES=false
LOCAL_MODE=false
FORGE_HOME_STAMP="managed-by-setup-sh"
MODIFIED_PROFILE=""  # Track which profile was modified (for accurate messaging)

# Block markers for safe profile editing (industry standard pattern)
BLOCK_START="# >>> multi-forge >>>"
BLOCK_END="# <<< multi-forge <<<"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1" >&2
}

fatal() {
    error "$1"
    exit 1
}

header() {
    echo ""
    echo -e "${BOLD}${CYAN}$1${NC}"
    echo -e "${CYAN}$(printf '─%.0s' {1..50})${NC}"
}

trim_trailing_slashes() {
    local path="$1"
    while [[ "$path" != "/" && "$path" == */ ]]; do
        path="${path%/}"
    done
    printf "%s" "$path"
}

validate_forge_home() {
    local action="$1"
    local home
    home="$(trim_trailing_slashes "$HOME")"
    FORGE_HOME="$(trim_trailing_slashes "$FORGE_HOME")"
    FORGE_BIN="$FORGE_HOME/bin"

    if [[ -z "$home" ]]; then
        fatal "HOME is empty - refusing to $action"
    fi
    if [[ -z "$FORGE_HOME" ]]; then
        fatal "FORGE_HOME is empty - refusing to $action"
    fi
    if [[ "$FORGE_HOME" == "~" || "$FORGE_HOME" == "~/"* ]]; then
        fatal "FORGE_HOME ('$FORGE_HOME') uses '~', which is not expanded here. Use an absolute path."
    fi
    if [[ "$FORGE_HOME" != /* ]]; then
        fatal "FORGE_HOME ('$FORGE_HOME') must be an absolute path - refusing to $action"
    fi
    if [[ "$FORGE_HOME" == "/" ]]; then
        fatal "FORGE_HOME is root (/) - refusing to $action"
    fi
    if [[ "$FORGE_HOME" == "$home" ]]; then
        fatal "FORGE_HOME cannot be \$HOME itself - refusing to $action"
    fi
    if [[ ! "$FORGE_HOME" == "$home"/* ]]; then
        fatal "FORGE_HOME ('$FORGE_HOME') is not under \$HOME - refusing to $action"
    fi

    case "$FORGE_HOME" in
        "$home/.local"|"$home/.local/bin"|"$home/.local/share"|"$home/.config"|"$home/.cache"|"$home/Library"|"$home/Library/Application Support")
            fatal "FORGE_HOME ('$FORGE_HOME') is a broad user directory - refusing to $action"
            ;;
    esac

    local base="${FORGE_HOME##*/}"
    if [[ "$base" != *forge* && "$base" != *Forge* && "$base" != *FORGE* ]]; then
        fatal "FORGE_HOME ('$FORGE_HOME') must be a Forge-specific directory (for example: $home/.forge)"
    fi
}

is_forge_repo_dir() {
    local repo_dir="$1"
    local pyproject="$repo_dir/pyproject.toml"
    [[ -f "$pyproject" ]] && grep -Eq "^[[:space:]]*name[[:space:]]*=[[:space:]]*[\"']$FORGE_PACKAGE[\"']" "$pyproject"
}

looks_like_forge_home() {
    if [[ -f "$FORGE_HOME/.forge-home" ]] && grep -qx "$FORGE_HOME_STAMP" "$FORGE_HOME/.forge-home" 2>/dev/null; then
        return 0
    fi

    # Legacy setup.sh installs predate the stamp, but still have a Forge repo
    # checkout or symlink at FORGE_HOME/repo.
    is_forge_repo_dir "$FORGE_HOME/repo"
}

# Portable pip wrapper: tries python3 -m pip first, falls back to pip3/pip.
# Needed because python3 may resolve to a venv without pip, while the stale
# package lives in the system Python reachable via pip3.
_pip() {
    if python3 -m pip "$@" 2>/dev/null; then
        return 0
    elif command -v pip3 &>/dev/null && pip3 "$@" 2>/dev/null; then
        return 0
    elif command -v pip &>/dev/null && pip "$@" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Uninstall a pip package using whichever pip command can see it.
# `pip uninstall -y` exits 0 even for missing packages, so _pip would
# succeed on the first interpreter and never reach the one that has it.
# This function finds which pip has the package, then uninstalls with that.
_pip_remove() {
    local pkg="$1"
    if python3 -m pip show "$pkg" &>/dev/null 2>&1; then
        python3 -m pip uninstall -y "$pkg" 2>/dev/null
        return $?
    elif command -v pip3 &>/dev/null && pip3 show "$pkg" &>/dev/null 2>&1; then
        pip3 uninstall -y "$pkg" 2>/dev/null
        return $?
    elif command -v pip &>/dev/null && pip show "$pkg" &>/dev/null 2>&1; then
        pip uninstall -y "$pkg" 2>/dev/null
        return $?
    else
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Prerequisite Checks
# -----------------------------------------------------------------------------

check_command() {
    command -v "$1" &> /dev/null
}

check_prerequisites() {
    header "Checking Prerequisites"

    local missing=()

    # Python 3.11+ (pyproject.toml requires-python = ">=3.11")
    if check_command python3; then
        local py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        local py_major=$(echo $py_version | cut -d. -f1)
        local py_minor=$(echo $py_version | cut -d. -f2)
        if [[ $py_major -ge 3 && $py_minor -ge 11 ]]; then
            success "Python $py_version"
        else
            missing+=("Python 3.11+ (found $py_version)")
        fi
    else
        missing+=("Python 3.11+")
    fi

    # uv (Python package manager)
    if check_command uv; then
        local uv_version=$(uv --version 2>/dev/null | head -1)
        success "uv ($uv_version)"
    else
        missing+=("uv (install: curl -LsSf https://astral.sh/uv/install.sh | sh)")
    fi

    # git
    if check_command git; then
        success "git"
    else
        missing+=("git")
    fi

    # Optional: Docker (for sandboxed execution)
    if check_command docker; then
        if docker info &>/dev/null; then
            success "Docker (optional, for sandboxed execution)"
        else
            warn "Docker installed but daemon not running (sandboxed execution unavailable)"
        fi
    else
        warn "Docker not found (sandboxed execution unavailable)"
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo ""
        error "Missing prerequisites:"
        for dep in "${missing[@]}"; do
            echo "  - $dep"
        done
        fatal "Please install missing dependencies and try again."
    fi
}

# -----------------------------------------------------------------------------
# Installation
# -----------------------------------------------------------------------------

install_forge() {
    header "Installing Forge"
    validate_forge_home "install Forge"

    # Create directories and stamp as a Forge-managed home
    mkdir -p "$FORGE_HOME"
    mkdir -p "$FORGE_BIN"
    echo "$FORGE_HOME_STAMP" > "$FORGE_HOME/.forge-home"

    # Remove stale pip/uv-tool installs that would conflict
    for pkg in "$FORGE_PACKAGE" "tr-claude-forge" "claude-forge"; do
        if _pip show "$pkg" &>/dev/null; then
            warn "Found stale pip install of '$pkg' -- removing to avoid conflicts..."
            _pip_remove "$pkg" || {
                warn "Could not uninstall '$pkg' (run manually: pip uninstall $pkg)"
            }
        fi
        if uv tool list 2>/dev/null | grep -q "^$pkg"; then
            warn "Found stale uv tool install of '$pkg' -- removing to avoid conflicts..."
            uv tool uninstall "$pkg" 2>/dev/null || true
        fi
    done

    # Clone or update repository
    local repo_dir="$FORGE_HOME/repo"
    if [[ -d "$repo_dir/.git" ]]; then
        info "Updating existing installation..."
        cd "$repo_dir"
        git fetch origin
        git checkout "$FORGE_VERSION"
        git pull origin "$FORGE_VERSION" 2>/dev/null || true
    else
        info "Cloning Forge repository..."
        rm -rf "$repo_dir"
        git clone --depth 1 --branch "$FORGE_VERSION" "$FORGE_REPO" "$repo_dir" 2>/dev/null || \
        git clone --depth 1 "$FORGE_REPO" "$repo_dir"
        cd "$repo_dir"
    fi

    success "Repository ready"

    # Install with uv (proxy dependencies now in core)
    info "Installing Python package..."
    cd "$repo_dir"
    uv sync --quiet

    success "Package installed"

    # Create wrapper script
    info "Creating forge command..."
    cat > "$FORGE_BIN/forge" << 'WRAPPER'
#!/usr/bin/env bash
# Forge wrapper - runs forge from the installed venv
FORGE_HOME="${FORGE_HOME:-$HOME/.forge}"
exec "$FORGE_HOME/repo/.venv/bin/forge" "$@"
WRAPPER
    chmod +x "$FORGE_BIN/forge"

    success "Forge command created at $FORGE_BIN/forge"
}

install_forge_local() {
    header "Installing Forge (Local/Development Mode)"
    validate_forge_home "install Forge"

    # Verify we're in a Forge repo
    if [[ ! -f "pyproject.toml" ]]; then
        fatal "No pyproject.toml found. Run this from the Forge repository root."
    fi
    if ! grep -q "name.*=.*$FORGE_PACKAGE" pyproject.toml 2>/dev/null; then
        fatal "This doesn't look like the Forge repository (pyproject.toml doesn't contain '$FORGE_PACKAGE')."
    fi

    local repo_dir="$(pwd)"
    info "Installing from: $repo_dir"

    # Create ~/.forge for config/state (still needed even in local mode)
    mkdir -p "$FORGE_HOME"
    echo "$FORGE_HOME_STAMP" > "$FORGE_HOME/.forge-home"

    # Remove old wrapper from standard install to prevent PATH shadowing
    if [[ -f "$FORGE_BIN/forge" ]]; then
        info "Removing old wrapper at $FORGE_BIN/forge..."
        rm -f "$FORGE_BIN/forge"
    fi

    # Remove stale pip/uv-tool installs that would conflict.
    # A pip-installed 'forge' package (editable or not) can shadow the uv tool
    # binary or inject old code into the Python import path.
    for pkg in "$FORGE_PACKAGE" "tr-claude-forge" "claude-forge"; do
        if _pip show "$pkg" &>/dev/null; then
            warn "Found stale pip install of '$pkg' -- removing to avoid conflicts..."
            _pip_remove "$pkg" || {
                warn "Could not uninstall '$pkg' (run manually: pip uninstall $pkg)"
            }
        fi
        if uv tool list 2>/dev/null | grep -q "^$pkg"; then
            warn "Found stale uv tool install of '$pkg' -- removing to avoid conflicts..."
            uv tool uninstall "$pkg" 2>/dev/null || true
        fi
    done

    # Use uv tool install for editable installation
    # This installs to ~/.local/bin/forge and uses the local source
    info "Installing with 'uv tool install -e --force .'..."
    uv tool install -e --force "."

    # FIX: Verify installation using uv tool list (more reliable than command -v)
    # command -v could find a different 'forge' binary on PATH
    if uv tool list 2>/dev/null | grep -q "^$FORGE_PACKAGE"; then
        success "Forge installed via uv tool"
        if [[ -x "$HOME/.local/bin/forge" ]]; then
            info "Binary at: ~/.local/bin/forge"
        fi
    else
        fatal "Installation failed - $FORGE_PACKAGE not found in 'uv tool list'"
    fi

    # Create symlink in ~/.forge/repo for compatibility with other tooling
    # that expects the repo there (e.g., extension symlink mode)
    if [[ ! -L "$FORGE_HOME/repo" ]] || [[ "$(readlink "$FORGE_HOME/repo")" != "$repo_dir" ]]; then
        # FIX: Check for uncommitted changes before deleting existing repo
        if [[ -d "$FORGE_HOME/repo/.git" ]]; then
            local dirty_status
            dirty_status=$(git -C "$FORGE_HOME/repo" status --porcelain 2>/dev/null || true)
            if [[ -n "$dirty_status" ]]; then
                warn "Existing ~/.forge/repo has uncommitted changes!"
                echo ""
                git -C "$FORGE_HOME/repo" status --short 2>/dev/null || true
                echo ""
                fatal "Stash or commit changes first: git -C ~/.forge/repo stash"
            fi
        fi
        rm -rf "$FORGE_HOME/repo"  # Safe now - no uncommitted changes
        ln -sf "$repo_dir" "$FORGE_HOME/repo"
        info "Linked $FORGE_HOME/repo -> $repo_dir"
    fi

    success "Local installation complete (editable mode)"
    info "Changes to source files will be reflected immediately"
}

setup_path() {
    if [[ "$MODIFY_PATH" != "true" ]]; then
        return
    fi

    header "Setting up PATH"

    # Detect shell
    local shell_name=$(basename "$SHELL")
    local profile_file=""

    case "$shell_name" in
        bash)
            if [[ -f "$HOME/.bash_profile" ]]; then
                profile_file="$HOME/.bash_profile"
            else
                profile_file="$HOME/.bashrc"
            fi
            ;;
        zsh)
            profile_file="$HOME/.zshrc"
            ;;
        fish)
            profile_file="$HOME/.config/fish/config.fish"
            ;;
        *)
            warn "Unknown shell: $shell_name. Add $FORGE_BIN to your PATH manually."
            return
            ;;
    esac

    # Check if already in PATH
    if echo "$PATH" | grep -q "$FORGE_BIN"; then
        success "PATH already configured"
        MODIFIED_PROFILE="$profile_file"
        return
    fi

    # Check if block markers already exist
    if grep -q "$BLOCK_START" "$profile_file" 2>/dev/null; then
        warn "Forge PATH entry exists in $profile_file (may need update)"
        MODIFIED_PROFILE="$profile_file"
        return
    fi

    # Add to profile using block markers (safe to remove later)
    {
        echo ""
        echo "$BLOCK_START"
        if [[ "$shell_name" == "fish" ]]; then
            echo "set -gx PATH \"$FORGE_BIN\" \$PATH"
        else
            echo "export PATH=\"$FORGE_BIN:\$PATH\""
        fi
        echo "$BLOCK_END"
    } >> "$profile_file"

    MODIFIED_PROFILE="$profile_file"
    success "Added to $profile_file"
    info "Run 'source $profile_file' or restart your terminal"
}

verify_forge() {
    header "Verifying Installation"

    # Add bin to PATH for this session
    export PATH="$FORGE_BIN:$PATH"

    # Verify forge command works
    if forge --version &>/dev/null; then
        success "Forge command available"
    else
        warn "Forge command not found (check PATH)"
    fi
}

print_success() {
    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║          Forge installed successfully!           ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Installation:${NC}  $FORGE_HOME"
    echo -e "  ${BOLD}Command:${NC}       $FORGE_BIN/forge"
    echo ""
    if [[ "$MODIFY_PATH" == "true" && -n "$MODIFIED_PROFILE" ]]; then
        echo -e "  ${YELLOW}Restart your terminal or run:${NC}"
        echo "    source $MODIFIED_PROFILE"
        echo ""
    fi
    echo -e "  ${BOLD}Next steps:${NC}"
    echo "    forge extension enable --user   # Install hooks globally (all projects)"
    echo "    forge extension enable --local  # Install hooks for current project only"
    echo ""
    echo -e "  ${BOLD}Quick start:${NC}"
    echo "    forge --help              # See available commands"
    echo "    forge info                # Check installation status"
    echo ""
}

print_success_local() {
    local forge_path
    forge_path=$(command -v forge 2>/dev/null || echo "$HOME/.local/bin/forge")

    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║     Forge installed successfully (dev mode)!     ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Mode:${NC}          Editable (local development)"
    echo -e "  ${BOLD}Source:${NC}        $(pwd)"
    echo -e "  ${BOLD}Command:${NC}       $forge_path"
    echo -e "  ${BOLD}Config:${NC}        $FORGE_HOME"
    echo ""
    echo -e "  ${BOLD}Development notes:${NC}"
    echo "    • Source changes are reflected immediately (editable install)"
    echo "    • Run './scripts/setup.sh --uninstall' to remove (or 'uv tool uninstall $FORGE_PACKAGE')"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo "    forge extension enable --user   # Install hooks globally (all projects)"
    echo "    forge extension enable --local  # Install hooks for current project only"
    echo ""
    echo -e "  ${BOLD}Quick start:${NC}"
    echo "    forge --help              # See available commands"
    echo "    forge info                # Check installation status"
    echo ""
}

# -----------------------------------------------------------------------------
# Uninstallation
# -----------------------------------------------------------------------------

uninstall_forge() {
    header "Uninstalling Forge"

    # CRITICAL: Validate FORGE_HOME before any rm -rf operations
    validate_forge_home "uninstall Forge"
    if ! looks_like_forge_home; then
        fatal "FORGE_HOME ('$FORGE_HOME') doesn't look like a Forge installation. Set FORGE_HOME correctly or remove it manually."
    fi

    local had_errors=false

    # Show what will be removed (if forge is available)
    local forge_cmd=""
    if [[ -x "$FORGE_BIN/forge" ]]; then
        forge_cmd="$FORGE_BIN/forge"
    elif check_command forge; then
        forge_cmd="forge"
    fi

    if [[ -n "$forge_cmd" ]]; then
        info "Scanning for Forge installations..."
        echo ""
        "$forge_cmd" info 2>/dev/null || true
        echo ""
    fi

    # 1. Remove Claude Code extensions (if forge is available)
    if [[ -n "$forge_cmd" ]]; then
        # Remove ALL tracked extensions (user + all local/project)
        info "Removing Claude Code extensions (all scopes)..."
        "$forge_cmd" extension disable --all --yes 2>/dev/null || {
            warn "Could not run 'forge extension disable --all' (may need manual cleanup)"
        }
    else
        warn "Forge command not found, skipping extension removal"
    fi

    # 2. Remove all package installations (uv tool + pip, current + legacy names)
    for pkg in "$FORGE_PACKAGE" "tr-claude-forge" "claude-forge"; do
        if uv tool list 2>/dev/null | grep -q "^$pkg"; then
            info "Removing uv tool installation of '$pkg'..."
            uv tool uninstall "$pkg" 2>/dev/null || true
            success "Removed uv tool package '$pkg'"
        fi
        if _pip show "$pkg" &>/dev/null; then
            info "Removing pip-installed '$pkg'..."
            _pip_remove "$pkg" || {
                warn "Could not uninstall pip package '$pkg' (may need manual: pip uninstall $pkg)"
            }
            success "Removed pip package '$pkg'"
        fi
    done

    # 3. Remove ~/.forge directory
    # IMPORTANT: Handle symlinked repo (from --local install) to avoid deleting user's source
    if [[ -d "$FORGE_HOME" ]]; then
        # First, safely remove repo symlink if it exists (don't follow it!)
        if [[ -L "$FORGE_HOME/repo" ]]; then
            local symlink_target
            symlink_target=$(readlink "$FORGE_HOME/repo")
            info "Removing repo symlink (preserving source: $symlink_target)..."
            rm "$FORGE_HOME/repo"  # Remove symlink only, not target
        fi
        info "Removing $FORGE_HOME..."
        rm -rf "$FORGE_HOME"
        success "Removed $FORGE_HOME"
    else
        info "$FORGE_HOME does not exist"
    fi

    # 4. Clean up project-local .forge directories
    if [[ "$PURGE" == "true" ]]; then
        info "Scanning for project-local .forge/ directories..."
        local forge_dirs
        forge_dirs=$(find "$HOME" -maxdepth 6 -type d -name '.forge' \
            ! -path "$FORGE_HOME" ! -path "$FORGE_HOME/*" 2>/dev/null || true)
        if [[ -n "$forge_dirs" ]]; then
            echo ""
            echo "$forge_dirs" | while read -r d; do echo "  $d"; done
            echo ""
            local count
            count=$(echo "$forge_dirs" | wc -l | tr -d ' ')
            warn "Found $count project-local .forge/ directories (sessions, artifacts, search index)"
            local confirm="n"
            if [[ "$YES" == "true" ]]; then
                confirm="y"
            elif [[ -t 0 ]]; then
                read -p "  Remove all? [y/N] " confirm
            else
                # stdin is piped (e.g. curl | bash); read from terminal
                read -p "  Remove all? [y/N] " confirm </dev/tty || {
                    warn "Cannot prompt for confirmation (no terminal). Use --yes to skip."
                    confirm="n"
                }
            fi
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                echo "$forge_dirs" | while read -r d; do
                    rm -rf "$d"
                    success "Removed $d"
                done
            else
                info "Skipped project-local cleanup"
            fi
        else
            info "No project-local .forge/ directories found"
        fi
    else
        warn "Note: Project-local .forge/ directories are NOT removed"
        warn "      Use --purge to include them, or remove manually:"
        warn "      find ~ -maxdepth 6 -type d -name '.forge'"
    fi

    # 6. Remove Docker images (current + legacy prefixes, avoiding unrelated images)
    if check_command docker && docker info &>/dev/null; then
        info "Removing Forge Docker images..."
        # Use specific prefix to avoid deleting unrelated images like "forge-server"
        local images=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^(multi-forge-|claude-forge-)' || true)
        if [[ -n "$images" ]]; then
            # Note: xargs -r is not portable (BSD/macOS doesn't support it)
            # Use conditional instead
            echo "$images" | while read -r img; do
                docker rmi -f "$img" 2>/dev/null || true
            done
            success "Removed Docker images"
        else
            info "No Forge Docker images found"
        fi
        # NOTE: Deliberately NOT running `docker image prune -f` here
        # That command removes ALL dangling images, not just Forge-related ones
    fi

    # 7. Clean up PATH from shell profile (using block markers for safe removal)
    info "Cleaning up shell profile..."
    for profile in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.config/fish/config.fish"; do
        if [[ -f "$profile" ]]; then
            # Check if our block markers exist (safe removal)
            if grep -q "$BLOCK_START" "$profile" 2>/dev/null; then
                # Create backup before modification
                cp "$profile" "$profile.forge-uninstall-backup"

                # Remove the block between markers (inclusive)
                # Using awk instead of sed for better portability (works on both BSD and GNU)
                awk -v start="$BLOCK_START" -v end="$BLOCK_END" '
                    $0 ~ start { skip=1; next }
                    $0 ~ end { skip=0; next }
                    !skip { print }
                ' "$profile" > "$profile.tmp"

                # Only replace if awk succeeded and produced output
                if [[ -s "$profile.tmp" ]] || [[ ! -s "$profile" ]]; then
                    mv "$profile.tmp" "$profile"
                    success "Cleaned $profile (backup: $profile.forge-uninstall-backup)"
                else
                    rm -f "$profile.tmp"
                    warn "Could not clean $profile (backup preserved)"
                fi
            # Fallback: check for legacy "# Forge" comment (from older versions)
            elif grep -q "# Forge" "$profile" 2>/dev/null; then
                cp "$profile" "$profile.forge-uninstall-backup"
                # Use subshell to prevent set -e from aborting on grep no-match
                (grep -v "# Forge" "$profile" | grep -v "$FORGE_BIN" || true) > "$profile.tmp"
                if [[ -s "$profile.tmp" ]]; then
                    mv "$profile.tmp" "$profile"
                    success "Cleaned $profile (backup: $profile.forge-uninstall-backup)"
                else
                    rm -f "$profile.tmp"
                    warn "Could not clean $profile (backup preserved)"
                fi
            fi
        fi
    done

    # 7. Summary
    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║         Forge uninstalled successfully!          ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Removed:"
    echo "    ✓ ~/.forge/ directory (sessions, proxies, config)"
    echo "    ✓ Claude Code extensions (all tracked scopes)"
    echo "    ✓ Python packages (pip + uv tool)"
    echo "    ✓ Docker images (multi-forge-*, claude-forge-*)"
    echo "    ✓ Shell PATH entries"
    if [[ "$PURGE" == "true" ]]; then
        echo "    ✓ Project-local .forge/ directories"
    fi
    echo ""
    echo "  Not removed (manual cleanup if needed):"
    if [[ "$PURGE" != "true" ]]; then
        echo "    • Project-local .forge/ directories (use --purge)"
    fi
    echo "    • Claude Code itself"
    echo ""
    echo "  Restart your terminal to complete cleanup."
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

show_help() {
    cat << EOF
Forge Installer

Usage:
  Install:   curl -sSL $FORGE_SETUP_URL | bash
  Uninstall: curl -sSL $FORGE_SETUP_URL | bash -s -- --uninstall
  Dev mode:  ./scripts/setup.sh --local

Options:
  --local             Install from current directory in editable mode (for development)
  --uninstall         Remove Forge completely (keeps project-local .forge/ dirs)
  --purge             With --uninstall: also remove project-local .forge/ directories
  --yes, -y           Skip interactive confirmations (for scripted use)
  --no-modify-path    Don't modify shell profile
  --version X.Y.Z     Install specific version/branch
  --help              Show this help

Environment Variables:
  FORGE_HOME          Installation directory (default: ~/.forge)
  FORGE_VERSION       Version to install (default: main)

Examples:
  # Install latest
  curl -sSL $FORGE_SETUP_URL | bash

  # Install specific version
  curl -sSL $FORGE_SETUP_URL | bash -s -- --version v1.0.0

  # Development install (from local clone)
  cd multi-forge && ./scripts/setup.sh --local

  # Complete uninstall
  curl -sSL $FORGE_SETUP_URL | bash -s -- --uninstall

  # Full purge (including project-local .forge/ directories)
  curl -sSL $FORGE_SETUP_URL | bash -s -- --uninstall --purge --yes
EOF
}

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --uninstall)
                UNINSTALL=true
                shift
                ;;
            --purge)
                PURGE=true
                shift
                ;;
            --yes|-y)
                YES=true
                shift
                ;;
            --local)
                LOCAL_MODE=true
                shift
                ;;
            --no-modify-path)
                MODIFY_PATH=false
                shift
                ;;
            --version)
                FORGE_VERSION="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    echo ""
    echo -e "${BOLD}${CYAN}╭──────────────────────────────────────────────────╮${NC}"
    echo -e "${BOLD}${CYAN}│              Forge Installer v1.0                │${NC}"
    echo -e "${BOLD}${CYAN}╰──────────────────────────────────────────────────╯${NC}"

    if [[ "$UNINSTALL" == "true" ]]; then
        uninstall_forge
    elif [[ "$LOCAL_MODE" == "true" ]]; then
        check_prerequisites
        install_forge_local
        # FIX: Add ~/.local/bin to PATH for this session so verify_forge can find 'forge'
        # (uv tool installs to ~/.local/bin which may not be in PATH on fresh systems)
        export PATH="$HOME/.local/bin:$PATH"
        verify_forge
        print_success_local
    else
        check_prerequisites
        install_forge
        setup_path
        verify_forge
        print_success
    fi
}

main "$@"
