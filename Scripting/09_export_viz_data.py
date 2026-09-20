"""
09_export_viz_data.py
=====================
Export analysis outputs as optimized, web-ready files for D3.js consumption.

Key optimizations:
  - Hero map: Pre-render block density to a PNG image (Canvas-friendly, <500KB)
    instead of 5MB TopoJSON that chokes D3 SVG rendering
  - County boundary: Extract single main polygon (drop tiny islands)
  - Hex deserts: Convert to TopoJSON for arc-sharing (~60% smaller)
  - Coverage: Simplify in projected CRS then reproject (correct simplification)

Outputs to Website/data/:
  - hero_density.png          (pre-rendered density raster, ~400KB)
  - hero_extent.json          (lat/lng bounds for positioning the image)
  - county_boundary.geojson   (single main polygon, simplified)
  - coverage_bus.geojson      (properly simplified bus coverage)
  - coverage_rail.geojson     (properly simplified rail coverage)
  - hex_deserts.json          (flat array of hex centroids + props, no geometry)
  - hex_grid.topojson         (hex geometries as TopoJSON, small)
  - corridor_profiles.json    (pass-through)
  - counterfactual_stations.geojson (pass-through)
  - coverage_stats.json       (pass-through)
  - counterfactual_stats.json (pass-through)
  - block_bin_stats.json      (legend metadata)
"""

import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from shapely.ops import unary_union
from shapely.geometry import shape, mapping
from shapely.geometry.polygon import orient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
WEBSITE_DATA = PROJECT_ROOT / "Website" / "data"
WEBSITE_DATA.mkdir(parents=True, exist_ok=True)

KM2_TO_MI2 = 0.386102


def truncate_coords(geojson_dict, precision=4):
    """Truncate coordinates in a GeoJSON dict to N decimal places."""
    def _trunc(coords):
        if isinstance(coords[0], (list, tuple)):
            return [_trunc(c) for c in coords]
        return [round(c, precision) for c in coords]
    for feature in geojson_dict.get("features", []):
        geom = feature.get("geometry", {})
        if "coordinates" in geom:
            geom["coordinates"] = _trunc(geom["coordinates"])
    return geojson_dict


# =====================================================================
# 1. County boundary — extract main polygon only
# =====================================================================
print("1/8  Processing county boundary...")
BOUNDARY_PATH = DATA_DIR / "County_Boundary.geojson"
county_geojson = None
if BOUNDARY_PATH.exists():
    boundary = gpd.read_file(BOUNDARY_PATH)
    # Keep only the largest polygon (the mainland county)
    boundary["_area"] = boundary.to_crs("EPSG:3310").geometry.area
    main_idx = boundary["_area"].idxmax()
    main_boundary = boundary.loc[[main_idx]].copy()
    main_boundary = main_boundary.drop(columns=["_area"])
    # Simplify gently
    main_boundary.geometry = main_boundary.geometry.simplify(0.001, preserve_topology=True)
    county_geojson = json.loads(main_boundary.to_json())
    county_geojson = truncate_coords(county_geojson, precision=4)
    out = WEBSITE_DATA / "county_boundary.geojson"
    with open(out, "w") as f:
        json.dump(county_geojson, f)
    print(f"     → {out.name} ({out.stat().st_size / 1e3:.0f} KB)")
else:
    print("     SKIP: County_Boundary.geojson not found")


