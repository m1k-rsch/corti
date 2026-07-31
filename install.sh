#!/usr/bin/env bash
# cortistrate — one-command Docker install (pull pre-built image)
# Usage: curl -fsSL https://raw.githubusercontent.com/mark1kwok/cortistrate/main/install.sh | bash
set -euo pipefail

IMAGE="mark1kwok/cortistrate:latest"

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

# ── Step 2: Pull image ────────────────────────────────────────────────────
section "Step 2: Pull Image"

info "Pulling $IMAGE..."
docker pull "$IMAGE"

# ── Step 3: Seed data directory ───────────────────────────────────────────
section "Step 3: Data Directory"

DATA_DIR="${CORTISTRATE_ROOT:-$HOME/.cortistrate}"

if [ -d "$DATA_DIR" ] && [ -f "$DATA_DIR/cortistrate.toml" ]; then
    info "Config already exists: $DATA_DIR/cortistrate.toml"
else
    info "Seeding data directory at $DATA_DIR"
    mkdir -p "$DATA_DIR/.index/sqlite" "$DATA_DIR/.index/pg" "$DATA_DIR/.tmp"

    # Extract default configs from the Docker image.
    CID=$(docker create "$IMAGE")
    docker cp "$CID:/opt/cortistrate/config/default.toml" "$DATA_DIR/cortistrate.toml"
    docker cp "$CID:/opt/cortistrate/config/default_ome.toml" "$DATA_DIR/ome.toml"
    docker rm "$CID" >/dev/null
fi

# ── Step 4: Agent integrations ────────────────────────────────────────────
section "Step 4: Agent Integrations"

CID=$(docker create "$IMAGE")

# ── 4a: Hermes ──────────────────────────────────────────────────────────────
HERMES_PLUGIN_DIR="$HOME/.hermes/plugins"
HERMES_TARGET="$HERMES_PLUGIN_DIR/cortistrate"

if command -v hermes &>/dev/null; then
    info "Hermes detected"
    if [ -L "$HERMES_TARGET" ]; then
        warn "Old symlink found at $HERMES_TARGET — removing"
        rm "$HERMES_TARGET"
    fi
    if [ -d "$HERMES_TARGET" ]; then
        info "Hermes plugin already installed at $HERMES_TARGET"
        echo "  Remove it manually if you want a fresh install: rm -rf $HERMES_TARGET"
    else
        mkdir -p "$HERMES_PLUGIN_DIR"
        docker cp "$CID:/opt/cortistrate/integrations/hermes" "$HERMES_PLUGIN_DIR/"
        mv "$HERMES_PLUGIN_DIR/hermes" "$HERMES_TARGET"
        info "Hermes plugin installed: $HERMES_TARGET"
    fi
    # Auto-enable the plugin + set memory provider so it's active immediately.
    if hermes plugins list 2>/dev/null | grep -q cortistrate; then
        hermes plugins enable cortistrate 2>/dev/null || true
    fi
    # Also set the memory provider (belt-and-suspenders — some Hermes versions
    # require this even after plugin enable).
    if hermes config get memory.provider 2>/dev/null | grep -q cortistrate; then
        info "Hermes plugin enabled — memory.provider=cortistrate"
    else
        hermes config set memory.provider cortistrate 2>/dev/null && \
            info "Hermes plugin enabled — memory.provider=cortistrate" || \
            warn "Could not set memory.provider. Run: hermes config set memory.provider cortistrate"
    fi
else
    info "Hermes not detected — skipping plugin install"
    echo "  Install Hermes: https://github.com/mark1kwok/hermes"
fi

# ── 4b: Claude Code ─────────────────────────────────────────────────────────
# ~/.claude/skills/ is auto-discovered by Claude Code — any folder containing
# .claude-plugin/plugin.json is loaded as a plugin on the next session with
# zero CLI commands.  hooks/hooks.json and MCP are auto-discovered.
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
CLAUDE_TARGET="$CLAUDE_SKILLS_DIR/cortistrate"

