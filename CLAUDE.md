# SimulCTTC — QKD Satellite Simulator

This file is the project's durable memory: what SimulCTTC is, who it's for, and what
matters most. It exists so that anyone opening this repo with Claude gets the context
quickly and knows how to be useful.

It is **context, not a rulebook** — read it to understand the project, then use your own
judgment. The specific working conventions the original author follows are noted below as
*their* preferences; they don't automatically bind you.

## What this project is
SimulCTTC is a **quantum-key-distribution (QKD) satellite-link simulator**. It models the
optical satellite ↔ optical-ground-station channel physics (atmospheric turbulence, beam
wander, pointing/PAT jitter, link geometry over a pass) and the resulting secret-key
performance. The app has a Python backend under `app/` (with a pure-NumPy physics layer in
`app/physics/`) and a browser frontend under `app/static/`.

## Who built it and who it's for
- Developed by **Francesc Adrià Sancho González**, with **Harshit Tiwari** and **Satyendra
  Kumar Mishra**, at the **Space and Resilient Communications and Systems (SRCOM)** unit of
  **CTTC** (Centre Tecnològic de Telecomunicacions de Catalunya), Castelldefels, Barcelona.
- The lead author is a QKD satellite-link researcher and a domain expert in the physics
  being simulated — assume they know the physics better than you do.
- Developed at very high velocity — the core codebase was built in under a week.
- Aimed at a **conference presentation for QKD researchers (~April 2026)**, so the results
  are meant to withstand expert scrutiny.
- Licensed **MIT** (see `LICENSE`).

## What matters most here
- **Physics accuracy above all.** Equations must be correct and each formula must trace to a
  paper/textbook source. Verify physics against published literature, not model recall.
  This covers key volume, PCFLOS, beam wander, PAT jitter, and any new physics added.
- **Publication-quality output** — MATLAB-grade scientific graphs suitable for a paper.
- **Code that is verified before it ships** — it should actually run and be checked.

## Where to orient yourself in the code
This public repo is intentionally code-only. Start here:
- `README.md` — full user manual, API reference, and the formulas with their sources
- `app/physics/` — the pure-NumPy physics layer (one concern per module)
- `app/routers/` — the HTTP surface; `app/services/` — external I/O (TLEs, weather, DB)
- `app/static/` — the browser frontend (ES modules, no build step)
- `test_all.py` — the test suite; `make_figures.py` — regenerates the paper figures

The author also keeps private planning notes in a local, git-ignored `.agents/` directory.
If it isn't present in your checkout, that's expected — don't go looking for it.

## The original author's working preferences (informational — not imposed on you)
- **Commits are done manually by the author.** They prefer to verify code themselves before
  committing, so historically Claude has not run `git commit`/`push` on their behalf.
- **Model routing:** lighter models for research/planning/simple edits, stronger models for
  heavy or multi-file implementation and difficult physics logic.

> These are point-in-time notes. Verify any file, function, or flag reference against the
> current code before relying on it.