# =====================================================================
# 2. Hero density — pre-render to PNG image
# =====================================================================
print("2/8  Rendering block density to PNG...")
BLOCKS_PATH = DATA_DIR / "la_blocks_density.geojson"
if BLOCKS_PATH.exists():
    blocks = gpd.read_file(BLOCKS_PATH)

    # Compute density in persons/mi²
    blocks["density_mi2"] = blocks["density"] * KM2_TO_MI2

    # Compute quantile bins for legend stats
    valid = blocks[blocks["density"] > 0]["density"]
    bin_edges_km2 = [0] + list(np.quantile(valid, [0.15, 0.3, 0.5, 0.65, 0.8, 0.92])) + [float("inf")]
    bin_stats = []
    for i in range(len(bin_edges_km2) - 1):
        lo = bin_edges_km2[i] * KM2_TO_MI2
        hi = bin_edges_km2[i + 1] * KM2_TO_MI2 if bin_edges_km2[i + 1] != float("inf") else None
        bin_stats.append({
            "bin": i,
            "min_density_mi2": round(lo),
            "max_density_mi2": round(hi) if hi else None,
        })
    with open(WEBSITE_DATA / "block_bin_stats.json", "w") as f:
        json.dump(bin_stats, f)

    # Use main county boundary for clipping extent
    if county_geojson:
        main_gdf = gpd.read_file(BOUNDARY_PATH)
        main_gdf["_area"] = main_gdf.to_crs("EPSG:3310").geometry.area
        main_poly = main_gdf.loc[main_gdf["_area"].idxmax()].geometry
        bounds = main_poly.bounds  # (minx, miny, maxx, maxy)
    else:
        bounds = blocks.total_bounds

    # Render with matplotlib — no axes, just geometry colored by density
    fig, ax = plt.subplots(1, 1, figsize=(12, 12), dpi=150)
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("#E8ECF0")
    ax.set_facecolor("#E8ECF0")

    # YlOrRd colormap
    ylor_colors = ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"]
    cmap = LinearSegmentedColormap.from_list("ylor", ylor_colors, N=256)

    # Clip density for color mapping
    vmin = float(np.quantile(blocks.loc[blocks["density"] > 0, "density"], 0.02))
    vmax = float(np.quantile(blocks.loc[blocks["density"] > 0, "density"], 0.98))

    blocks.plot(
        ax=ax,
        column="density",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        linewidth=0,
        edgecolor="none",
        missing_kwds={"color": "#E8ECF0"},
    )

    # Draw county outline
    if county_geojson:
        main_gdf.loc[[main_gdf["_area"].idxmax()]].boundary.plot(
            ax=ax, color="#999999", linewidth=0.5
        )

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0, hspace=0)
    hero_path = WEBSITE_DATA / "hero_density.png"
    fig.savefig(hero_path, dpi=150, bbox_inches="tight", pad_inches=0,
                facecolor="#E8ECF0", transparent=False)
    plt.close(fig)

    # Save the extent for D3 positioning
    extent = {
        "minLng": round(bounds[0], 4),
        "minLat": round(bounds[1], 4),
        "maxLng": round(bounds[2], 4),
        "maxLat": round(bounds[3], 4),
    }
    with open(WEBSITE_DATA / "hero_extent.json", "w") as f:
        json.dump(extent, f)

    size_kb = hero_path.stat().st_size / 1e3
    print(f"     → hero_density.png ({size_kb:.0f} KB)")
else:
    print("     SKIP: la_blocks_density.geojson not found")


# =====================================================================
# 3. Coverage polygons — simplify in projected CRS
# =====================================================================
print("3/8  Processing coverage polygons...")
for name, filename in [("bus", "coverage_quarter_mi_bus.geojson"),
                        ("rail", "coverage_half_mi_rail.geojson")]:
    src = DATA_DIR / filename
    if src.exists():
        gdf = gpd.read_file(src)
        # Simplify in projected CRS (meters) then reproject back
        gdf_proj = gdf.to_crs("EPSG:3310")
        tolerance = 200 if name == "bus" else 100  # meters
        gdf_proj.geometry = gdf_proj.geometry.simplify(tolerance, preserve_topology=True)
        # Buffer(0) to fix any topology issues from simplification
        gdf_proj.geometry = gdf_proj.geometry.buffer(0)
        gdf_out = gdf_proj.to_crs("EPSG:4326")
        # Fix winding order: D3 requires CCW exterior rings (RFC 7946)
        gdf_out.geometry = gdf_out.geometry.apply(lambda g: orient(g, sign=1.0))
        geojson = json.loads(gdf_out.to_json())
        geojson = truncate_coords(geojson, precision=4)
        out = WEBSITE_DATA / f"coverage_{name}.geojson"
        with open(out, "w") as f:
            json.dump(geojson, f)
        print(f"     → {out.name} ({out.stat().st_size / 1e3:.0f} KB)")
    else:
        print(f"     SKIP: {filename} not found")


