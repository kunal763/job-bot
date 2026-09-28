#!/usr/bin/env bash
# ==============================================================================
# Creates a lightweight (<1MB) sync archive for Android phone deployment
# Includes profile, database, active browser sessions/cookies, and environment
# ==============================================================================
set -e

ARCHIVE_NAME="job_bot_phone_sync.tar.gz"
echo "📦 Packaging Job Bot session, profile, and database for phone..."

tar -czf "${ARCHIVE_NAME}" \
  --exclude="*Cache*" \
  --exclude="*.pma" \
  profile.json \
  .env \
  Kunal_resume.txt \
  data/job_bot.db \
  data/Kunal_Singh_Resume.pdf \
  data/browser_context

SIZE=$(du -sh "${ARCHIVE_NAME}" | awk '{print $1}')
echo "✔ Created ${ARCHIVE_NAME} (${SIZE}) successfully!"
echo ""
echo "To transfer to your phone over local Wi-Fi:"
echo "1. Run on this computer: python3 -m http.server 8080"
echo "2. Inside Termux Ubuntu on your phone: curl -O http://$(hostname -I | awk '{print $1}'):8080/${ARCHIVE_NAME}"
echo "3. Extract on phone: tar -xzf ${ARCHIVE_NAME} -C ~/job-bot/"
