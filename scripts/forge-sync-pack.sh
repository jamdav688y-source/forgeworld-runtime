#!/data/data/com.termux/files/usr/bin/bash

cd ~/forgeworld

mkdir -p sync

tar -czf sync/forgeworld-phone-sync-$(date +%Y%m%d-%H%M%S).tar.gz \
README.md STATUS.md TASKS.md CAPTURE.md commands inbox notes ideas bugs logs 2>/dev/null

echo "Sync package created:"
ls -lh sync/*.tar.gz | tail -1
