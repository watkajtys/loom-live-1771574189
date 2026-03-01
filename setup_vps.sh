#!/bin/bash
set -e

# Project Loom VPS Setup Script (Ubuntu/Debian)
echo "------------------------------------------------"
echo "--- Project Loom: VPS Environment Setup ---"
echo "------------------------------------------------"

# 1. Update system and install basics
echo "[1/4] Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y curl git gnupg lsb-release ca-certificates

# 2. Install Docker (the clean way)
echo "[2/4] Installing Docker Engine..."
if ! [ -x "$(command -v docker)" ]; then
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo 
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu 
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
else
    echo "Docker is already installed. Skipping..."
fi

# 3. Enable Docker for current user
echo "[3/4] Configuring Docker permissions..."
sudo usermod -aG docker $USER || true

# 4. Final check and guidance
echo "[4/4] Environment Ready!"
echo ""
echo "Next Steps:"
echo "1. Log out and back in (to apply Docker group changes)."
echo "2. Clone your repo: git clone <repo_url> loom"
echo "3. Go into the directory: cd loom"
echo "4. Create your .env file: nano .env"
echo "5. Start Loom: docker compose up -d"
echo ""
echo "The dashboard will be available at: http://<your-vps-ip>:8080/viewer/"
echo "------------------------------------------------"
