# Jet Lag Seattle — Hiding Spot Finder

Fork of `web/` focused on **finding hiding places**, using **official Lifack zone radii**.

## Why this fork exists

The combined map treated radii as freeform drawing tools and a global ¼-mile walkshed union.  
In Hide and Seek, a **hiding zone is one circle around one transit station**:

| Game size | Zone radius | Hide period |
|-----------|-------------|-------------|
| Small / Medium | **¼ mile** (402.336 m) | 30 / 60 min |
| Large | **½ mile** (804.672 m) | 180 min |

Rules distill: [`../RULES.md`](../RULES.md) (from [lifack.ch](https://www.lifack.ch/docs/quick_start_guide/)).

## Run

```bash
cd web-hiding
npm install
npm run dev
```

Opens on **http://localhost:5174** (port differs from the combined map’s 5173).

Data is shared via symlink: `public/data` → `../web/public/data`.

## What it does

- Game size switcher that sets the **correct** zone radius
- Click a station → official zone circle + **path-proximity sample points**
- Green samples = within path buffer (hideable-ish); red = too far from marked paths
- Buffer modes: **strict** (10 ft from OSM centerline) vs **practical** (half-width + 10 ft)
- Radar presets: official `¼ · ½ · 1 · 3 · 5 · 10 · 25 · 50 · 100` mi
- Rank stations by **hideable fraction of zone only** (path-adjacent sample hits)
- No parks / tentacles / radar heuristics in the score

## Path data + fraction scores

OSM does not publish ordinary road **polygons** — only centerlines.

```bash
# all roads+paths (no type thinning) + 5k-sample hideable_frac scores
.venv/bin/python scripts/rebuild_paths_and_score.py
```

Writes into `web/public/data/`:

- `walkable_paths.geojson` — all OSM road/path centerlines (~50MB)
- `zone_hideable_scores.json` — per-stop `hideable_frac` only (n=5000)

## Not the same as

- Global walkshed of all stops (not a legal zone)
- Freeform “any radius” strategy doodles without game-size context
- A guarantee the spot is public/stayable — only path adjacency
