Synthetic User Generation Platform - Milestone 4 Final

CHANGES
- Survey Mode now owns the single "Ask All Personas" action. Interview Mode has no broadcast block.
- Survey responses and Survey Insights & Scoring remain below Survey Mode.
- Interview responses and Interview Insights remain below Interview Mode.
- Raw JSON Schema UI was removed.
- Product Domain is a dropdown with an Other option.
- Persona count supports 1-150. Generation is dynamically batched in groups of 5 with controlled parallelism and rate-limit retries.
- Persona generation contains no hard-coded persona dataset.
- Narrative persona fields are enforced to be meaningful. Pain Points must be a concrete 2-3 line explanation, not a one-word label. Psychology, Personality, Goals, Target Audience, Research Objective, Tech Adoption, Preferred Channel and Memory are also descriptive.
- Survey Ask All uses controlled parallel requests and retries so large cohorts respond faster.
- Milestone 4 visual dashboard and professional ReportLab PDF remain included.
- Saved History includes permanent delete.

RUN
1. Put your Groq key in .environment as GROQ_API_KEY=...
   Optional: GROQ_API_KEYS=key1,key2 for legitimate separate quotas/projects. Multiple keys do NOT bypass an organization-wide Groq limit.
2. Install dependencies: pip install -r requirements.txt
3. Start backend: python main.py
4. Start frontend with your normal Vite command (for example npm run dev).

IMPORTANT
If port 8000 is already in use, do not start a second backend. Stop the old process or use the already-running backend.

