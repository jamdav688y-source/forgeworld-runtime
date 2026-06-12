#!/data/data/com.termux/files/usr/bin/bash

cd ~/forgeworld

{
echo ""
echo "DATE: $(date)"
echo "STATUS SNAPSHOT:"
echo "Storage:"
df -h ~ | tail -1
echo "---"
} >> logs/phone_health.log

echo "Logged phone health."
