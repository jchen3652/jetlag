# jetlag — Seattle Hide & Seek Strategy Notebook

Exploratory Jupyter notebook for discovering optimal early-game questions in *Jet Lag: The Game* (Hide & Seek mode) when played in the Seattle metro area.

**Scope**: All Link light rail stops, Seattle Monorail, and King County Metro RapidRide stops inside Seattle city limits + Bellevue + Redmond. Game starts near the Seattle Art Museum.

## Quick Start (uv — recommended)

```bash
# From this directory
uv sync
uv run jupyter lab
```

Then open `notebooks/seattle_strategy.ipynb` and **Restart & Run All**.

## Alternative (classic venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uv run jupyter lab   # or just `jupyter lab` after activation
```

## What the Notebook Contains

1. Self-contained GTFS download + parsing (Sound Transit consolidated feed).
2. Real candidate stations filtered to the allowed transit modes + geographic boundaries (via osmnx).
3. Interactive folium maps of the current possibility set.
4. **Landmark Audit** section (first-class, user-auditable) — because Tentacles / Measuring / Radar / Matching questions live or die by good POI anchors. You can visually inspect and easily add new landmarks.
5. Question proposers (lat/lon splits, radius-from-landmark, attribute) that compute real information gain / balance on the live candidate list.
6. Manual simulation of question sequences with instant re-mapping.

All data is cached under `data/` after the first run.

## Key Reference Links (used inside the notebook)

- Game rules & question types: https://www.lifack.ch/
- Excellent community map + simulator: https://taibeled.github.io/JetLagHideAndSeek/
- More question generators (see the "places" lists): https://jetlag.neocities.org/

## Next Steps / Extensions

See the notebook itself and the implementation plan in the session log for planned follow-ups (beam search for short strategies, decision-tree export, etc.).

## Attractions & POIs Standing Database (Seattle only)

A separate, self-contained notebook + module for parks, museums, zoos, libraries, diplomatic sites, and the other 10 "nearest X" landmark categories used by the game (exactly as implemented in https://github.com/taibeled/JetLagHideAndSeek).

- `notebooks/seattle_attractions.ipynb` — interactive checkboxes (one per category), live ipyleaflet map, final clean folium visualization.
- Standing database: `data/seattle_attractions.geojson` (+ tiny `.meta.json`). This is the permanent reference file you can point me (Grok) at directly in this chat for any questions about Seattle parks, museums, zoos, etc. Optional DuckDB only if you want it for your own SQL use.
- Same 4-city scope as the strategy work.
- **No transit data included** — pure non-transit attractions/landmarks only.
- One-time fetch from Overpass (modeled directly on the reference TS code); afterwards everything loads instantly from disk.

Usage (inside the attractions notebook or any future notebook):

```python
from jetlag.attractions import load_or_fetch_attractions, CATEGORY_COLORS
attractions = load_or_fetch_attractions()   # first run does the Overpass pull + saves the GeoJSON
attractions[attractions.category == "Parks"].head()
```

The GeoJSON is the canonical standing artifact. In this Grok chat you can just tell me to look at it and ask anything (e.g. "from the attractions database, list parks that would make good Radar/Tentacle questions"). No extra tools or setup needed.

---
*Generated from the approved implementation plan.*
