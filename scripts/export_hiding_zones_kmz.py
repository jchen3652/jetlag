#!/usr/bin/env python3
"""Export official hiding-zone circles as KMZ for Google Earth.

Default: Medium/Small rule = ¼ mile radius around each transit stop.
Also writes a Large (½ mile) folder optionally.

Usage:
  .venv/bin/python scripts/export_hiding_zones_kmz.py
  .venv/bin/python scripts/export_hiding_zones_kmz.py --both-sizes
"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
STOPS = DATA / "transit_stops.geojson"
SCORES = DATA / "zone_hideable_scores.json"
OUT_DIR = ROOT / "data"

METERS_PER_MILE = 1609.344
# Official lifack zone radii
ZONE_M = {
    "medium": 0.25 * METERS_PER_MILE,  # small & medium games
    "large": 0.5 * METERS_PER_MILE,
}

# KML color = aabbggrr
MODE_COLORS = {
    "Link": "ffee8800",
    "RapidRide": "ff00aaff",
    "Monorail": "ff44cc44",
}


def circle_ring(lat: float, lng: float, radius_m: float, n: int = 64):
    """Return outer boundary coords as list of (lng, lat) closed ring."""
    # local meters
    m_lat = 111320.0
    m_lng = 111320.0 * math.cos(math.radians(lat))
    pts = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        dN = radius_m * math.cos(ang)
        dE = radius_m * math.sin(ang)
        pts.append((lng + dE / m_lng, lat + dN / m_lat))
    pts.append(pts[0])
    return pts


def load_scores():
    if not SCORES.exists():
        return {}
    data = json.loads(SCORES.read_text())
    idx = {}
    for s in data.get("stops", []):
        key = (round(s["lat"], 5), round(s["lng"], 5))
        idx[key] = s
        idx[(s["stop_name"], s.get("mode", ""))] = s
    return idx


def find_score(scores, name, mode, lat, lng):
    s = scores.get((round(lat, 5), round(lng, 5)))
    if s:
        return s
    return scores.get((name, mode))


def kml_document(stops_features, scores, sizes: list[str], circle_pts: int) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        "<name>Jet Lag Seattle — Hiding Zones</name>",
        "<description>Official hiding-zone circles centered on transit stops. "
        "Medium/Small = ¼ mi; Large = ½ mi. Source: lifack rules.</description>",
    ]

    # Styles: light outline + very transparent fill so 3D terrain doesn't look solid/warped.
    # PolyStyle fill color aaBBGGRR with low alpha.
    for mode, color in MODE_COLORS.items():
        fill = "22" + color[2:]  # ~13% opacity fill
        parts.append(
            f"""
  <Style id="zone_{mode}">
    <LineStyle><color>{color}</color><width>2.5</width></LineStyle>
    <PolyStyle>
      <color>{fill}</color>
      <fill>1</fill>
      <outline>1</outline>
    </PolyStyle>
  </Style>"""
        )
    parts.append(
        """
  <Style id="zone_Other">
    <LineStyle><color>ff888888</color><width>2.5</width></LineStyle>
    <PolyStyle><color>22888888</color><fill>1</fill><outline>1</outline></PolyStyle>
  </Style>
  <Style id="center_Link">
    <IconStyle>
      <color>ffee8800</color><scale>0.85</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      <hotSpot x="0.5" y="0.5" xunits="fraction" yunits="fraction"/>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>
  <Style id="center_RapidRide">
    <IconStyle>
      <color>ff00aaff</color><scale>0.85</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      <hotSpot x="0.5" y="0.5" xunits="fraction" yunits="fraction"/>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>
  <Style id="center_Monorail">
    <IconStyle>
      <color>ff44cc44</color><scale>0.85</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      <hotSpot x="0.5" y="0.5" xunits="fraction" yunits="fraction"/>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>
  <Style id="center_Other">
    <IconStyle>
      <scale>0.85</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      <hotSpot x="0.5" y="0.5" xunits="fraction" yunits="fraction"/>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>"""
    )

    # group by mode once
    by_mode = {}
    for f in stops_features:
        mode = f["properties"].get("mode") or "Other"
        by_mode.setdefault(mode, []).append(f)

    # ----- Zone circles only (no centers mixed in) -----
    for size in sizes:
        radius = ZONE_M[size]
        zkey = "large" if size == "large" else "small_medium"
        mi = radius / METERS_PER_MILE
        parts.append(f'<Folder><name>Hiding zones — {size} ({mi:g} mi)</name>')

        for mode in sorted(by_mode.keys()):
            parts.append(f"<Folder><name>{escape(mode)}</name>")
            for f in sorted(by_mode[mode], key=lambda x: x["properties"].get("stop_name") or ""):
                p = f["properties"]
                name = p.get("stop_name") or "Unnamed"
                route = p.get("route") or ""
                lng, lat = f["geometry"]["coordinates"][:2]
                sc = find_score(scores, name, mode, lat, lng)
                frac = None
                if sc and zkey in sc.get("zones", {}):
                    frac = sc["zones"][zkey].get("practical", {}).get("hideable_frac")

                label = name
                if frac is not None:
                    label = f"{name} ({frac*100:.1f}% hideable)"

                desc_lines = [
                    f"Station: {name}",
                    f"Mode: {mode}",
                    f"Route: {route}",
                    f"Zone radius: {mi:g} mi ({radius:.1f} m)",
                    f"Center: {lat:.6f}, {lng:.6f}",
                ]
                if frac is not None:
                    desc_lines.append(f"Hideable fraction (practical): {frac*100:.1f}%")
                    area = sc["zones"][zkey]["practical"].get("hideable_area_m2")
                    if area is not None:
                        desc_lines.append(f"≈ hideable area: {area/1e4:.2f} ha")
                desc = escape("\n".join(desc_lines))

                ring = circle_ring(lat, lng, radius, n=circle_pts)
                # lon,lat only (no altitude) + clampToGround → drapes on terrain, less 3D weirdness
                coord_str = " ".join(f"{x:.7f},{y:.7f}" for x, y in ring)
                style = f"zone_{mode}" if mode in MODE_COLORS else "zone_Other"

                parts.append(
                    f"""
    <Placemark>
      <name>{escape(label)}</name>
      <description>{desc}</description>
      <styleUrl>#{style}</styleUrl>
      <Polygon>
        <extrude>0</extrude>
        <tessellate>1</tessellate>
        <altitudeMode>clampToGround</altitudeMode>
        <outerBoundaryIs><LinearRing>
          <coordinates>{coord_str}</coordinates>
        </LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>"""
                )

            parts.append("</Folder>")
        parts.append("</Folder>")

    # ----- Station centers as a completely separate top-level folder -----
    # Use medium hideable % for labels when available
    zkey_label = "small_medium"
    parts.append('<Folder><name>Station centers</name>')
    parts.append(
        "<description>Transit stop points only (zone centers). Toggle separately from zone circles.</description>"
    )
    for mode in sorted(by_mode.keys()):
        parts.append(f"<Folder><name>{escape(mode)}</name>")
        for f in sorted(by_mode[mode], key=lambda x: x["properties"].get("stop_name") or ""):
            p = f["properties"]
            name = p.get("stop_name") or "Unnamed"
            route = p.get("route") or ""
            lng, lat = f["geometry"]["coordinates"][:2]
            sc = find_score(scores, name, mode, lat, lng)
            frac = None
            if sc and zkey_label in sc.get("zones", {}):
                frac = sc["zones"][zkey_label].get("practical", {}).get("hideable_frac")

            label = name
            if frac is not None:
                label = f"{name} ({frac*100:.1f}%)"

            desc_lines = [
                f"Station: {name}",
                f"Mode: {mode}",
                f"Route: {route}",
                f"Lat/Lng: {lat:.6f}, {lng:.6f}",
            ]
            if frac is not None:
                desc_lines.append(f"Hideable fraction (¼ mi, practical): {frac*100:.1f}%")
            desc = escape("\n".join(desc_lines))
            cstyle = f"center_{mode}" if mode in MODE_COLORS else "center_Other"

            parts.append(
                f"""
    <Placemark>
      <name>{escape(label)}</name>
      <description>{desc}</description>
      <styleUrl>#{cstyle}</styleUrl>
      <Point>
        <extrude>0</extrude>
        <altitudeMode>clampToGround</altitudeMode>
        <coordinates>{lng:.7f},{lat:.7f}</coordinates>
      </Point>
    </Placemark>"""
            )
        parts.append("</Folder>")
    parts.append("</Folder>")

    parts.append("</Document></kml>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--both-sizes",
        action="store_true",
        help="Include both ¼ mi (medium) and ½ mi (large) folders",
    )
    ap.add_argument(
        "--large-only",
        action="store_true",
        help="Only ½ mi large-game zones",
    )
    ap.add_argument("--circle-points", type=int, default=72, help="Polygon sides per circle")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=OUT_DIR / "seattle_hiding_zones.kmz",
    )
    args = ap.parse_args()

    if args.large_only:
        sizes = ["large"]
    elif args.both_sizes:
        sizes = ["medium", "large"]
    else:
        sizes = ["medium"]

    stops = json.loads(STOPS.read_text())
    features = stops["features"]
    scores = load_scores()

    kml = kml_document(features, scores, sizes, args.circle_points)

    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    # write kmz = zip with doc.kml
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)

    # also plain kml next to it
    kml_path = out.with_suffix(".kml")
    kml_path.write_text(kml)

    print(f"Wrote {out} ({out.stat().st_size/1e6:.2f} MB)")
    print(f"Wrote {kml_path} ({kml_path.stat().st_size/1e6:.2f} MB)")
    print(f"  stops={len(features)} sizes={sizes} scores={'yes' if scores else 'no'}")


if __name__ == "__main__":
    main()
