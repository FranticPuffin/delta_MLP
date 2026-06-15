# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NASA Deep Space Network (DSN) multi-mission scheduling system using the **Δ-MILP algorithm** (Delta Mixed-Integer Linear Programming). Optimizes allocation of limited antenna resources across competing spacecraft missions with priority-aware conflict resolution. This is an academic paper reproduction (`Docs/delta.md` describes the algorithm; `Docs/Data.md` describes input parameters).

## Commands

```bash
# Run the full scheduler (MILP solve → iterative weight adjustment → CSV + Gantt chart)
python Scripts/delta.py

# Generate synthetic mission data (JSONL)
python Scripts/datapreprocess.py
```

The solver outputs:
- `dsn_schedule.csv` — per-activity schedule (Mission, Antenna, Start, End, Setup, Teardown)
- `dsn_gantt_chart.png` — visual Gantt chart colored by mission
- `Outputs/optimization_log.txt` — full iteration log (stdout is redirected here)

**Prerequisites**: Python with `pulp`, `pandas`, `matplotlib`, `numpy`. The MILP solver uses **GLPK** (`GLPK_CMD`) — GLPK must be installed on the system PATH separately (not pip-installable).

## Architecture

```
Data/*.jsonl          — Input: one JSON object per line (mission + activities + view periods)
Scripts/datapreprocess.py — Synthetic data generator (100 missions, 40 antennas, priority schedule)
Scripts/delta.py      — Main solver + visualization
Docs/                 — Algorithm reference (Chinese)
Outputs/              — Optimization logs
```

### Core class: `DeltaMILPSolver` (`Scripts/delta.py`)

| Method | Purpose |
|--------|---------|
| `_load_data()` | Parse JSONL into mission dicts |
| `_get_activity_priority()` | Compute time-weighted priority for an activity across its view periods |
| `_resolve_conflicts()` | Greedy post-MILP conflict resolver: sort by priority desc, assign antennas first-come-first-served, drop conflicts |
| `solve(mission_weights, eta_threshold)` | Build and solve the MILP — defines binary variables, objective (priority² × iter_weight), capacity/resource constraints, then runs GLPK |

### Algorithm flow (`run_dynamic_optimization`)

1. **MILP solve** — binary variables `x[activity_id]` with objective `Σ(iter_weight × priority² × x)`. Activities with `can_split=true` get XOR sub-activity variables (Constraints 6k-6m).
2. **Conflict resolution** — post-solve greedy assignment respecting antenna exclusivity and mission non-overlap.
3. **Iterative weight adjustment (Algorithm 2)** — compute per-mission satisfaction; double weights for missions below threshold η; raise η by 5% when all missions meet it. Repeat up to 10 iterations.
4. **Final reporting** — satisfaction by priority level, conflict analysis (high vs low priority outcomes), CSV export, Gantt chart.

### Data format (JSONL)

Each line is a mission object:
```json
{
  "mission_id": "DAWN",
  "total_requested_hr": 168.0,
  "base_priority": 4,
  "priority_schedule": [{"start_hr": 0.0, "end_hr": 24.17, "priority": 4}, ...],
  "activities": [{
    "activity_id": "DAWN_ACT_00",
    "d_min": 6.4, "d_max": 8.0,
    "setup_min": 60, "teardown_min": 15,
    "can_split": true,
    "view_periods": [{"antenna": "DSS-24", "start_hr": 9.58, "end_hr": 19.22}, ...]
  }]
}
```

### Key constraints
- **Resource capacity**: 40 antennas × 168 hours × 70% utilization
- **Antenna exclusivity (6h)**: one activity per antenna at a time (including setup/teardown)
- **Mission non-overlap (6j)**: a spacecraft cannot use two antennas simultaneously
- **Duration bounds (6i)**: d_min ≤ scheduled_duration ≤ d_max
- **View window (6b)**: all tracking must fall within visibility windows
- **XOR split (6k-6m)**: splittable activities get prime/double-prime sub-variables, mutually exclusive with the unsplit version

## Known simplifications

The solver picks the first view period per scheduled activity rather than selecting the optimal window. Real DSN scheduling would also account for antenna slew/setup time between different spacecraft, and the 15-minute discretization may clip precise window boundaries.
