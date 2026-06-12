#!/data/data/com.termux/files/usr/bin/bash

echo "Cleaning safe Termux cache only..."

pkg clean
rm -rf ~/.cache/pip 2>/dev/null
rm -rf ~/forgeworld/logs/*.tmp 2>/dev/null

echo "Clean complete. No project files deleted."
