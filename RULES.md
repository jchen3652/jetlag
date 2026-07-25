# Jet Lag: Hide and Seek — Distilled Rules

Source: [lifack.ch Quick Start Guide](https://www.lifack.ch/docs/quick_start_guide/) and linked rulebook pages (Hide and Seek / Jet Lag The Game community rulebook).

This distill is for **planning Seattle hiding zones and final spots**. It is not a full substitute for the official rulebook.

---

## 1. Win condition & structure

1. One player **hides** using **public transit** to reach a **hiding zone** centered on a map station.
2. Other players **seek** by asking questions from six categories.
3. After each answered question, the hider draws from the **hider deck**.
4. When the hider is found, roles rotate.
5. **Longest single hide wins** (best round if multiple rounds; times are not summed).

Default: each player/team hides **once**. Optional extra rounds only if the group commits more time.

---

## 2. Game size (drives radii & timers)

| Size   | Map scale                         | Typical duration | Ideal stations / area        |
|--------|-----------------------------------|------------------|------------------------------|
| Small  | Town / part of a large city       | 4–8 hours        | 30–100 stations; 10–100 mi²  |
| Medium | Major city / metro                | ~1 day           | 100–500 stations; 100–1,000 mi² |
| Large  | Region / country / multi-country | 2–4 days         | 500+ stations; 1,000+ mi²    |

**Seattle (Link + Monorail + RapidRide in city + Bellevue/Redmond scope)** fits **Medium** by default (city/metro, ~1 day). Switch to Large only if you expand far beyond that scope.

### Official distance constants (the ones that were wrong on freeform tools)

| Concept | Small | Medium | Large |
|---------|-------|--------|-------|
| **Hiding zone radius** (from station map icon) | **¼ mile** | **¼ mile** | **½ mile** |
| Hiding period (travel time at round start) | 30 min | 60 min | 180 min |
| Photo answer window | 10 min | 10 min | 20 min |
| Non-photo answer window | 5 min | 5 min | 5 min |

Conversion used in this project:

- 1 mile = **1609.344 m**
- ¼ mile = **402.336 m**
- ½ mile = **804.672 m**
- 10 feet ≈ **3.048 m** (final spot path rule)
- 5 feet ≈ **1.524 m** (caught rule)

---

## 3. Map setup (Seattle-relevant)

- **Transit is the backbone.** Define which systems count (here: Link, Monorail, RapidRide).
- Draw **hard map borders** all players share (My Maps polygon / square / circle ok).
- Only stations **inside the borders** are legal zone centers.
- Exclude unsafe areas by group agreement before play.
- **Google Maps recommended** for questions/measure; use the **same app** on both sides for category icons.
- **No Google Street View** for research.

POI legitimacy (Google Maps): ≥5 reviews → assume real; &lt;5 → assume not; group can override. Apple Maps: assume real unless group agrees otherwise.

---

## 4. Round flow

### Start

- Hide order set randomly beforehand.
- Hider gets **hider deck**; seekers get **investigation book** + trackers on.
- Both sides: dice, rulebook optional, printed map optional.
- Start location: anywhere in map (Seattle project often assumes near **Seattle Art Museum**).

### Hiding period

- Hider may walk + use **allowed public transit** only.
- Must end at a **legal transit station** → that station becomes the **center of the hiding zone**.
- If time expires elsewhere, **that** location/station is the zone (per rules: wherever you are when the period ends).

### After hiding period

- Hider must remain **inside the zone circle** for the rest of the round (until end game freezes them).
- Seekers ask questions; hider answers + draws cards.

### End game

- Starts when seekers **enter the hiding zone** and are **off transit**.
- Hider must **stop moving** and stay in a legal **final hiding spot**.
- Some photo questions may become unanswerable → “I cannot answer” still counts; hider still draws.

### Caught

- Found when seekers are **within 5 feet** **and** have **spotted** them.
- Clock stops; **time bonus cards still in hand** add to total.
- Next hider: up to **10 minutes** prep; next round starts from last hiding spot.

---

## 5. Hiding zones (critical for strategy)

- Zone is a **circle** around **one chosen transit station icon**.
- Radius: **¼ mi (S/M)** or **½ mi (L)**.
- Other stations may fall inside the circle; you still have **one** home station (photos/questions often reference it).
- Inside the zone (pre–end game): free to move, shop, eat, prep photos, scout a final spot.
- **Choosing the zone is the highest-impact hide decision.**

Tradeoffs called out by the rulebook:

| Edge / sparse network | Dense core |
|-----------------------|------------|
| Harder to identify early; longer transit for seekers | Complexity + many candidate stations |
| Once narrowed, easier to pinpoint exact station | Easier seeker transit; **tentacle** risk higher |

Practical zone checklist (from general tips + zone rules):

- Bathroom access somewhere in zone
- Places you can stay without being kicked out
- Photo subjects available (station exterior, streets, trees, parks, etc.)
- For multi-day: lodging considerations near zone

---

## 6. Final hiding spots (end game)

Must be:

1. **Inside** the hiding zone  
2. **Publicly accessible** during all game hours (excluding rest periods) — not private homes, not bathroom stalls; seekers must be able to reach it  
3. **Within 10 feet of a marked path/road** on the shared map app (walking directions test)  
4. Sustainable for a long stay without raising suspicion → **avoid stores/businesses** even if open  

Final spot locks the moment end game starts. If not public-accessible then, go to nearest legal public spot immediately.

A clever final spot can buy **an hour+** after seekers know the station.

---

## 7. Questions (six categories)

Rules shared by all:

- One question at a time; wait for answer.
- Truthful answers within time window.
- Replay costs **double / triple / …** (separate draw sequences each time).
- Locations outside map borders **do not exist** for matching/measuring → null still costs cards.
- Seekers clarify ambiguity (screenshots of what counts).

| Category | Format | Draw (typical) | Notes |
|----------|--------|----------------|-------|
| **Radar** | “Are you within ____ of me?” yes/no | Draw 2 keep 1 | About **current location**, not the whole zone |
| **Thermometer** | After traveling ____, hotter/colder? | Draw 2 keep 1 | Crow-flies closer = hotter |
| **Measuring** | Closer/further than me from ____? | Draw 3 keep 1 | Measure to map **icons** for POIs |
| **Matching** | Same nearest ____ as me? | Draw 3 keep 1 | Same; transit line match has special on-vehicle rules |
| **Tentacles** | Within R mi, which X nearest? (must be within R) | Draw 4 keep 2 | **Not in Small** |
| **Photos** | Send photo of ____ | Draw 1 keep 1 | No Street View for seekers |

### Radar distances (official list)

`¼ mi · ½ mi · 1 · 3 · 5 · 10 · 25 · 50 · 100 · Choose (any)`

### Thermometer travel distances

- Small: `½ mi · 3 mi`
- Medium: + `10 mi`
- Large: + `50 mi`

### Tentacles

- **Small:** none  
- **Medium (reach 1 mile):** Museums · Libraries · Movie theaters · Hospitals  
- **Large add (reach 15 miles):** Metro lines · Zoos · Aquariums · Amusement parks  

### Measuring / Matching POI anchors (icons)

Commercial airport, high-speed rail (measuring), rail station (measuring), borders, sea level, body of water, coastline (special definition), mountain, park, amusement park, zoo, aquarium, golf course (outdoor full course only), museum, movie theater, hospital, library, foreign consulate (no honorary).

Matching also: transit line (seekers must be **on moving transit**; yes only if that vehicle **stops** at hider’s station), station name length, street/path, admin divisions 1–4, landmass.

### Photos (high-level)

- Small set: building from station, widest street, tree, tallest in sightline, selfie, sky  
- Medium/Large add: tallest from station, trace nearest street, 2 buildings, restaurant interior (through window), park, grocery aisle, place of worship, train platform  
- Large add: ½ mile continuous street trace (5 turns), tallest mountain from station, biggest body of water in zone, 5 buildings  

---

## 8. Hider deck (strategy relevance)

- Hand size **6** (expandable by powerup).
- Types: **Time bonuses** (score if still held when caught), **Powerups**, **Curses**.
- Notable powerup **Move**: new hiding period to a **new station**; timer paused; seekers freeze; **discard entire hand** and **reveal original station**; cannot use in end game.
- Curses slow seekers; casting costs vary; only one active “block questions/transit” curse at a time.

---

## 9. Implications for “best hiding places” in Seattle

A strong hide is **not** only “far away.” Score candidates by:

1. **Legal zone geometry** — correct ¼ mi (or ½ mi) circle around a **legal** station.  
2. **Final-spot quality inside the circle** — public, path-adjacent, stayable, not obvious.  
3. **Zone amenities** — bathroom, cover (parks), photo subjects, food without becoming a “store hide.”  
4. **Network ambiguity** — many plausible stations nearby delays exact ID; pure edges can be fragile late-game.  
5. **Tentacle risk (Medium)** — unique nearest museum/library/cinema/hospital within 1 mi of seekers’ eventual approach corridors.  
6. **Transit access for seekers** — Link-only vs RapidRide density changes how fast end game arrives.  
7. **Hiding-period reachability** — Medium: **60 minutes** from start via allowed modes only.

This repo’s **hiding map fork** encodes (1) and approximates (2)–(6) with per-station zone circles, radar presets, and a station scoreboard.

---

## 10. Quick radius cheat sheet

```
HIDING_ZONE_RADIUS_MI = 0.25   # small & medium
HIDING_ZONE_RADIUS_MI = 0.50   # large only

RADAR_MI = [0.25, 0.5, 1, 3, 5, 10, 25, 50, 100]
THERMO_MI_MEDIUM = [0.5, 3, 10]
TENTACLE_MI_MEDIUM = 1.0       # museums, libraries, cinemas, hospitals
PATH_RULE_FT = 10
CAUGHT_FT = 5
```

Do **not** treat a freeform “0.25 mi walkshed union of all stops” as a hiding zone. A hiding zone is **one circle around one station**.