# =====================================================================
# 4. Hex deserts — lightweight flat JSON + TopoJSON for geometry
# =====================================================================
print("4/8  Processing hex desert scores...")
DESERTS_PATH = DATA_DIR / "hex_transit_deserts.geojson"
if DESERTS_PATH.exists():
    hexes = gpd.read_file(DESERTS_PATH)

    # Compute has_rail_1km: same logic as script 08 baseline
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    STOPS_PATH = DATA_DIR / "transit_stops.geojson"
    _stops = gpd.read_file(STOPS_PATH).to_crs("EPSG:3310")
    _rail = _stops[_stops["route_category"].isin(["metro_rail", "commuter_rail"])]
    # Include D Line Section 1 (opened 2024, missing from GTFS)
    _s1 = gpd.GeoDataFrame(geometry=[
        Point(-118.3437, 34.0621), Point(-118.3614, 34.0622), Point(-118.3766, 34.0624),
    ], crs="EPSG:4326").to_crs("EPSG:3310")
    _all_rail = list(_rail.geometry.values) + list(_s1.geometry.values)
    _rail_tree = STRtree(_all_rail)
    _hex_3310 = hexes.to_crs("EPSG:3310")
    _has_rail_1km = []
    for c in _hex_3310.geometry.centroid:
        _has_rail_1km.append(len(_rail_tree.query(c.buffer(1000), predicate="intersects")) > 0)
    hexes["has_rail_1km"] = _has_rail_1km
    print(f"     Rail within 1km: {sum(_has_rail_1km)} of {len(hexes)} hexes")

    # Create a flat JSON array (properties only, with centroid coords) for fast lookup
    hex_props = []
    for _, row in hexes.iterrows():
        centroid = row.geometry.centroid
        hex_props.append({
            "id": row["hex_id"],
            "pop": int(row["population"]),
            "d": round(row["density_mi2"], 0),  # density
            "bs": int(row["bus_stops_quarter_mi"]),
            "rs": int(row["rail_stations_half_mi"]),
            "r1": 1 if row["has_rail_1km"] else 0,  # rail within 1km (matches counterfactual)
            "as": round(float(row["access_score"]), 2),
            "pr": round(float(row["pct_rank"]), 3) if not np.isnan(row.get("pct_rank", float("nan"))) else None,
            "def": round(row["deficit"], 2) if row["deficit"] is not None and not np.isnan(row["deficit"]) else None,
            "n": row.get("neighborhood", None) if isinstance(row.get("neighborhood"), str) else None,
            "cx": round(centroid.x, 4),
            "cy": round(centroid.y, 4),
        })

    with open(WEBSITE_DATA / "hex_props.json", "w") as f:
        json.dump(hex_props, f, separators=(",", ":"))
    print(f"     → hex_props.json ({(WEBSITE_DATA / 'hex_props.json').stat().st_size / 1e3:.0f} KB)")

    # TopoJSON for hex geometries (much smaller than GeoJSON)
    import topojson as tp
    hexes_slim = hexes[["hex_id", "geometry"]].copy()
    topo = tp.Topology(hexes_slim, prequantize=1e4)
    topo_path = WEBSITE_DATA / "hex_grid.topojson"
    with open(topo_path, "w") as f:
        f.write(topo.to_json())
    print(f"     → hex_grid.topojson ({topo_path.stat().st_size / 1e3:.0f} KB)")
else:
    print("     SKIP: hex_transit_deserts.geojson not found")


# =====================================================================
# 5. Corridor profiles → pass through
# =====================================================================
print("5/8  Copying corridor profiles...")
src = DATA_DIR / "corridor_profiles.json"
if src.exists():
    shutil.copy2(src, WEBSITE_DATA / "corridor_profiles.json")
    print(f"     → corridor_profiles.json")
else:
    print("     SKIP: corridor_profiles.json not found")


# =====================================================================
# 6. Counterfactual stations + stats
# =====================================================================
print("6/8  Processing counterfactual data...")
for filename in ["counterfactual_stations.geojson", "counterfactual_stats.json"]:
    src = DATA_DIR / filename
    if src.exists():
        shutil.copy2(src, WEBSITE_DATA / filename)
        print(f"     → {filename}")
    else:
        print(f"     SKIP: {filename} not found")

