#!/bin/bash
cd "$(dirname "$0")"
echo "Starting S26 backend on http://0.0.0.0:8501"
python3 backend.py
