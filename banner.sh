#!/usr/bin/env bash
# Render the Cortistrate banner — just for preview, does nothing else.

CYAN='\033[0;36m'
BOLD='\033[1m'
GREEN='\033[0;32m'
NC='\033[0m'

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
