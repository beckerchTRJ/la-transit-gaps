"""
07_corridor_profiles.py
=======================
Define 5 major LA transit corridors and extract density + transit mode profiles.

Corridors:
  1. Wilshire Blvd (downtown to Santa Monica — bus + rail)
  2. Vermont Ave (Hollywood to Watts — bus only, very dense)
  3. Figueroa St (Highland Park to San Pedro — bus only)
  4. Crenshaw Blvd (Exposition Park to LAX — new rail + bus)
  5. Sepulveda Blvd (Van Nuys to LAX — bus only, planned rail)

For each corridor: buffer at 800m, sample density at regular intervals,
identify transit modes available.

Outputs:
  - Data/corridor_profiles.json
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"

BLOCKS_PATH = DATA_DIR / "la_blocks_density.geojson"
STOPS_PATH = DATA_DIR / "transit_stops.geojson"
ROUTES_PATH = DATA_DIR / "transit_routes.geojson"

for p in [BLOCKS_PATH, STOPS_PATH, ROUTES_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}")

# --- Corridor definitions (lat/lng waypoints) ---
CORRIDORS = {
    "Wilshire Blvd": {
        "waypoints": [
            (-118.2553, 34.0558),  # Downtown (Grand Park)
            (-118.3015, 34.0624),  # Koreatown
            (-118.3437, 34.0626),  # Miracle Mile
            (-118.3762, 34.0583),  # Beverly Hills adj
            (-118.4514, 34.0395),  # Westwood
            (-118.4946, 34.0195),  # Santa Monica
        ],
        "description": "Downtown to Santa Monica via Koreatown and Miracle Mile",
    },
    "Vermont Ave": {
        "waypoints": [
            (-118.2919, 34.1016),  # Los Feliz
            (-118.2917, 34.0762),  # Hollywood
            (-118.2913, 34.0524),  # Koreatown
            (-118.2910, 34.0226),  # USC/Exposition Park
            (-118.2820, 33.9589),  # Watts
        ],
        "description": "Los Feliz to Watts — one of LA's densest bus-only corridors",
    },
    "Figueroa St": {
        "waypoints": [
            (-118.1903, 34.1109),  # Highland Park
            (-118.2507, 34.0536),  # Downtown
            (-118.2748, 34.0171),  # USC
            (-118.2820, 33.9380),  # South LA
            (-118.2788, 33.7628),  # San Pedro
        ],
        "description": "Highland Park to San Pedro through downtown and South LA",
    },
    "Crenshaw Blvd": {
        "waypoints": [
            (-118.3281, 34.0240),  # Exposition Park
            (-118.3330, 34.0026),  # Leimert Park
            (-118.3353, 33.9610),  # Inglewood
            (-118.3400, 33.9330),  # Hawthorne
            (-118.3590, 33.9205),  # near LAX
        ],
        "description": "Exposition Park to LAX area — new Crenshaw/LAX rail line",
    },
    "Sepulveda Blvd": {
        "waypoints": [
            (-118.4487, 34.1863),  # Van Nuys
            (-118.4523, 34.1567),  # Sherman Oaks (pass)
            (-118.4687, 34.0783),  # Westwood
            (-118.3985, 33.9530),  # near LAX
        ],
        "description": "San Fernando Valley to LAX — future Sepulveda Transit Corridor",
    },
}

BUFFER_M = 800  # meters
SAMPLE_INTERVAL_M = 200  # sample density every 200m along corridor

print("Loading data...")
blocks = gpd.read_file(BLOCKS_PATH).to_crs("EPSG:3310")
stops = gpd.read_file(STOPS_PATH).to_crs("EPSG:3310")
routes = gpd.read_file(ROUTES_PATH).to_crs("EPSG:3310")

# Prepare spatial indices
from shapely.strtree import STRtree

bus_stops = stops[stops["route_category"].isin(["metro_bus", "local_bus"])]
rail_stops = stops[stops["route_category"].isin(["metro_rail", "commuter_rail"])]
bus_tree = STRtree(bus_stops.geometry.values)
rail_tree = STRtree(rail_stops.geometry.values)

# Block density lookup via spatial index
block_tree = STRtree(blocks.geometry.values)
block_densities = blocks["density"].values
block_pops = blocks["population"].values

results = {}

for name, config in CORRIDORS.items():
    print(f"\nProcessing corridor: {name}")

    # Build LineString from waypoints (convert to EPSG:3310)
    waypoint_gdf = gpd.GeoDataFrame(
        geometry=[Point(lng, lat) for lng, lat in config["waypoints"]],
        crs="EPSG:4326",
    ).to_crs("EPSG:3310")
    corridor_line = LineString(waypoint_gdf.geometry.tolist())
    corridor_length_m = corridor_line.length
    corridor_length_mi = corridor_length_m * 0.000621371

    print(f"  Length: {corridor_length_mi:.1f} mi ({corridor_length_m:.0f} m)")

    # Sample points along the corridor
    distances = np.arange(0, corridor_length_m, SAMPLE_INTERVAL_M)
    sample_points = [corridor_line.interpolate(d) for d in distances]

    # For each sample point: compute local density and transit mode
    profile = []
    for i, pt in enumerate(sample_points):
        dist_mi = distances[i] * 0.000621371

        # Density: average of blocks within buffer
        circle = pt.buffer(BUFFER_M)
        block_idxs = block_tree.query(circle, predicate="intersects")
        if len(block_idxs) > 0:
            # Area-weighted average density
            local_density = float(np.mean(block_densities[block_idxs]))
            local_pop = float(np.sum(block_pops[block_idxs]))
        else:
            local_density = 0
            local_pop = 0

        # Transit mode within buffer
        bus_circle = pt.buffer(402)  # ¼ mile
        rail_circle = pt.buffer(805)  # ½ mile
        has_bus = len(bus_tree.query(bus_circle, predicate="intersects")) > 0
        has_rail = len(rail_tree.query(rail_circle, predicate="intersects")) > 0

        if has_bus and has_rail:
            mode = "bus+rail"
        elif has_bus:
            mode = "bus"
        elif has_rail:
            mode = "rail"
        else:
            mode = "none"

        profile.append({
            "distance_mi": round(dist_mi, 2),
            "density_per_mi2": round(local_density * 0.386102, 0),  # convert from km² to mi²
            "population": round(local_pop, 0),
            "mode": mode,
            "lat": round(gpd.GeoDataFrame(geometry=[pt], crs="EPSG:3310").to_crs("EPSG:4326").geometry[0].y, 5),
            "lng": round(gpd.GeoDataFrame(geometry=[pt], crs="EPSG:3310").to_crs("EPSG:4326").geometry[0].x, 5),
        })

    # Corridor line in 4326 for mapping
    corridor_4326 = gpd.GeoDataFrame(
        geometry=[corridor_line], crs="EPSG:3310"
    ).to_crs("EPSG:4326").geometry[0]

    results[name] = {
        "description": config["description"],
        "length_mi": round(corridor_length_mi, 1),
        "coordinates": list(corridor_4326.coords),
        "profile": profile,
    }

    # Summary
    modes = [p["mode"] for p in profile]
    for m in ["bus+rail", "bus", "rail", "none"]:
        pct = round(100 * modes.count(m) / len(modes), 1)
        if pct > 0:
            print(f"    {m}: {pct}%")

# --- Save ---
print("\nSaving corridor_profiles.json...")
with open(DATA_DIR / "corridor_profiles.json", "w") as f:
    json.dump(results, f, indent=2)
print("Done.")
