#!/usr/bin/env bash
# ==============================================================================
# Job Bot - Oracle Cloud Always-Free Deployment Script
# Automatically provisions Ubuntu VM with dependencies, uv, and systemd service
# ==============================================================================
set -e

echo "=================================================="
echo "🚀 Deploying Job Bot on Oracle Cloud Always Free"
echo "=================================================="

# 1. Update system packages & install Chromium for headless Playwright
echo "📦 Installing system dependencies..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl wget chromium-browser poppler-utils build-essential

# 2. Install uv package manager
if ! command -v uv &> /dev/null; then
    echo "⚡ Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 3. Clone or update repository
if [ ! -d "$HOME/job-bot" ]; then
    echo "📥 Cloning Job Bot repository..."
    git clone https://github.com/kunal763/job-bot.git "$HOME/job-bot"
fi

cd "$HOME/job-bot"
echo "🔧 Installing Python dependencies with uv..."
uv sync

echo ""
echo "=================================================="
echo "🎉 Server Provisioning Complete!"
echo "=================================================="
echo "Next step: Extract your sync bundle (cookies, profile, db):"
echo "  tar -xzf job_bot_phone_sync.tar.gz"
echo ""
echo "To start the Telegram bot for mobile control:"
echo "  uv run job-bot telegram-bot"
echo "=================================================="
