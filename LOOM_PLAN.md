# Project Loom: The Infinite Builder Loop

An autonomous, self-correcting agentic loop that designs, implements, and refines React web applications until it achieves "Happiness."

## 1. Vision
To create a fully autonomous software engineering loop where a "Project Manager" LLM (The Overseer) coordinates specialized AI sub-agents to build high-quality web applications. The system iterates in a continuous loop: **Inspiration -> Design -> Build -> Critique -> Happiness/Correction.**

---

## 2. Core Architecture

### A. The Overseer (Gemini Pro)
*   **Role:** The Executive Function.
*   **Responsibilities:**
    *   High-level goal setting and planning.
    *   Managing the Git repository (Branching, Merging, Rollbacks).
    *   Coordinating tool calls to Stitch, Jules, and Sub-agents.
    *   Deciding the "Happiness Score" based on sub-agent feedback.

### B. The Hands (Execution)
*   **Designer (Stitch MCP):** 
    *   Provides Visual DNA (Tailwind HTML/CSS).
    *   Tools: `create_screen`, `get_screen_image`, `get_screen_code`.
*   **Engineer (Jules API):** 
    *   Handles Repository-level implementation directly via the `v1alpha` API.
    *   Reads target GitHub repository (with pagination support) and converts Stitch HTML into modular React components.
    *   Returns a surgical `gitPatch` applied by the Conductor to modify files without destroying context.
    *   Reference: [Jules CLI Docs](https://jules.google/docs/cli/reference/) | [Jules API Docs](https://developers.google.com/jules/api)

### C. The Judges (Quality Control)
*   **The Architect (Sub-agent):** Peer-reviews code for React best practices, TypeScript safety, and Tailwind standards.
*   **The Eye (Vision Sub-agent):** Uses Gemini Pro Vision to compare the Live App vs. the Stitch Design for visual fidelity.
*   **The Sentry (Runtime Sub-agent):** Monitors the Vite dev server for console errors, runtime crashes, and performance bottlenecks using Playwright.

---

## 3. Tech Stack & Constraints
*   **Runtime:** React (Vite) - **No Next.js.**
*   **Styling:** Tailwind CSS.
*   **Language:** TypeScript (Strict mode).
*   **State Management:** Git (Local).
*   **Communication:** WebSocket-based Broadcast Dashboard for real-time visualization.

---

## 4. The Loom Loop (The Workflow)

1.  **Phase 1: Inspiration**
    *   Overseer defines the feature or app goal.
    *   Create a new feature branch: `git checkout -b feat/feature-name`.
2.  **Phase 2: Design (Stitch)**
    *   Overseer calls Stitch to generate the UI.
    *   Visual assets and HTML/Tailwind are saved to a `design/` artifact folder.
3.  **Phase 3: Implementation (Jules)**
    *   Overseer tasks Jules to implement the design in the `src/` directory.
    *   Jules connects via the real Jules API (using paginated source discovery to find the target GitHub repo), performs repo-wide edits, and returns a surgical `gitPatch` which the Conductor applies.
4.  **Phase 4: Evaluation (The Judges)**
    *   **Architect** scans the code.
    *   **Sentry** checks `localhost:5173` for crashes.
    *   **Eye** compares screenshots.
5.  **Phase 5: The Happiness Decision & Meta Loop**
    *   **If Score >= 8/10:** Merge to `main`, commit with a "Happy" message. Then, the Overseer engages the **Meta Loop** to autonomously brainstorm the next small feature, visual improvement, or iteration to keep the build progressing, setting the new "Inspiration Goal" and starting the next loop.
    *   **If Score < 8/10:** Overseer analyzes the critiques, identifies the root cause, and tasks Jules/Stitch with specific fixes in the current branch (**Refinement Loop**).

---

## 5. Broadcast & Streaming Strategy
A dedicated "Director's Monitor" webapp will visualize the bot's internal state:
*   **Thinking Pane:** Live text of the Overseer's plan and internal monologue.
*   **Forge Pane:** Real-time code changes and the Git graph.
*   **Mirror Pane:** Vision agent's bounding boxes over the UI showing detected "Visual Bugs."
*   **Live Pane:** The actual running app (HMR updates).

---

## 6. Engineering Details

### A. State Persistence (The "Resurrection" Logic)
*   **Mechanism:** A local `session_state.json` file.
*   **Tracking:** Current iteration index, active Git branch, current "Inspiration Goal," and a history of "Happiness Scores."
*   **Recovery:** On startup, the Conductor reads this file to resume the loop from the last recorded state.

### B. Initial Seed Generation
*   **Initialization Phase:** Before the first loop, the bot executes a "Scaffolding" task.
*   **Jules Task:** `jules task "Initialize a React + Vite + Tailwind project. Set up a /design folder and a clean /src structure with a dynamic App.tsx to host Stitch screens."`
*   **Standardization:** This ensures all subsequent iterations have a predictable environment.

### C. Authentication Strategy (The "Keychain")
*   **Zero Interaction:** Use API Keys for all services to avoid interactive login prompts.
*   **Environment Variables:** 
    *   `GEMINI_API_KEY`: Overseer & Judges.
    *   `JULES_API_KEY`: Implementation (via API/CLI).
    *   `STITCH_API_KEY`: Design (via MCP).
    *   `GITHUB_TOKEN`: Repository management.

### D. The Critic Personas (Constructive Tension)
*   **The Builder (Jules):** Prompted as an "Optimistic Implementer" focused on speed and completion.
*   **The Architect (Reviewer):** Prompted as a "Grumpy Senior Architect" with a bias toward rejecting code for minor infractions (missing types, bad naming).
*   **The Eye (Vision):** Prompted as a "Pixel-Perfect Designer" who is never truly satisfied.

### E. Process Management (The "Phoenix Server")
*   **The Problem:** Long-running `npm run dev` processes can become "zombies," hold onto ports (5173), or serve stale cache after branch switches.
*   **The Solution:** The Conductor treats the dev server as ephemeral.
    1.  **Kill:** Before any Review Phase, explicitly kill any process listening on port 5173.
    2.  **Spawn:** Start a fresh `npm run dev` process in the background.
    3.  **Wait:** Poll `http://localhost:5173` until it returns 200 OK.
    4.  **Review:** Perform Vision and Runtime checks.
    5.  **Terminate:** Immediately kill the process to free resources for the next loop.

## 7. Risk Management & Safety
*   **Git Rollbacks:** If the bot breaks the build beyond repair, it must `git reset --hard` to the last "Happy" commit on `main`.
*   **Token Budget:** The Conductor will monitor API usage and halt the loop if it exceeds a set dollar amount.
*   **Halt Detection:** If the "Happiness Score" doesn't improve for 3 consecutive iterations, the Overseer must pivot its strategy (e.g., "Simplify the design" or "Use a different library").
