#!/usr/bin/env bash
# cortistrate install script — https://cortistrate.dev
# Usage: curl -fsSL https://cortistrate.dev/install.sh | bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'
    CYAN='\033[0;36m'; BLUE='\033[0;34m'; NC='\033[0m'
else
    BOLD=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; BLUE=''; NC=''
fi

print_banner() {
    cat <<'BANNER'

   ██████╗ ██████╗ ██████╗ ████████╗██╗
  ██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██║
  ██║     ██║   ██║██████╔╝   ██║   ██║
  ██║     ██║   ██║██╔══██╗   ██║   ██║
  ╚██████╗╚██████╔╝██║  ██║   ██║   ██║
   ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝

BANNER
    printf "  ${BOLD}Cortistrate${NC} — ${GREEN}Multi-agent memory for AI swarms${NC}\n"
    echo ""
}

# ── Helpers ──────────────────────────────────────────────────────────────────
info()    { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}❌${NC} $*"; }
section() { echo ""; echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${YELLOW}  $*${NC}"; echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

prompt_user() {
    local prompt="$1" varname="$2"
    printf "%s" "$prompt"
    if [ -e /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
        read "$varname" </dev/tty
    else
        read "$varname" || true
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────
print_banner

# ── Step 0: Detect platform ──────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux*)  PLATFORM="linux";;
    Darwin*) PLATFORM="macos";;
    *)       error "Unsupported OS: $OS"; exit 1;;
esac
info "Platform: $PLATFORM ($ARCH)"

# ── Step 1: Check Python ≥ 3.12 ──────────────────────────────────────────────
section "Step 1: Check Python"

PYTHON=""
for cmd in python3.14 python3.13 python3.12 python3; do
    if command -v "$cmd" &>/dev/null; then
        PY_VERSION="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")"
        PY_MAJOR="${PY_VERSION%%.*}"
        PY_MINOR="${PY_VERSION#*.}"
        if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 12 ]; }; then
            PYTHON="$cmd"
            info "Found $cmd ($PY_VERSION)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python 3.12+ is required but not found."
    echo ""
    echo "Install Python 3.12+:"
    if [ "$PLATFORM" = "macos" ]; then
        echo "  brew install python@3.12"
    else
        echo "  sudo apt install python3.12  # or use deadsnakes PPA"
    fi
    echo ""
    echo "Or use uv (recommended):"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ── Step 2: Choose installer (uv preferred, pip fallback) ────────────────────
section "Step 2: Install Cortistrate"

INSTALLER=""
if command -v uv &>/dev/null; then
    INSTALLER="uv"
    info "Using uv"
    uv tool install cortistrate --force
elif command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
    PIP_CMD="$(command -v pip3 || command -v pip)"
    INSTALLER="pip"
    info "Using $PIP_CMD"
    "$PIP_CMD" install --user --upgrade cortistrate
else
    error "Neither uv nor pip found. Install pip or uv first."
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ── Step 3: Verify CLI ───────────────────────────────────────────────────────
if ! command -v cortistrate &>/dev/null; then
    # Try user base
    USER_BASE="$($PYTHON -m site --user-base 2>/dev/null || echo "$HOME/.local")"
    export PATH="$USER_BASE/bin:$PATH"
fi

if ! command -v cortistrate &>/dev/null; then
    error "cortistrate CLI not found in PATH."
    echo "  Add to PATH: export PATH=\"$USER_BASE/bin:\$PATH\""
    exit 1
fi

info "cortistrate CLI ready: $(command -v cortistrate)"

# ── Step 4: Initialize ──────────────────────────────────────────────────────
section "Step 3: Initialize Cortistrate"

CORTISTRATE_ROOT="${CORTISTRATE_ROOT:-$HOME/.cortistrate}"

if [ -d "$CORTISTRATE_ROOT" ]; then
    warn "Existing config at $CORTISTRATE_ROOT"
    prompt_user "Re-initialize? This will NOT delete data. (y/N): " REINIT
    if [ "${REINIT:-N}" = "y" ] || [ "${REINIT:-N}" = "Y" ]; then
        cortistrate init --non-interactive 2>/dev/null || cortistrate init || true
        info "Re-initialized"
    else
        info "Keeping existing config"
    fi
else
    cortistrate init --non-interactive 2>/dev/null || cortistrate init || true
    info "Initialized at $CORTISTRATE_ROOT"
fi

# ── Step 5: Check Postgres ──────────────────────────────────────────────────
section "Step 4: Check Postgres"

PG_READY="false"
if command -v psql &>/dev/null; then
    if psql -d postgres -c "SELECT 1" &>/dev/null 2>&1; then
        info "Postgres connection OK"
        PG_READY="true"
    elif psql -d cortistrate -c "SELECT 1" &>/dev/null 2>&1; then
        info "Postgres connection OK (cortistrate database)"
        PG_READY="true"
    fi
fi

if [ "$PG_READY" = "false" ]; then
    warn "Postgres not detected or not reachable."
    echo ""
    echo "  Cortistrate uses Postgres with pgvector for hybrid search."
    echo "  Install Postgres:"
    if [ "$PLATFORM" = "macos" ]; then
        echo "    brew install postgresql@16 pgvector"
    else
        echo "    sudo apt install postgresql postgresql-16-pgvector"
    fi
    echo ""
    echo "  Then create database:"
    echo "    createdb cortistrate"
    echo "    psql -d cortistrate -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
    echo ""
    echo "  Configure connection in: $CORTISTRATE_ROOT/config.toml"
    echo ""
    echo "  Cortistrate will use embedded SQLite for state. Vector search"
    echo "  features require Postgres. See docs: https://cortistrate.dev/docs"
fi

# ── Step 6: Configure LLM ──────────────────────────────────────────────────
section "Step 5: Configure LLM"

echo "Cortistrate needs an OpenAI-compatible LLM endpoint for memory extraction."
echo "Edit your config:"
echo ""
echo -e "  ${BLUE}$EDITOR $CORTISTRATE_ROOT/config.toml${NC}"
echo ""
echo "Set [llm] section with your api_key and model."
echo "Or set environment variable:"
echo ""
echo -e "  ${BLUE}export CORTISTRATE_LLM_API_KEY=\"sk-...\"${NC}"
echo ""

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  🎉 Cortistrate installed!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo ""
echo -e "  ${BOLD}Start the server:${NC}"
echo "    cortistrate server start"
echo ""
echo -e "  ${BOLD}Install agent integration:${NC}"
echo "    Hermes:   hermes plugins install cortistrate"
echo "    Claude:   see https://cortistrate.dev/docs/claude-code"
echo ""
echo -e "  ${BOLD}Docs:${NC} https://cortistrate.dev/docs"
echo ""
