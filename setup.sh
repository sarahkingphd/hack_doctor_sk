#!/usr/bin/env bash
# setup.sh — one-time environment bootstrap for dbx-hack-doctors
# Run this once after cloning. Then use ./run.sh to start things.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$REPO_ROOT/app"
FRONTEND_DIR="$APP_DIR/frontend"
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

# ── colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
die()  { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }
step() { echo -e "\n${BOLD}── $* ──${RESET}"; }

# ── 1. prerequisites ─────────────────────────────────────────────────────────
step "Checking prerequisites"

check_cmd() {
  local cmd="$1" hint="$2"
  if command -v "$cmd" &>/dev/null; then
    ok "$cmd $(${cmd} --version 2>&1 | head -1)"
  else
    die "$cmd not found. $hint"
  fi
}

check_cmd node  "Install via: brew install node"
check_cmd npm   "Comes with Node — reinstall Node"
check_cmd python3 "Install via: brew install python"

# python >= 3.10
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
  || die "Python 3.10+ required, found $PY_VER"
ok "python3 $PY_VER"

# databricks CLI — check common install locations
DBX_CLI=""
for candidate in \
    "$(command -v databricks 2>/dev/null || true)" \
    "/opt/homebrew/bin/databricks" \
    "/usr/local/bin/databricks" \
    "$HOME/.databricks/bin/databricks"; do
  if [ -x "$candidate" ]; then
    DBX_CLI="$candidate"
    break
  fi
done
if [ -n "$DBX_CLI" ]; then
  ok "databricks CLI $("$DBX_CLI" --version 2>&1 | head -1)"
else
  warn "databricks CLI not found."
  echo "  Install: brew tap databricks/tap && brew install databricks"
  echo "  Then re-run this script."
  read -r -p "  Continue without it? (deploy won't work) [y/N] " yn
  [[ "$yn" =~ ^[Yy] ]] || exit 1
fi

# uv (optional but preferred for Python deps)
USE_UV=false
if command -v uv &>/dev/null; then
  ok "uv $(uv --version 2>&1)"
  USE_UV=true
else
  warn "uv not found — will use pip + venv instead (slower)"
fi

# ── 2. python environment ────────────────────────────────────────────────────
step "Setting up Python environment"

VENV="$REPO_ROOT/.venv"
if [ ! -d "$VENV" ]; then
  if $USE_UV; then
    (cd "$REPO_ROOT" && uv sync)
  else
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
  fi
  ok "Python venv created at .venv"
else
  ok "Python venv already exists — skipping"
fi

# ── 3. frontend deps ─────────────────────────────────────────────────────────
step "Installing frontend dependencies"
(cd "$FRONTEND_DIR" && npm install --silent)
ok "node_modules installed"

# ── 4. .env configuration ────────────────────────────────────────────────────
step "Configuring .env"

if [ -f "$ENV_FILE" ]; then
  warn ".env already exists — skipping creation"
  echo "  Delete $ENV_FILE and re-run to reconfigure."
else
  cp "$ENV_EXAMPLE" "$ENV_FILE"

  echo ""
  echo "  You need a Databricks Personal Access Token."
  echo "  Get one: Databricks workspace → top-right avatar → Settings → Developer → Access tokens"
  echo ""

  read -r -p "  DATABRICKS_HOST (e.g. https://dbc-xxxxx.cloud.databricks.com): " dbx_host
  read -r -s -p "  DATABRICKS_TOKEN (dapi...): " dbx_token
  echo ""
  read -r -p "  Your Databricks email (for workspace path): " dbx_email
  dbx_workspace_path="/Workspace/Users/${dbx_email}/dbx-hack-doctors"
  echo "  Workspace path will be: $dbx_workspace_path"

  # Write values into .env
  set_env_var() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    else
      echo "${key}=${val}" >> "$ENV_FILE"
    fi
  }

  set_env_var "DATABRICKS_HOST"           "$dbx_host"
  set_env_var "DATABRICKS_TOKEN"          "$dbx_token"
  set_env_var "DATABRICKS_WORKSPACE_PATH" "$dbx_workspace_path"
  ok ".env written"
fi

# ── 5. ~/.databrickscfg ──────────────────────────────────────────────────────
step "Configuring ~/.databrickscfg"

# Parse values from .env
parse_env() {
  local key="$1"
  grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true
}

DBX_HOST=$(parse_env DATABRICKS_HOST)
DBX_TOKEN=$(parse_env DATABRICKS_TOKEN)
DBX_PROFILE=$(parse_env DATABRICKS_CONFIG_PROFILE)
DBX_PROFILE="${DBX_PROFILE:-dbx_hack_doctors}"

if [ -z "$DBX_HOST" ] || [ -z "$DBX_TOKEN" ]; then
  warn "DATABRICKS_HOST or DATABRICKS_TOKEN missing from .env — skipping ~/.databrickscfg"
else
  python3 - <<PYEOF
import configparser, os, sys

cfg_path = os.path.expanduser("~/.databrickscfg")
cfg = configparser.RawConfigParser()
if os.path.exists(cfg_path):
    cfg.read(cfg_path)

profile = "$DBX_PROFILE"
if not cfg.has_section(profile):
    cfg.add_section(profile)
cfg.set(profile, "host",  "$DBX_HOST")
cfg.set(profile, "token", "$DBX_TOKEN")

with open(cfg_path, "w") as f:
    cfg.write(f)
print(f"  ~/.databrickscfg [{profile}] written")
PYEOF
  ok "~/.databrickscfg [$DBX_PROFILE]"
fi

# ── 6. verify Databricks connectivity ────────────────────────────────────────
step "Verifying Databricks connection"

if [ -n "$DBX_CLI" ] && [ -n "$DBX_TOKEN" ]; then
  DATABRICKS_HOST="$DBX_HOST" DATABRICKS_TOKEN="$DBX_TOKEN" \
    "$DBX_CLI" auth whoami 2>&1 | sed 's/^/  /' \
    && ok "Databricks auth OK" \
    || warn "Auth check failed — double-check your host and token"
else
  warn "Skipping connectivity check (CLI or token missing)"
fi

# ── done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Setup complete.${RESET}"
echo ""
echo "  ./run.sh dev     — start UI + API locally"
echo "  ./run.sh deploy  — build and push to Databricks Apps"
echo ""
