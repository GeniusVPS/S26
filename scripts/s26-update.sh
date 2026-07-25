#!/bin/bash
# S26 靜態數據自動更新（每小時）
cd ~/stock-system
python3 generate_static.py >> /tmp/s26-generate.log 2>&1
echo "--- $(date) ---" >> /tmp/s26-generate.log
