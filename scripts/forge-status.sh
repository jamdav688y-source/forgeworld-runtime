#!/data/data/com.termux/files/usr/bin/bash
echo "========== FORGEWORLD PHONE STATUS =========="
echo "Date: $(date)"
echo ""
echo "Directory:"
pwd
echo ""
echo "Storage:"
df -h ~ | tail -1
echo ""
echo "Memory:"
free -h 2>/dev/null || echo "Memory info unavailable"
echo ""
echo "Files:"
find ~/forgeworld -maxdepth 2 -type f | wc -l
echo ""
echo "Recent captures:"
tail -20 ~/forgeworld/CAPTURE.md
echo "============================================="
