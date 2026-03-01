#!/bin/bash

# Project Loom Deployment Helper
# Usage: ./deploy_vps.sh user@vps-ip /path/to/destination

REMOTE=$1
DEST=$2

if [ -z "$REMOTE" ] || [ -z "$DEST" ]; then
    echo "Usage: ./deploy_vps.sh user@vps-ip /path/to/destination"
    echo "Example: ./deploy_vps.sh root@1.2.3.4 /root/loom"
    exit 1
fi

echo "--- Preparing Loom for Remote Deployment ---"

# Exclude large and unnecessary directories
EXCLUDES=(
    "--exclude=.git"
    "--exclude=__pycache__"
    "--exclude=node_modules"
    "--exclude=dist"
    "--exclude=.idea"
    "--exclude=.vscode"
    "--exclude=playwright-report"
    "--exclude=test-results"
)

echo "--- Syncing to $REMOTE:$DEST ---"

# Sync project files
rsync -avz --progress "${EXCLUDES[@]}" ./ $REMOTE:$DEST

# Helpful follow-up command
echo "--- Deployment Sync Complete! ---"
echo ""
echo "Run this on your VPS to start the containers:"
echo "ssh $REMOTE "cd $DEST && docker compose up -d --build""
echo ""
echo "Dashboard will be at http://$(echo $REMOTE | cut -d'@' -f2):8080/viewer/"
