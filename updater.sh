#!/bin/bash
# Wait 80 seconds to allow the internet connection to establish
sleep 80

# updater.sh - Force overwrite local code from GitHub, then run main.py

# Define the repository directory
REPO_DIR="/home/trc/Desktop/Projects/hm_releases"
cd "$REPO_DIR" || exit 1

# Check for an internet connection (using Google DNS as a test)
if ping -c 1 8.8.8.8 > /dev/null 2>&1; then
    echo "Internet available. Forcing update from GitHub..."
    git fetch origin
    git reset --hard origin/main
else
    echo "No internet connection. Skipping update."
fi

# Launch the main Python script
python3 main.py