# Export existing rail station coordinates for JS-side 1km coverage check
_stops_4326 = gpd.read_file(DATA_DIR / "transit_stops.geojson")
_rail_4326 = _stops_4326[_stops_4326["route_category"].isin(["metro_rail", "commuter_rail"])]
_rail_coords = [[round(g.x, 5), round(g.y, 5)] for g in _rail_4326.geometry]
# Add D Line Section 1 (opened 2024, missing from GTFS)
_rail_coords += [[-118.3437, 34.0621], [-118.3614, 34.0622], [-118.3766, 34.0624]]
with open(WEBSITE_DATA / "rail_stations.json", "w") as f:
    json.dump(_rail_coords, f, separators=(",", ":"))
print(f"     → rail_stations.json ({len(_rail_coords)} stations)")

# Export BRT station coordinates (J Line + G Line) for JS-side coverage display
import partridge as ptg

_bus_dir = DATA_DIR / "la_metro_gtfs_bus"
# stop_times.txt is the one file the BRT export needs; it is large and was pruned
# from the feed directory. Keep the previously exported brt_stations.json when it
# is absent instead of crashing the whole export (2026-09-13).
if _bus_dir.exists() and not (_bus_dir / "stop_times.txt").exists():
    if (WEBSITE_DATA / "brt_stations.json").exists():
        print("     SKIP: stop_times.txt missing from la_metro_gtfs_bus; keeping existing brt_stations.json")
    else:
        print("     WARNING: stop_times.txt missing and no brt_stations.json to keep")
elif _bus_dir.exists():
    _bus_feed = ptg.load_raw_feed(str(_bus_dir))
    _brt_route_ids = [rid for rid in _bus_feed.routes["route_id"]
                      if str(rid).startswith("901") or str(rid).startswith("910")]
    _brt_trips = _bus_feed.trips[_bus_feed.trips["route_id"].isin(_brt_route_ids)]
    _brt_st = _bus_feed.stop_times[_bus_feed.stop_times["trip_id"].isin(_brt_trips["trip_id"])]
    _brt_stops = _bus_feed.stops[_bus_feed.stops["stop_id"].isin(_brt_st["stop_id"].unique())].copy()
    _brt_stops["stop_lat"] = _brt_stops["stop_lat"].astype(float)
    _brt_stops["stop_lon"] = _brt_stops["stop_lon"].astype(float)
    # Deduplicate paired platforms: merge stops within ~200m
    _brt_dedup = []
    _used = set()
    for _, s in _brt_stops.iterrows():
        if s["stop_id"] in _used:
            continue
        lat, lon = s["stop_lat"], s["stop_lon"]
        # Mark nearby stops as used
        for _, s2 in _brt_stops.iterrows():
            dlat = abs(float(s2["stop_lat"]) - lat)
            dlon = abs(float(s2["stop_lon"]) - lon)
            if dlat < 0.002 and dlon < 0.002:  # ~200m
                _used.add(s2["stop_id"])
        _brt_dedup.append([round(lon, 5), round(lat, 5)])
    with open(WEBSITE_DATA / "brt_stations.json", "w") as f:
        json.dump(_brt_dedup, f, separators=(",", ":"))
    print(f"     → brt_stations.json ({len(_brt_dedup)} stations)")
else:
    print("     SKIP: la_metro_gtfs_bus not found for BRT export")


# =====================================================================
# 7. Coverage stats → pass through
# =====================================================================
print("7/8  Copying coverage stats...")
src = DATA_DIR / "coverage_stats.json"
if src.exists():
    shutil.copy2(src, WEBSITE_DATA / "coverage_stats.json")
    print(f"     → coverage_stats.json")
else:
    print("     SKIP: coverage_stats.json not found")


# =====================================================================
# 8. Summary
# =====================================================================
print("\n8/8  Summary of Website/data/:")
total = 0
for f in sorted(WEBSITE_DATA.iterdir()):
    sz = f.stat().st_size
    total += sz
    print(f"     {f.name}: {sz/1e3:.0f} KB")
print(f"     TOTAL: {total/1e3:.0f} KB")
print("\nDone.")
