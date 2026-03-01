# Project Loom: VPS Deployment Guide

Project Loom is designed to run autonomously on a remote server. This guide explains how to set up, deploy, and manage multiple Loom instances.

---

## 1. Quick Setup (VPS)

On a fresh Ubuntu/Debian VPS, run the setup script to install Docker and system dependencies:

```bash
# Upload or create the script on the VPS
curl -fsSL https://raw.githubusercontent.com/<repo>/main/setup_vps.sh -o setup_vps.sh
chmod +x setup_vps.sh
./setup_vps.sh
```

---

## 2. Deploying Your Code

From your local machine, use the deployment helper to sync your files:

```bash
chmod +x deploy_vps.sh
./deploy_vps.sh user@vps-ip /home/user/loom
```

Then SSH into the VPS and start the container:

```bash
cd loom
docker compose up -d --build
```

---

## 3. Running Multiple Instances

To run multiple independent "Loom Factory" instances (e.g., for different experiments or projects), follow these steps:

### Option A: Separate Service Blocks (Recommended for isolation)
Edit your `docker-compose.yml` to define multiple services. Each service should have its own volume mappings for `loom_memory.json`, `archive`, and `app`.

```yaml
services:
  loom-alpha:
    build: .
    volumes:
      - ./loom_memory_alpha.json:/app/loom_memory.json
      - ./archive_alpha:/app/archive
      - ./app_alpha:/app/app
      - ./viewer_alpha:/app/viewer/public/artifacts
    ports:
      - "8081:8080"
    env_file: .env_alpha

  loom-beta:
    build: .
    volumes:
      - ./loom_memory_beta.json:/app/loom_memory.json
      - ./archive_beta:/app/archive
      - ./app_beta:/app/app
      - ./viewer_beta:/app/viewer/public/artifacts
    ports:
      - "8082:8080"
    env_file: .env_beta
```

### Option B: Multiple Project Folders
Clone the repository into separate folders on the VPS:
- `/home/user/loom-run-1/`
- `/home/user/loom-run-2/`

Each will have its own `docker-compose.yml` and `.env`. You will just need to change the **external port** in each `docker-compose.yml` (e.g., 8081, 8082) to avoid collisions.

---

## 4. Monitoring

Access your dashboards at:
- `http://<vps-ip>:8080/viewer/` (Loom Main)
- `http://<vps-ip>:8081/viewer/` (Loom Alpha)
- etc.

Check logs for any instance:
```bash
docker compose logs -f loom-main
```

---

## 5. Security Note

By default, the dashboard (port 8080) is exposed publicly. For production use, consider:
- **SSH Tunneling**: Only allow port 8080 from localhost and use `ssh -L 8080:localhost:8080 user@vps-ip` to view locally.
- **Reverse Proxy**: Use Nginx or Caddy with Basic Auth.
- **Firewall**: Restrict port 8080 to your own IP using `ufw`.
