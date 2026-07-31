#!/usr/bin/env bash
# cortistrate — one-command Docker install
# curl -fsSL https://raw.githubusercontent.com/mark1kwok/cortistrate/main/install.sh | bash
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'
    CYAN='\033[0;36m'; NC='\033[0m'
else
    BOLD=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; NC=''
fi

info()    { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*"; }

echo ""
echo -e "${BOLD}  cortistrate${NC} — one-command Docker install"
echo ""

# ── Step 1: Docker ────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    error "Docker is required but not found."
    echo "  Install: https://docs.docker.com/engine/install/"
    exit 1
fi
info "Docker found: $(docker --version)"

# ── Step 2: Clone repo ────────────────────────────────────────────────────
REPO_URL="https://github.com/mark1kwok/cortistrate.git"
REPO_DIR="${CORTISTRATE_REPO:-$HOME/.local/share/cortistrate/repo}"

if [ -d "$REPO_DIR/.git" ]; then
    info "Updating existing repo at $REPO_DIR"
    git -C "$REPO_DIR" pull --ff-only
else
    info "Cloning cortistrate to $REPO_DIR"
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone "$REPO_URL" "$REPO_DIR"
fi

# ── Step 3: Build Docker image ────────────────────────────────────────────
info "Building Docker image (this may take a few minutes)..."
docker build -t cortistrate:latest "$REPO_DIR"

# ── Step 4: Create data directory + seed default config ───────────────────
DATA_DIR="${CORTISTRATE_ROOT:-$HOME/.cortistrate}"
mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/cortistrate.toml" ]; then
    info "Seeding default config at $DATA_DIR/cortistrate.toml"
    mkdir -p "$DATA_DIR/.index/sqlite" "$DATA_DIR/.index/pg" "$DATA_DIR/.tmp"
    cp "$REPO_DIR/src/cortistrate/config/default.toml" "$DATA_DIR/cortistrate.toml"
    cp "$REPO_DIR/src/cortistrate/config/default_ome.toml" "$DATA_DIR/ome.toml"
else
    info "Config already exists: $DATA_DIR/cortistrate.toml"
fi

# ── Step 5: Show next steps ───────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Cortistrate ready.${NC}"
echo ""
echo -e "  1. Edit your config to add LLM + embedding API keys:"
echo -e "     ${CYAN}\$EDITOR $DATA_DIR/cortistrate.toml${NC}"
echo ""
echo -e "  2. Start the server:"
echo -e "     ${CYAN}docker run -d --name cortistrate \\"
echo -e "       -p 5473:5473 \\"
echo -e "       -v ~/.cortistrate:/home/app/.cortistrate \\"
echo -e "       cortistrate:latest${NC}"
echo ""
echo -e "  3. Check health:"
echo -e "     ${CYAN}curl http://localhost:5473/health${NC}"
echo ""
echo -e "  Update:  cd $REPO_DIR && git pull && docker build -t cortistrate:latest ."
echo -e "  Docs:    https://cortistrate.dev/docs"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
