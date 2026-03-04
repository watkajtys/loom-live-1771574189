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
- [ ] Retain Jules Run Status in Dashboard: Ensure the active Jules coding session remains visible in the iteration history or dashboard even after the patch is generated, rather than disappearing abruptly, to provide a smoother and more continuous visual experience of the process.


## 8. App Meta & Continuity Strategy (The 'Schizophrenic App' Fix)
*   **The Problem:** Currently, every iteration acts as a blank slate. The Overseer guesses the next feature from a screenshot, Stitch creates a brand-new screen design from scratch (losing the color palette/theme), and Jules attempts to overwrite the entire app to match the new image.
*   **The Solution:**
    1.  **APP_META.md:** A source-of-truth document maintaining the core product identity (Name, Theme, Core Colors, Architecture). The Overseer reads this during brainstorming and updates it when adding major systems.
    2.  **Stateful Design (Stitch):** Do not reset stitch_screen_id to None after an iteration. Pass the previous screen_id back to Stitch so it edits the *existing* design rather than inventing a new one, preserving the visual DNA.
    3.  **Contextual Coding (Jules):** Prompt Jules with the APP_META.md context and explicitly instruct it to *integrate* new features into the existing architecture rather than overwriting it.

---

## 9. Advanced Factory Evolution (Current Build)

### A. The Triage Highway ([REQUIRES_DESIGN])
The Overseer now performs a triage check during brainstorming. If a feature is purely architectural (logic/state/performance), it is flagged as `REQUIRES_DESIGN: FALSE`. This triggers a bypass of the Stitch/Vision pipeline, sending the task directly to Jules for faster, more focused execution.

### B. Two-Pass Design System (Layout then Theme)
To ensure high-quality UI without overwhelming the model, Iteration 1 now executes a two-stage design process:
1. **Layout Pass**: Stitch generates 5 structural variants. Overseer selects the best layout.
2. **Theme Pass**: Stitch generates 5 color/typography variants of that layout. Overseer selects the winner and locks in the `APP_META`.

### C. Persistent Repo Memory (Reflection Pass)
At the end of every iteration, the Overseer performs a "Reflection Pass," logging technical successes and failures into a persistent `repo_memory` KV store. These learnings are injected into all future brainstorming and implementation prompts to ensure the agents "learn" over time.

### D. Agentic Branching & Indexing Sync
To ensure cumulative progress, the factory now uses a single **Agentic Branch** per iteration.
*   **The Ledger:** All implementation attempts are committed to this branch, providing Jules with the full context of its previous work.
*   **Indexing Sync:** The `JulesClient` now polls the `/sources` API to confirm branch indexing before starting a session, eliminating "blank slate" hallucinations.

---

## 10. Future Horizons (The Ultimate Factory)

To scale Project Loom from a toy to an enterprise factory, we plan to implement specialized asynchronous sentries and workflows:

### A. "Invasion Mode" (Existing Codebases)
Instead of starting from a blank canvas, Loom will be able to take over existing, legacy codebases.
1. **The Surveyor (AST Parsing):** Runs local AST parsers (e.g., `ts-morph`) to generate a `CODEBASE_MAP.json` detailing exports, imports, and component hierarchies.
2. **The Archeologist (Vision + DOM):** Uses a Vision Agent alongside a DOM Inspector to bridge the gap between code and UI, mapping visual elements directly to source files.
3. **Ticket Ingestion:** Instead of open-ended brainstorming, the Overseer works directly off a GitHub Issues or Jira backlog.

### B. Test-Driven Execution (TDE)
Static screenshots are insufficient for verifying complex UI logic (e.g., dropdowns, modals, state changes).
1. **Test Generator**: Overseer tasks a sub-agent to write a Playwright integration test for the new feature *before* it is built.
2. **Execution**: Jules is handed the failing test script alongside the UI goal and must write React code to make the test pass.
3. **The Sentry**: Evaluates success based on binary Playwright test execution (`npx playwright test`), eliminating LLM subjectivity.

### C. The "UI Kit" Approach
To prevent design drift over multiple iterations, Loom will generate a foundational Design System before building the app.
* **Phase 0**: Overseer tasks Stitch with generating a comprehensive UI Kit (buttons in all states, typography scales, full color palettes).
* **Phase 1**: The Overseer extracts a massive, robust `APP_META` from this UI Kit, ensuring the app remains perfectly cohesive even at Iteration 50.

### D. Specialized Sentries
*   **The Friction Report (UX Taste):** A specialized sub-agent that "plays" with the app using Playwright to detect jank, small tap targets, or confusing flows.
*   **The Dependency Auditor (Bloat Loop):** Fails builds if Jules imports massive libraries (e.g., `moment.js`) for trivial tasks, enforcing a "Vanilla-First" philosophy.
*   **The Janitor:** A garbage collection agent that runs periodically to find and delete unused React components and dead code.

---

## 11. The Studio Era (Loom 2.0)

We are evolving from an "App Builder" into a "Multiplexed Product Studio." This phase focuses on making the apps "real" (Persistence) and "live" (Shared Hosting).

### A. The Director's Gate (Manual Breakpoints)
To transition from an "Autonomous Factory" to a "Collaborative Studio," we introduce manual approval gates.
*   **Checkpoints:** The Overseer pauses and awaits a "Go/No-Go" after **Concept Brainstorming**, **Design Selection**, and **Final Validation** before merging to `main`.

### B. Persistent Persistence (PocketBase)
Apps are no longer ephemeral frontends. Every Loom project now has a "Data Soul."
*   **Zero-Key Automation:** The Overseer autonomously spins up a PocketBase instance as a Docker sidecar for every app.
*   **Data Model Phase:** The Overseer defines a `[DATA_MODEL]` (collections/fields) during Inspiration and generates a `pb_schema.json`.

### C. Shared Studio Hosting (Hetzner)
Moving away from dedicated VPS instances to a cost-effective shared model using Reverse Proxy Automation and Subdomain Logic.

### D. Operational Efficiency
*   **Model Tiering:** Use Gemini 3.1 Pro for high-level "Brain" tasks and Gemini 3 Flash for high-volume "Reviewer" tasks.
*   **Stable References:** Implementation of the `REFINEMENT` mode to prevent design drift once a UI is established.

