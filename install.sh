#!/usr/bin/env bash
# cortistrate — one-command Docker install
# Usage: curl -fsSL https://raw.githubusercontent.com/mark1kwok/cortistrate/main/install.sh | bash
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────
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

# ── Helpers ────────────────────────────────────────────────────────────────
info()    { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*"; }
section() { echo ""; echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${YELLOW}  $*${NC}"; echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ── Main ──────────────────────────────────────────────────────────────────
print_banner

# ── Step 0: Detect platform ───────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux*)  PLATFORM="linux";;
    Darwin*) PLATFORM="macos";;
    *)       error "Unsupported OS: $OS"; exit 1;;
esac
info "Platform: $PLATFORM ($ARCH)"

# ── Step 1: Check Docker ──────────────────────────────────────────────────
section "Step 1: Check Docker"

if command -v docker &>/dev/null; then
    info "Docker $(docker --version | cut -d' ' -f3 | cut -d',' -f1)"
else
    error "Docker is required but not found."
    echo ""
    if [ "$PLATFORM" = "macos" ]; then
        echo "  brew install --cask docker"
    else
        echo "  curl -fsSL https://get.docker.com | bash"
    fi
    exit 1
fi

# ── Step 2: Clone repo ────────────────────────────────────────────────────
section "Step 2: Clone Cortistrate"

REPO_URL="https://github.com/mark1kwok/cortistrate.git"
REPO_DIR="${CORTISTRATE_REPO:-$HOME/.local/share/cortistrate/repo}"

if [ -d "$REPO_DIR/.git" ]; then
    info "Updating existing repo at $REPO_DIR"
    git -C "$REPO_DIR" pull --ff-only
else
    info "Cloning to $REPO_DIR"
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone "$REPO_URL" "$REPO_DIR"
fi

# ── Step 3: Build Docker image ────────────────────────────────────────────
section "Step 3: Build Docker Image"

info "Building cortistrate:latest (this may take a few minutes)..."
docker build -t cortistrate:latest "$REPO_DIR"

# ── Step 4: Seed data directory ───────────────────────────────────────────
section "Step 4: Data Directory"

DATA_DIR="${CORTISTRATE_ROOT:-$HOME/.cortistrate}"

if [ -d "$DATA_DIR" ] && [ -f "$DATA_DIR/cortistrate.toml" ]; then
    info "Config already exists: $DATA_DIR/cortistrate.toml"
else
    info "Seeding data directory at $DATA_DIR"
    mkdir -p "$DATA_DIR/.index/sqlite" "$DATA_DIR/.index/pg" "$DATA_DIR/.tmp"
    cp "$REPO_DIR/src/cortistrate/config/default.toml" "$DATA_DIR/cortistrate.toml"
    cp "$REPO_DIR/src/cortistrate/config/default_ome.toml" "$DATA_DIR/ome.toml"
fi

# ── Step 5: Agent integrations ────────────────────────────────────────────
section "Step 5: Agent Integrations"

# ── 5a: Hermes ──────────────────────────────────────────────────────────────
HERMES_PLUGIN_DIR="$HOME/.hermes/plugins"
HERMES_LINK="$HERMES_PLUGIN_DIR/cortistrate"
HERMES_SRC="$REPO_DIR/src/integrations/hermes"

if command -v hermes &>/dev/null; then
    info "Hermes detected"
    if [ -L "$HERMES_LINK" ]; then
        info "Hermes plugin already linked: $HERMES_LINK"
    elif [ -d "$HERMES_LINK" ]; then
        warn "Hermes plugin dir exists as real directory (not symlink)."
        echo "  Remove it manually if you want a fresh install: rm -rf $HERMES_LINK"
    else
        mkdir -p "$HERMES_PLUGIN_DIR"
        ln -s "$HERMES_SRC" "$HERMES_LINK"
        info "Hermes plugin installed: $HERMES_LINK → $HERMES_SRC"
    fi
else
    info "Hermes not detected — skipping plugin install"
    echo "  Install Hermes: https://github.com/mark1kwok/hermes"
fi

# ── 5b: Claude Code ─────────────────────────────────────────────────────────
if command -v claude &>/dev/null; then
    info "Claude Code detected"
    echo "  Register cortistrate in Claude Code:"
    echo "    ${BLUE}/plugin marketplace add cortistrate${NC}"
else
    info "Claude Code not detected — skipping plugin install"
    echo "  Install Claude Code: https://claude.ai/code"
fi

# ── Step 6: Configure LLM ─────────────────────────────────────────────────
section "Step 6: Configure LLM"

echo "Cortistrate needs an OpenAI-compatible LLM endpoint for memory extraction."
echo "Edit your config to add API keys:"
echo ""
echo -e "  ${BLUE}\$EDITOR $DATA_DIR/cortistrate.toml${NC}"
echo ""
echo "  [llm] section: api_key, model, base_url"
echo "  [embedding] section: api_key, model, base_url"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Cortistrate installed!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo ""
echo -e "  ${BOLD}1. Start the server:${NC}"
echo "    docker run -d --name cortistrate \\"
echo "      -p 5473:5473 \\"
echo "      -v ~/.cortistrate:/home/app/.cortistrate \\"
echo "      cortistrate:latest"
echo ""
echo -e "  ${BOLD}2. Check health:${NC}"
echo "    curl http://localhost:5473/health"
echo ""
echo -e "  ${BOLD}Update:${NC}"
echo "    cd $REPO_DIR && git pull && docker build -t cortistrate:latest ."
echo "    docker rm -f cortistrate && docker run -d ... cortistrate:latest"
echo ""
echo -e "  ${BOLD}Docs:${NC} https://cortistrate.dev/docs"
echo ""