if command -v claude &>/dev/null; then
    info "Claude Code detected"
    if [ -L "$CLAUDE_TARGET" ]; then
        warn "Old symlink found at $CLAUDE_TARGET — removing"
        rm "$CLAUDE_TARGET"
    fi
    if [ -d "$CLAUDE_TARGET" ]; then
        info "Claude Code plugin already installed at $CLAUDE_TARGET"
        echo "  Remove it manually if you want a fresh install: rm -rf $CLAUDE_TARGET"
    else
        mkdir -p "$CLAUDE_SKILLS_DIR"
        docker cp "$CID:/opt/cortistrate/integrations/claude-code" "$CLAUDE_SKILLS_DIR/"
        mv "$CLAUDE_SKILLS_DIR/claude-code" "$CLAUDE_TARGET"
        info "Claude Code plugin installed: $CLAUDE_TARGET"
        info "Hooks + MCP auto-discovered on next session — no manual steps needed"
    fi
else
    info "Claude Code not detected — skipping plugin install"
    echo "  Install Claude Code: https://claude.ai/code"
fi

docker rm "$CID" >/dev/null

# ── Step 5: Default endpoints ─────────────────────────────────────────────
section "Step 5: Default Endpoints"

echo -e "  ${CYAN}Cortistrate ships with free default endpoints — no API key required:${NC}"
echo ""
echo -e "  ${BOLD}LLM:${NC}       ${GREEN}Pollinations.ai${NC} (openai-fast, GPT-OSS 20B)"
echo "           https://text.pollinations.ai/openai"
echo -e "  ${BOLD}Embedding:${NC}  ${GREEN}OVHcloud AI Endpoints${NC} (bge-m3, 1024-d, MIT)"
echo "           https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
echo ""
echo "  These are community / anonymous-tier services:"
echo "    • Pollinations — ~3 yr track record, community-funded"
echo "    • OVHcloud — European public cloud (€20B market cap), 2 RPM per IP"
echo ""
echo -e "  ${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "  ${YELLOW}║${NC}  ${BOLD}For production / higher quality, replace the defaults.${NC}  ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}                                                          ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}  Edit: ${BOLD}${CYAN}\$EDITOR $DATA_DIR/cortistrate.toml${NC}               ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}  Sections: [llm]  [embedding]  [rerank]                    ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}                                                          ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}  ${RED}⚠ After editing, restart the container:${NC}                ${YELLOW}║${NC}"
echo -e "  ${YELLOW}║${NC}    ${BOLD}docker restart cortistrate${NC}                             ${YELLOW}║${NC}"
echo -e "  ${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 6: Auto-start ────────────────────────────────────────────────────
section "Step 6: Start Server"

CONTAINER_NAME="cortistrate"

# Check if a container with this name already exists (running or stopped).
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER_NAME"; then
    STATE=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)
    if [ "$STATE" = "running" ]; then
        info "Container '$CONTAINER_NAME' is already running"
        echo "  docker restart $CONTAINER_NAME   # if you edit config"
    else
        warn "Container '$CONTAINER_NAME' exists but is $STATE"
        echo "  docker start $CONTAINER_NAME     # to resume"
    fi
else
    info "Starting Cortistrate server..."
    docker run -d --name "$CONTAINER_NAME" \
        -p 5473:5473 \
        -v "$DATA_DIR:/home/app/.cortistrate" \
        "$IMAGE" >/dev/null

    # Quick health check
    sleep 2
    if curl -sf http://localhost:5473/health >/dev/null 2>&1; then
        info "Server is running — http://localhost:5473"
    else
        warn "Server started but health check pending (may still be initializing)"
        echo "  docker logs $CONTAINER_NAME  # check progress"
    fi
fi

echo ""
echo -e "  ${BOLD}Check:${NC}     curl http://localhost:5473/health"
echo -e "  ${BOLD}Logs:${NC}      docker logs -f $CONTAINER_NAME"
echo -e "  ${BOLD}Restart:${NC}   docker restart $CONTAINER_NAME   ${CYAN}# after editing cortistrate.toml${NC}"
echo -e "  ${BOLD}Update:${NC}    docker pull $IMAGE && docker rm -f $CONTAINER_NAME && docker run -d --name $CONTAINER_NAME -p 5473:5473 -v $DATA_DIR:/home/app/.cortistrate $IMAGE"
echo -e "  ${BOLD}Docs:${NC}     https://cortistrate.dev/docs"
echo ""
