"""
08_counterfactual.py
====================
Three-tier rail coverage analysis:
  1. Current rail coverage
  2. D Line extension (Sections 1-3, opening 2024-2027) — how much it adds
  3. Greedy set-cover hypothetical stations on remaining gaps

Outputs:
  - Data/counterfactual_stations.geojson  (hypothetical + D Line stations)
  - Data/counterfactual_stats.json        (three-tier coverage statistics)
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"

DESERTS_PATH = DATA_DIR / "hex_transit_deserts.geojson"
STOPS_PATH = DATA_DIR / "transit_stops.geojson"

for p in [DESERTS_PATH, STOPS_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}")

ONE_KM_M = 1000
N_STATIONS = 20
DENSITY_THRESHOLD = 5000

# ---------------------------------------------------------------------------
# D Line extension stations (not yet in GTFS data)
# ---------------------------------------------------------------------------
# Section 1 opened 2024 but missing from GTFS — add to current baseline
D_LINE_SECTION_1 = [
    {"name": "Wilshire/La Brea",      "lat": 34.0621, "lng": -118.3437},
    {"name": "Wilshire/Fairfax",      "lat": 34.0622, "lng": -118.3614},
    {"name": "Wilshire/La Cienega",   "lat": 34.0624, "lng": -118.3766},
]

# Sections 2-3 under construction — shown as planned expansion
D_LINE_PLANNED = [
    # Section 2 (opening ~2025)
    {"name": "Wilshire/Rodeo",        "lat": 34.0607, "lng": -118.3997, "section": 2},
    {"name": "Century City/Constellation", "lat": 34.0553, "lng": -118.4167, "section": 2},
    # Section 3 (opening ~2027)
    {"name": "Westwood/UCLA",         "lat": 34.0630, "lng": -118.4440, "section": 3},
    {"name": "Westwood/VA Hospital",  "lat": 34.0502, "lng": -118.4522, "section": 3},
]

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading data...")
hexes = gpd.read_file(DESERTS_PATH).to_crs("EPSG:3310")
stops = gpd.read_file(STOPS_PATH).to_crs("EPSG:3310")

rail_stops = stops[stops["route_category"].isin(["metro_rail", "commuter_rail"])].copy()
print(f"  {len(hexes)} populated hexes, {len(rail_stops)} existing rail stations")

# Add D Line Section 1 to the existing rail baseline (opened 2024, missing from GTFS)
s1_points = [Point(s["lng"], s["lat"]) for s in D_LINE_SECTION_1]
s1_gdf = gpd.GeoDataFrame(geometry=s1_points, crs="EPSG:4326").to_crs("EPSG:3310")
print(f"  Adding {len(s1_gdf)} D Line Section 1 stations to baseline (opened 2024)")

# Combine existing rail + Section 1 for baseline
all_current_rail = list(rail_stops.geometry.values) + list(s1_gdf.geometry.values)

# ---------------------------------------------------------------------------
# Current rail coverage (including Section 1)
# ---------------------------------------------------------------------------
print("\nStep 1: Current rail coverage (1 km)...")
hex_centroids = hexes.geometry.centroid
hex_coords_3310 = np.array([(c.x, c.y) for c in hex_centroids])
rail_tree = STRtree(all_current_rail)

has_rail_current = []
for centroid in hex_centroids:
    circle = centroid.buffer(ONE_KM_M)
    has_rail_current.append(len(rail_tree.query(circle, predicate="intersects")) > 0)

hexes["has_rail_current"] = has_rail_current
current_rail_pop = int(hexes[hexes["has_rail_current"]]["population"].sum())
total_pop = int(hexes["population"].sum())
print(f"  Current: {current_rail_pop:,} ({100*current_rail_pop/total_pop:.1f}%)")

# ---------------------------------------------------------------------------
# D Line extension coverage
# ---------------------------------------------------------------------------
print(f"\nStep 2: D Line Sections 2-3 ({len(D_LINE_PLANNED)} stations)...")
d_line_points_4326 = [Point(s["lng"], s["lat"]) for s in D_LINE_PLANNED]
d_line_gdf = gpd.GeoDataFrame(D_LINE_PLANNED, geometry=d_line_points_4326, crs="EPSG:4326")
d_line_3310 = d_line_gdf.to_crs("EPSG:3310")

# Find hexes newly covered by D Line (not already covered by current rail)
has_rail_with_dline = list(has_rail_current)  # copy
for station_geom in d_line_3310.geometry:
    for i, centroid in enumerate(hex_centroids):
        if not has_rail_with_dline[i]:
            if centroid.distance(station_geom) <= ONE_KM_M:
                has_rail_with_dline[i] = True

hexes["has_rail_with_dline"] = has_rail_with_dline
dline_rail_pop = int(hexes[hexes["has_rail_with_dline"]]["population"].sum())
dline_additional = dline_rail_pop - current_rail_pop
print(f"  D Line adds: {dline_additional:,} residents")
print(f"  With D Line: {dline_rail_pop:,} ({100*dline_rail_pop/total_pop:.1f}%)")

for s in D_LINE_PLANNED:
    print(f"    Section {s['section']}: {s['name']}")

# ---------------------------------------------------------------------------
# Greedy set-cover on remaining gaps (after D Line)
# ---------------------------------------------------------------------------
print(f"\nStep 3: Greedy set-cover for {N_STATIONS} hypothetical stations (post-D Line)...")

no_rail = hexes[~hexes["has_rail_with_dline"]].copy()
print(f"  {len(no_rail)} hexes still without rail")

dense_no_rail = no_rail[no_rail["density_mi2"] >= DENSITY_THRESHOLD].copy()
print(f"  {len(dense_no_rail)} dense hexes (>={DENSITY_THRESHOLD}/mi²) without rail")

candidates = no_rail.copy()
candidates["centroid"] = candidates.geometry.centroid
candidate_pops = candidates["population"].values.copy()
candidate_coords = np.array([(c.x, c.y) for c in candidates["centroid"].values])

placement_candidates = dense_no_rail.copy()
placement_candidates["centroid"] = placement_candidates.geometry.centroid

stations = []
total_new_coverage = 0
covered_mask = np.zeros(len(candidates), dtype=bool)

for i in range(N_STATIONS):
    best_pop = 0
    best_idx = -1
    best_covered = None

    for j, centroid in enumerate(placement_candidates["centroid"].values):
        dists = np.sqrt((candidate_coords[:, 0] - centroid.x) ** 2 +
                        (candidate_coords[:, 1] - centroid.y) ** 2)
        within = (dists <= ONE_KM_M) & (~covered_mask)
        pop_covered = candidate_pops[within].sum()

        if pop_covered > best_pop:
            best_pop = pop_covered
            best_idx = j
            best_covered = within

    if best_idx < 0 or best_pop == 0:
        print(f"  No more beneficial station locations after {i} stations.")
        break

    covered_mask |= best_covered
    total_new_coverage += best_pop

    station_centroid = placement_candidates.iloc[best_idx]["centroid"]
    station_4326 = gpd.GeoDataFrame(
        geometry=[station_centroid], crs="EPSG:3310"
    ).to_crs("EPSG:4326").geometry[0]

    stations.append({
        "station_number": i + 1,
        "station_type": "hypothetical",
        "population_covered": int(best_pop),
        "cumulative_coverage": int(total_new_coverage),
        "geometry": Point(station_4326.x, station_4326.y),
        "lat": round(station_4326.y, 5),
        "lng": round(station_4326.x, 5),
    })

    print(f"  Station {i+1}: covers {best_pop:,} people "
          f"(cumulative: {total_new_coverage:,})")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
final_pop = dline_rail_pop + total_new_coverage

stats = {
    "total_population_in_populated_hexes": total_pop,
    "current_rail_1km_population": current_rail_pop,
    "current_rail_1km_percent": round(100 * current_rail_pop / total_pop, 1),
    "dline_additional_population": dline_additional,
    "dline_total_population": dline_rail_pop,
    "dline_total_percent": round(100 * dline_rail_pop / total_pop, 1),
    "dline_n_stations": len(D_LINE_PLANNED),
    "hypothetical_additional_population": int(total_new_coverage),
    "final_total_population": int(final_pop),
    "final_total_percent": round(100 * final_pop / total_pop, 1),
    "n_hypothetical_stations": len(stations),
}

print(f"\nSummary:")
print(f"  Current rail: {stats['current_rail_1km_percent']}%")
print(f"  + D Line Sections 2-3 ({len(D_LINE_PLANNED)} stations): {stats['dline_total_percent']}% "
      f"(+{dline_additional:,} residents)")
print(f"  + {len(stations)} hypothetical: {stats['final_total_percent']}% "
      f"(+{total_new_coverage:,} residents)")

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
print("\nSaving outputs...")

# Combine D Line and hypothetical stations into one GeoDataFrame
d_line_output = []
for s in D_LINE_PLANNED:
    d_line_output.append({
        "station_number": 0,
        "station_type": f"d_line_section_{s['section']}",
        "name": s["name"],
        "population_covered": 0,
        "cumulative_coverage": 0,
        "geometry": Point(s["lng"], s["lat"]),
        "lat": s["lat"],
        "lng": s["lng"],
    })

all_stations = d_line_output + stations
stations_gdf = gpd.GeoDataFrame(all_stations, crs="EPSG:4326")
stations_gdf.to_file(DATA_DIR / "counterfactual_stations.geojson", driver="GeoJSON")

with open(DATA_DIR / "counterfactual_stats.json", "w") as f:
    json.dump(stats, f, indent=2)

print("Done.")
