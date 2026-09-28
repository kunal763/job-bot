#!/usr/bin/env bash
# ==============================================================================
# Job Bot - Native Android Termux Setup Script
# Installs PRoot Ubuntu, ARM64 Chromium, Python 3, uv, and creates 1-tap alias
# ==============================================================================
set -e

echo "=================================================="
echo "🚀 Setting up Job Bot Natively on Android (Termux)"
echo "=================================================="

# Check if running in Termux
if [ -d "/data/data/com.termux" ]; then
    echo "✔ Detected Termux environment on Android."
    pkg update -y
    pkg install -y proot-distro git curl wget tar openssh

    echo "✔ Installing/Verifying PRoot Ubuntu container..."
    if ! proot-distro list | grep -q "ubuntu.*installed"; then
        proot-distro install ubuntu
    fi

    # Write the inner provisioning script for Ubuntu
    UBUNTU_ROOT="/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root"
    cat << 'EOF' > "${UBUNTU_ROOT}/setup_job_bot_ubuntu.sh"
#!/usr/bin/env bash
set -e
echo "📦 Installing Ubuntu packages (Python 3, Chromium, poppler)..."
apt update -y
apt install -y python3 python3-pip python3-venv git curl wget poppler-utils build-essential software-properties-common
add-apt-repository ppa:xtradeb/apps -y
apt update -y
apt install -y chromium

# Install uv for lightning fast Python execution
if ! command -v uv &> /dev/null && [ ! -f "$HOME/.local/bin/uv" ]; then
    echo "⚡ Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

export PATH="$HOME/.local/bin:$PATH"
echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> $HOME/.bashrc

echo "✔ PRoot Ubuntu packages and UV installed successfully!"
EOF
    chmod +x "${UBUNTU_ROOT}/setup_job_bot_ubuntu.sh"

    # Execute inner setup script inside Ubuntu
    proot-distro login ubuntu -- bash /root/setup_job_bot_ubuntu.sh

    # Install 'jobbot' shortcut inside Ubuntu as well
    cat << 'EOF' > "${UBUNTU_ROOT}/usr/local/bin/jobbot"
#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/job-bot" && uv run job-bot "$@"
EOF
    chmod +x "${UBUNTU_ROOT}/usr/local/bin/jobbot"

    # Setup 1-tap wrapper script in Termux $PREFIX/bin/jobbot
    cat << 'EOF' > "$PREFIX/bin/jobbot"
#!/data/data/com.termux/files/usr/bin/bash
proot-distro login ubuntu -- bash -c 'export PATH=$HOME/.local/bin:$PATH; cd $HOME/job-bot && uv run job-bot "$@"' _ "$@"
EOF
    chmod +x "$PREFIX/bin/jobbot"
    echo "✔ Created native 'jobbot' command in Termux ($PREFIX/bin/jobbot)."

    echo ""
    echo "=================================================="
    echo "🎉 Android setup complete!"
    echo "You can now run Job Bot directly from Termux anytime:"
    echo "  jobbot rank --platform yc"
    echo "  jobbot apply --platform yc --live --limit 5"
    echo "=================================================="
else
    echo "This script is intended to be run inside Termux on Android."
    exit 1
fi
