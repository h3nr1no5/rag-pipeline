# Project Agents (Free Models Only)

This project uses a **multi-agent orchestration system** powered by OpenCode with **only free models** (via OpenCode Zen).

The central **@coordinator** (Big Pickle) decomposes tasks and delegates to specialized sub-agents.

## Core Agents

| Agent                     | Role                              | Free Model                     | Temp | Key Strength                     |
|---------------------------|-----------------------------------|--------------------------------|------|----------------------------------|
| @coordinator              | Orchestrator                      | big-pickle                     | 0.1  | Planning & delegation            |
| @subagents/coder          | General Implementation            | deepseek-v4-flash-free         | 0.2  | Code writing                     |
| @subagents/backend        | Backend APIs & Logic              | deepseek-v4-flash-free         | 0.2  | Server-side & databases          |
| @subagents/frontend       | UI/UX & Components                | deepseek-v4-flash-free         | 0.25 | Frontend implementation          |
| @subagents/reviewer       | Code Quality & Review             | deepseek-v4-flash-free         | 0.05 | Critical feedback                |
| @subagents/tester         | Testing                           | deepseek-v4-flash-free         | 0.2  | Test generation                  |
| @subagents/security       | Security Auditing                 | deepseek-v4-flash-free         | 0.05 | Vulnerability detection          |
| @subagents/architect      | High-Level Design                 | big-pickle                     | 0.1  | Architecture & trade-offs        |
| @subagents/owner          | Decision Making & Approval        | big-pickle                     | 0.1  | Final sign-off & prioritization  |
| @subagents/docs           | Documentation                     | deepseek-v4-flash-free         | 0.3  | Technical writing                |
| @subagents/researcher     | Codebase Exploration              | big-pickle                     | 0.2  | Analysis & context               |
| @subagents/devops         | DevOps & Infrastructure           | deepseek-v4-flash-free         | 0.2  | Deployments & CI/CD              |
| @subagents/e2e            | E2E / Playwright Testing          | deepseek-v4-flash-free         | 0.2  | Browser test automation          |
| @subagents/prompter       | Prompt Engineering                | deepseek-v4-flash-free         | 0.5  | Prompt optimization              |

## Usage
- Start with `@coordinator` for best results.
- All models are free (as of April 2026). Run `/models` to confirm current availability.
- Big Pickle is used for coordination and deep reasoning tasks.
- Minimax M2.5 Free offers the best speed/quality balance for implementation.
- Qwen3.6 Plus Free is used for review & security (strong critic among free options).

---
## Mandatory Security Policy

**Security review is non-negotiable.**

- Every feature, refactor, or code change **must** receive a security review from @subagents/security before final delivery.
- The @coordinator is responsible for enforcing this gate in every workflow.
- Violations of this policy are not allowed.

**Last updated**: April 2026  
**Free models only** — No paid API keys required.