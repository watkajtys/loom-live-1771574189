# Project Loom 2.0: Studio Access & Management

This document provides the essential information for accessing and managing the autonomous Loom Studio running on your Hetzner box.

---

## 1. Remote Server Identity
*   **IP Address:** `46.62.197.70`
*   **Username:** `root`
*   **Location:** `/root/loom`
*   **Authentication:** Pre-configured via your local Windows RSA SSH key.

---

## 2. Web Interfaces

### A. The Observer Dashboard (The Brain)
Watch the Overseer brainstorm concepts, review Stitch designs, and track Jules as it writes the code.
*   **URL:** [http://46.62.197.70:8080/viewer/](http://46.62.197.70:8080/viewer/)
*   **Pro Tip:** If you see "ghost" data from a previous run, use **Ctrl + F5** to force a browser cache refresh.

### B. The Database Soul (PocketBase)
This is the live real-time backend. The Overseer autonomously creates collections (tables) here before coding the frontend.
*   **URL:** [http://46.62.197.70:8090/_/](http://46.62.197.70:8090/_/)
*   **Login:** `admin@loom.local`
*   **Password:** `loom_secure_password`

---

## 3. Command Line Management (SSH)

To manage the studio, SSH into the box from your local terminal:
```bash
ssh root@46.62.197.70
```

### Watching the Factory Floor (Logs)
To see exactly what the Overseer and Jules are doing in real-time:
```bash
docker logs loom-main -f
```

### Studio Health Check
Verify the containers are running and check their resource usage:
```bash
docker ps
docker stats
```

### Restarting the Factory
If the loop hangs or you want to pick up manual code changes:
```bash
cd /root/loom
docker compose restart loom-main
```

---

## 4. The "Scorched Earth" Reset
If you want to end the current project and start a **100% fresh autonomous run** with a clean database and new idea, run this one-liner:

```bash
cd /root/loom && 
docker compose down && 
rm -rf pb_data session_state.json loom_memory.json viewer/public/artifacts/* app/* && 
mkdir -p viewer/public/artifacts && 
docker compose up -d
```

---

## 5. Architectural Notes
*   **Full-Stack Pods:** Every Loom session consists of two containers: `loom-main` (the Python brain + React builder) and `loom-pocketbase` (the database sidecar).
*   **Infrastructure-as-Code:** The Overseer automatically provisions the PocketBase schema based on the project's `[DATA_MODEL]`.
*   **Auto-Identity:** Git credentials and Docker networking are automatically configured on startup—the server is fully self-healing.
