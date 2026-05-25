# Audit — Seattle Jet Lag Strategy Notebook (April 2026)

**Project**: `/Users/james/jetlag`  
**Notebook**: `notebooks/seattle_strategy.ipynb` (freshly reset)

---

## 1. Current State (Post-Reset)

- Notebook has been completely cleared and reset to a minimal clean skeleton (15 cells).
- Structure now follows the original approved plan:
  1. Data Loading
  2. Visualization Foundation
  3. Landmark Audit (high priority for user)
  4. Question Engine & Proposers
  5. Interactive Exploration
  6. Notes

- All previous route-drawing / `LINE_GEOMETRIES` / per-line polyline code has been **deleted**.
- Checkpoint files cleaned up.

---

## 2. What Worked Well

| Area | Assessment | Notes |
|------|------------|-------|
| **Landmark Audit concept** | Excellent | This was the user's explicit priority. The design (editable `landmarks_df` + dedicated audit map + stats table + easy extension) is still the strongest part of the project. |
| **Full-resolution points** | Good | Defaulting `cluster=False` in `create_map()` was the right call after user feedback. |
| **Download robustness** | Good | Adding `User-Agent` + fallback URLs for KCM was solid engineering. |
| **Boundary handling** | Good | Using `osmnx` for Seattle + Bellevue + Redmond is clean and accurate. |
| **Mode tagging** | Useful | Keeping `is_rapidride`, `is_link`, `is_monorail` booleans is lightweight and valuable. |
| **Project tooling** | Good | `uv`, `pyproject.toml`, and the `DATA_DIR` root-resolution logic were well handled. |

---

## 3. What Caused Significant Pain

| Issue | Root Cause | Impact | Lesson |
|-------|------------|--------|--------|
| **Route/line drawing saga** | Tried to draw "coherent segments" using crude latitude sorting + later GTFS shapes, all inside one giant notebook cell. | Repeated NameErrors, visual bugs (1 Line & 2 Line interspersed), scope hell. | Never build complex geometry logic inside a notebook cell without extracting it. |
| **Monolithic data loading cell** | Everything (download, parsing, shape loading, geometry building) lived in one cell. | Extremely hard to debug and iterate. | Split data loading into small, testable functions early. |
| **Over-engineering visualization too soon** | Tried to solve "show the network" before the basic point set + deduplication was stable. | Wasted time and created technical debt that had to be deleted. | Get points + dedup + basic map working perfectly before adding lines. |
| **Deduplication inconsistency** | Multiple different approaches (exact match → rounded + normalized → per-line). | Duplicate points kept appearing. | Decide on dedup strategy once and centralize it. |
| **GTFS source confusion** | Started with consolidated feed (which lacked stop_times for buses), then switched sources mid-stream. | Wasted runs and confusion. | Validate data completeness (especially stop_times) on the very first download. |

---

## 4. Technical Recommendations (Going Forward)

### Data Loading Strategy (Highest Risk Area)

**Recommended approach**:

1. **Primary source for RapidRide**: King County Metro GTFS (via Sound Transit mirror)
2. **Primary source for Link**: Sound Transit Rail GTFS
3. **Monorail**: Hardcode the two stops (or use tiny dedicated feed)

Do **not** use the consolidated feed again for stop-level analysis.

Key functions that should exist (outside the notebook if possible):

- `download_gtfs(urls, dest_dir)` — robust with headers + fallbacks (keep this)
- `load_candidates(kcm_dir, st_dir) -> pd.DataFrame` — returns clean deduplicated stops with mode flags
- Strong deduplication (rounded lat/lon + name normalization) done **once**, centrally.

### Visualization

- Keep `create_map(df, cluster=False, ...)` as the single source of truth.
- Do **not** attempt line drawing until:
  - Points + dedup + filtering are rock solid
  - User explicitly asks again (they were frustrated by it)

### Landmark Audit

This section can (and should) be built next. It is largely independent of the route drama.

### Code Organization

Strong recommendation: Move non-trivial functions out of the notebook into a `src/jetlag_seattle/` package once the logic stabilizes. Notebooks should become thin orchestration + exploration layers.

---

## 5. Immediate Recommended Next Steps

1. **Keep the notebook clean** (already done).
2. Re-implement **Data Loading** from scratch with the lessons above (small, focused functions).
3. Build the **Landmark Audit** section next (user's stated priority).
4. Only after (2) and (3) are solid, revisit whether any form of line visualization is actually needed.
5. Consider extracting reusable code once the first working end-to-end flow exists.

---

## 6. Files Status

- `notebooks/seattle_strategy.ipynb` — Clean skeleton ✓
- `AUDIT.md` — This document (new)
- Old checkpoint removed ✓
- `pyproject.toml` + dependencies — Still appropriate
- `README.md` — Slightly outdated (mentions removed features) but usable

---

**Bottom line**: The project has good bones (especially the Landmark Audit idea and tooling). The main damage came from trying to solve a hard visualization problem (accurate per-line geometry) too early, inside a notebook, without stable data foundations.

We're now in a much better position to start over cleanly.

*Audit performed after notebook reset on 2026-05-24.*
