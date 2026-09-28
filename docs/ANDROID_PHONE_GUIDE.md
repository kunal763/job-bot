# 📱 Native Android (Termux) Guide for Job Bot

Run the fully functional **Job Bot** (Python, Playwright headless browser, SQLite DB, and Groq AI Copilot) directly on your Android phone hardware without needing any laptop or cloud server.

---

## 1. Install Termux on Android

> ⚠️ **Important:** Do NOT install Termux from Google Play Store (it is deprecated and broken).

* Download and install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) or from the [Termux GitHub Releases](https://github.com/termux/termux-app/releases/latest) (download `termux-app_v..._universal.apk` or `arm64-v8a.apk`).

---

## 2. Set Up the Linux Container (One-Time Setup)

Open the **Termux** app on your phone and run this single command:

```bash
pkg update -y && pkg install -y git curl proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
```

Inside the Ubuntu prompt (`root@localhost:~#`), install Python, Chromium, and `uv`:

```bash
apt update -y && apt install -y python3 python3-pip python3-venv git curl chromium-browser poppler-utils build-essential
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Clone the Job Bot repository:

```bash
git clone https://github.com/kunal763/job-bot.git ~/job-bot
cd ~/job-bot
uv sync
```

---

## 3. Sync Your Session & Profile to Phone

To copy your pre-authenticated YC cookies, `.env`, resume, and database from your laptop to your phone:

### Step A: On your laptop (in the job-bot directory)
Run:
```bash
./scripts/create_phone_bundle.sh
python3 -m http.server 8080
```

### Step B: On your phone (inside Termux Ubuntu)
Run (replace `<LAPTOP_IP>` with your laptop's IP, e.g. `10.182.14.48` shown on laptop):
```bash
cd ~/job-bot
curl -O http://<LAPTOP_IP>:8080/job_bot_phone_sync.tar.gz
tar -xzf job_bot_phone_sync.tar.gz
rm job_bot_phone_sync.tar.gz
```

---

## 4. Set Up 1-Tap Shortcut in Termux

To make `jobbot` callable directly from anywhere:

### Inside Ubuntu (`root@localhost:~#`):
```bash
cat << 'EOF' > /usr/local/bin/jobbot
#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/job-bot" && uv run job-bot "$@"
EOF
chmod +x /usr/local/bin/jobbot
```

### In Termux (Outside Ubuntu, prompt ends with `$`):
Type `exit` to return to Termux, then run:

```bash
cat << 'EOF' > $PREFIX/bin/jobbot
#!/data/data/com.termux/files/usr/bin/bash
proot-distro login ubuntu -- bash -c 'export PATH=$HOME/.local/bin:$PATH; cd $HOME/job-bot && uv run job-bot "$@"' _ "$@"
EOF
chmod +x $PREFIX/bin/jobbot
```

Now you have a native `jobbot` command that works both from Termux and from inside Ubuntu!

---

## 5. Daily Usage from Phone Anywhere

Open Termux on your phone anytime, anywhere (using mobile data or Wi-Fi):

### View Top High-Probability YC Matches:
```bash
jobbot rank --platform yc --limit 5
```

### Dry-Run Application on Phone:
```bash
jobbot apply --platform yc --limit 5 --headless
```

### Submit Live Top 5 Applications:
```bash
jobbot apply --platform yc --live --limit 5 --headless
```

### Search New Startup Jobs:
```bash
jobbot search --platform yc --keywords Python --keywords Backend
```
