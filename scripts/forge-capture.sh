#!/data/data/com.termux/files/usr/bin/bash

cd ~/forgeworld

echo ""
echo "FORGE CAPTURE"
echo "Type category: idea / bug / task / observation / command"
read -r category

echo "Enter detail:"
read -r detail

{
echo ""
echo "DATE: $(date)"
echo "TYPE: $category"
echo "DETAIL: $detail"
echo "NEXT ACTION: review on laptop"
echo "---"
} >> CAPTURE.md

echo "Captured."
