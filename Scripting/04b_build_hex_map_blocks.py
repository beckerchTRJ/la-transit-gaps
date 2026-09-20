"""
04b_build_hex_map_blocks.py
===========================
Build two interactive Folium maps using H3 hexagonal bins for population
density, sourced from **census blocks** instead of tracts. Produces:
  - Outputs/la_transit_density_hex_blocks_small.html   (H3 res 8, ~0.7 km²/hex)
  - Outputs/la_transit_density_hex_blocks_medium.html   (H3 res 7, ~5 km²/hex)

Density is displayed as persons / mi².

Transit layers (routes + stops) are identical to 04_build_hex_map.py.

Run from project root:
    python Scripting/04b_build_hex_map_blocks.py
"""

import json
import sys
from pathlib import Path

import folium
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from branca.colormap import LinearColormap
from branca.element import MacroElement, Template
from folium.plugins import Fullscreen, MarkerCluster
from shapely.geometry import Polygon

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
OUTPUT_DIR = PROJECT_ROOT / "Outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

DENSITY_PATH = DATA_DIR / "la_blocks_density.geojson"
ROUTES_PATH = DATA_DIR / "transit_routes.geojson"
STOPS_PATH = DATA_DIR / "transit_stops.geojson"

for p in [DENSITY_PATH, ROUTES_PATH, STOPS_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}\nRun scripts 01b and 02 first.")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading data...")
blocks_gdf = gpd.read_file(DENSITY_PATH).to_crs("EPSG:4326")
routes_gdf = gpd.read_file(ROUTES_PATH).to_crs("EPSG:4326")
stops_gdf = gpd.read_file(STOPS_PATH).to_crs("EPSG:4326")
print(f"  Blocks: {len(blocks_gdf)}, Routes: {len(routes_gdf)}, Stops: {len(stops_gdf)}")

# Precompute block areas in EPSG:3310 (CA Albers) for areal interpolation
blocks_3310 = blocks_gdf.to_crs("EPSG:3310")
blocks_gdf["block_area_m2"] = blocks_3310.geometry.area

# ---------------------------------------------------------------------------
# Route / stop styling (identical to 04_build_hex_map.py)
# ---------------------------------------------------------------------------
RAIL_DEFAULT_COLOR = "#1a1aff"
BUS_COLOR = "#ff6600"
NEUTRAL_STATION_COLOR = "#CCCCCC"


def get_route_color(feature):
    rc = feature["properties"].get("route_color") or ""
    if rc and len(rc) == 6:
        return f"#{rc}"
    category = feature["properties"].get("route_category", "metro_bus")
    if category in ("metro_rail", "commuter_rail"):
        return RAIL_DEFAULT_COLOR
    return BUS_COLOR


def rail_style(feature):
    return {"color": get_route_color(feature), "weight": 4, "opacity": 0.9}


def bus_style(feature):
    return {"color": BUS_COLOR, "weight": 1.5, "opacity": 0.55}


def metrolink_style(feature):
    return {"color": get_route_color(feature), "weight": 4, "opacity": 0.5}


def local_bus_style(feature):
    return {"color": "#4A90D9", "weight": 1.5, "opacity": 0.55}


FEED_DISPLAY_NAME = {
    "big_blue_bus": "Big Blue Bus",
    "foothill_transit": "Foothill Transit",
    "ladot": "LADOT",
    "long_beach_transit": "Long Beach Transit",
    "montebello": "Montebello Bus Lines",
    "culver_citybus": "Culver CityBus",
    "santa_clarita": "Santa Clarita Transit",
    "avta": "AVTA",
    "pasadena_transit": "Pasadena Transit",
    "gtrans": "GTrans",
    "norwalk_transit": "Norwalk Transit",
    "glendale_beeline": "Glendale Beeline",
    "torrance_transit": "Torrance Transit",
}

ROUTE_LAYERS = [
    {"category": "metro_bus", "name": "Metro Bus Routes", "show": True,
     "style_fn": bus_style, "tooltip_fields": ["route_short_name", "route_long_name"],
     "tooltip_aliases": ["Route", "Name"]},
    {"category": "local_bus", "name": "Municipal Bus Routes", "show": False,
     "style_fn": local_bus_style,
     "tooltip_fields": ["agency", "route_short_name", "route_long_name"],
     "tooltip_aliases": ["Agency", "Route", "Name"]},
    {"category": "commuter_rail", "name": "Metrolink Lines", "show": True,
     "style_fn": metrolink_style, "tooltip_fields": ["route_short_name", "route_long_name"],
     "tooltip_aliases": ["Line", "Name"]},
    {"category": "metro_rail", "name": "Metro Rail Lines", "show": True,
     "style_fn": rail_style, "tooltip_fields": ["route_short_name", "route_long_name"],
     "tooltip_aliases": ["Line", "Name"]},
]

STOP_LAYERS = [
    {"category": "metro_rail", "name": "Metro Rail Stations", "show": False,
     "color": "#1a1aff", "radius": 5, "opacity": 0.9, "use_cluster": False},
    {"category": "commuter_rail", "name": "Metrolink Stations", "show": False,
     "color": "#8B4513", "radius": 6, "opacity": 0.5, "use_cluster": False},
    {"category": "metro_bus", "name": "Metro Bus Stops", "show": False,
     "color": BUS_COLOR, "radius": 2, "use_cluster": True},
    {"category": "local_bus", "name": "Municipal Bus Stops", "show": False,
     "color": "#0066cc", "radius": 2, "use_cluster": True},
]

ROUTE_PANE = {
    "metro_bus": "busRoutesPane",
    "local_bus": "busRoutesPane",
    "commuter_rail": "metrolinkRoutesPane",
    "metro_rail": "railRoutesPane",
}

KM2_TO_MI2 = 0.386102

# ---------------------------------------------------------------------------
# H3 hex grid generation + areal interpolation
# ---------------------------------------------------------------------------

def build_hex_density(blocks_gdf, resolution):
    """Generate H3 hex grid over LA County and interpolate population from blocks."""
    print(f"  Building H3 hex grid at resolution {resolution}...")

    # Union boundary of all blocks (LA County outline)
    county_boundary = blocks_gdf.geometry.union_all()

    # Fill boundary with H3 cells
    hex_ids = set()
    if county_boundary.geom_type == "MultiPolygon":
        polygons = list(county_boundary.geoms)
    else:
        polygons = [county_boundary]

    for poly in polygons:
        exterior = list(poly.exterior.coords)
        h3_poly = h3.LatLngPoly([(lat, lng) for lng, lat in exterior])
        cells = h3.polygon_to_cells(h3_poly, resolution)
        hex_ids.update(cells)

    print(f"    {len(hex_ids)} hex cells generated")

    # Convert hex IDs to polygons
    hex_polys = []
    for hid in hex_ids:
        boundary = h3.cell_to_boundary(hid)
        coords = [(lng, lat) for lat, lng in boundary]
        coords.append(coords[0])
        hex_polys.append({"hex_id": hid, "geometry": Polygon(coords)})

    hex_gdf = gpd.GeoDataFrame(hex_polys, crs="EPSG:4326")

    # Areal interpolation via spatial overlay in EPSG:3310
    print("    Running areal interpolation...")
    hex_3310 = hex_gdf.to_crs("EPSG:3310")
    blocks_3310 = blocks_gdf[["geometry", "population", "block_area_m2"]].to_crs("EPSG:3310")

    hex_3310["_hex_idx"] = range(len(hex_3310))
    blocks_3310 = blocks_3310.copy()
    blocks_3310["_block_idx"] = range(len(blocks_3310))

    overlay = gpd.overlay(hex_3310[["_hex_idx", "geometry"]],
                          blocks_3310[["_block_idx", "geometry", "population", "block_area_m2"]],
                          how="intersection")
    overlay["intersection_area"] = overlay.geometry.area
    overlay["allocated_pop"] = overlay["population"] * (overlay["intersection_area"] / overlay["block_area_m2"])

    pop_by_hex = overlay.groupby("_hex_idx")["allocated_pop"].sum()

    hex_gdf["population"] = 0.0
    hex_gdf.loc[pop_by_hex.index, "population"] = pop_by_hex.values

    # Compute hex area in mi² and density
    hex_gdf["area_mi2"] = hex_3310.geometry.area / 1e6 * KM2_TO_MI2
    hex_gdf["density_mi2"] = hex_gdf["population"] / hex_gdf["area_mi2"]

    # Round for display
    hex_gdf["population"] = hex_gdf["population"].round(0).astype(int)
    hex_gdf["density_mi2"] = hex_gdf["density_mi2"].round(0)

    print(f"    Density range: {hex_gdf['density_mi2'].min():.0f} – {hex_gdf['density_mi2'].max():.0f} persons/mi²")
    return hex_gdf


# ---------------------------------------------------------------------------
# Map builder
# ---------------------------------------------------------------------------

def build_map(hex_gdf, routes_gdf, stops_gdf, resolution, output_path):
    """Build a Folium map with hex density layer and transit overlays."""
    print(f"\nBuilding map for resolution {resolution}...")

    # Colormap from hex density (2nd–Max percentile)
    valid = hex_gdf["density_mi2"].replace(0, np.nan).dropna()
    vmin = float(valid.quantile(0.02))
    vmax = float(valid.quantile(0.999))

    colormap = LinearColormap(
        colors=["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"],
        vmin=vmin, vmax=vmax,
        caption="Population Density (persons / mi²)",
    )

    def hex_style(feature):
        val = feature["properties"].get("density_mi2")
        if val is None or val == 0:
            return {"fillColor": "#f0f0f0", "color": "#cccccc", "weight": 0.3, "fillOpacity": 0.6}
        return {
            "fillColor": colormap(min(max(val, vmin), vmax)),
            "color": "#888888", "weight": 0.3, "fillOpacity": 0.7,
        }

    def hex_highlight(feature):
        return {"weight": 1.5, "color": "#333333", "fillOpacity": 0.85}

    m = folium.Map(
        location=[34.0522, -118.2437], zoom_start=10,
        min_zoom=9, max_zoom=15, tiles=None,
    )

    folium.TileLayer(tiles="CartoDB Positron", name="CartoDB Positron", control=False).add_to(m)

    # Custom panes
    pane_setup = MacroElement()
    pane_setup._template = Template("""
        {% macro script(this, kwargs) %}
            var map = {{ this._parent.get_name() }};
            map.createPane('densityPane');
            map.getPane('densityPane').style.zIndex = 400;
            map.createPane('stopsPane');
            map.getPane('stopsPane').style.zIndex = 450;
            map.createPane('busRoutesPane');
            map.getPane('busRoutesPane').style.zIndex = 420;
            map.createPane('metrolinkRoutesPane');
            map.getPane('metrolinkRoutesPane').style.zIndex = 430;
            map.createPane('railRoutesPane');
            map.getPane('railRoutesPane').style.zIndex = 440;
        {% endmacro %}
    """)
    pane_setup.add_to(m)

    # Hex density layer
    print("  Adding hex density layer...")
    density_layer = folium.FeatureGroup(name="Population Density (Hex)", show=True)
    hex_json = json.loads(hex_gdf.to_json())

    folium.GeoJson(
        hex_json,
        name="Population Density (Hex)",
        style_function=hex_style,
        highlight_function=hex_highlight,
        pane="densityPane",
        tooltip=folium.GeoJsonTooltip(
            fields=["population", "density_mi2"],
            aliases=["Est. Population", "Density (persons/mi²)"],
            localize=True, sticky=False, labels=True,
            style=(
                "background-color: white; color: #333333; font-family: Arial; "
                "font-size: 12px; padding: 6px; border-radius: 4px; "
                "box-shadow: 2px 2px 4px rgba(0,0,0,0.2);"
            ),
            max_width=250,
        ),
    ).add_to(density_layer)
    density_layer.add_to(m)

    # Stop layers
    for cfg in STOP_LAYERS:
        cat = cfg["category"]
        subset = stops_gdf[stops_gdf["route_category"] == cat].copy()
        if subset.empty:
            continue
        if cat == "local_bus" and "feed" in subset.columns:
            subset["agency"] = subset["feed"].map(FEED_DISPLAY_NAME).fillna(subset["feed"])
        print(f"  Adding {cfg['name']} ({len(subset)} stops)...")
        fg = folium.FeatureGroup(name=cfg["name"], show=cfg["show"])

        if cfg["use_cluster"]:
            cluster = MarkerCluster(name=cfg["name"])
            for _, row in subset.iterrows():
                stop_label = row.get("stop_name", "")
                if cat == "local_bus" and "agency" in row.index:
                    stop_label = f"{stop_label} ({row['agency']})"
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=cfg["radius"], color=cfg["color"],
                    fill=True, fill_color=cfg["color"], fill_opacity=0.6,
                    weight=0, pane="stopsPane",
                    tooltip=stop_label,
                ).add_to(cluster)
            cluster.add_to(fg)
        else:
            stop_opacity = cfg.get("opacity", 0.9)
            for _, row in subset.iterrows():
                n_routes = row.get("n_routes")
                if pd.notna(n_routes) and n_routes > 1:
                    stop_color = NEUTRAL_STATION_COLOR
                else:
                    rc = row.get("route_color")
                    rc = str(rc) if pd.notna(rc) else ""
                    stop_color = f"#{rc}" if len(rc) == 6 else cfg["color"]
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=cfg["radius"], color="#333333",
                    fill=True, fill_color=stop_color,
                    fill_opacity=stop_opacity, opacity=stop_opacity,
                    weight=2, pane="stopsPane",
                    tooltip=row.get("stop_name", ""),
                ).add_to(fg)
        fg.add_to(m)

    # Route layers
    for cfg in ROUTE_LAYERS:
        cat = cfg["category"]
        subset = routes_gdf[routes_gdf["route_category"] == cat].copy()
        if subset.empty:
            continue
        if cat == "local_bus" and "feed" in subset.columns:
            subset["agency"] = subset["feed"].map(FEED_DISPLAY_NAME).fillna(subset["feed"])
        print(f"  Adding {cfg['name']} ({len(subset)} routes)...")
        fg = folium.FeatureGroup(name=cfg["name"], show=cfg["show"])
        folium.GeoJson(
            json.loads(subset.to_json()),
            name=cfg["name"],
            style_function=cfg["style_fn"],
            pane=ROUTE_PANE[cat],
            tooltip=folium.GeoJsonTooltip(
                fields=cfg["tooltip_fields"], aliases=cfg["tooltip_aliases"],
                localize=True, sticky=False, labels=True,
                style="background-color: white; font-family: Arial; font-size: 12px; padding: 4px;",
                max_width=200,
            ),
        ).add_to(fg)
        fg.add_to(m)

    # Colormap legend
    colormap.add_to(m)
    colormap_css = """
    <style>
        .legend.leaflet-control {
            position: fixed !important;
            bottom: 10px !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            top: auto !important;
            right: auto !important;
            z-index: 1000;
            background: rgba(255, 255, 255, 0.92) !important;
            border-radius: 6px !important;
            padding: 6px 10px !important;
        }
        .legend.leaflet-control .caption {
            color: #333 !important;
        }
    </style>
    """
    m.get_root().html.add_child(folium.Element(colormap_css))

    # Rail line legend
    rail_categories = routes_gdf[routes_gdf["route_category"].isin(["metro_rail", "commuter_rail"])].copy()
    if not rail_categories.empty:
        legend_rows_html = ""
        for _, row in rail_categories.iterrows():
            name_short = row.get("route_short_name")
            name_long = row.get("route_long_name")
            name = (name_short if pd.notna(name_short) else None) or \
                   (name_long if pd.notna(name_long) else None) or "Unknown"
            rc = row.get("route_color")
            rc = str(rc) if pd.notna(rc) else ""
            color = f"#{rc}" if len(rc) == 6 else RAIL_DEFAULT_COLOR
            legend_rows_html += (
                f'<div style="display:flex;align-items:center;margin:2px 0;">'
                f'<span style="display:inline-block;width:24px;height:4px;'
                f'background:{color};margin-right:6px;border-radius:2px;"></span>'
                f'<span style="font-size:11px;color:#333;">{name}</span>'
                f'</div>'
            )

        legend_html = f"""
        <div id="rail-legend" style="
            position: fixed; bottom: 40px; left: 10px; z-index: 1000;
            background-color: rgba(255,255,255,0.92); padding: 8px 12px;
            border-radius: 6px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
            font-family: Arial, sans-serif; max-height: 300px; overflow-y: auto;
        ">
            <div style="font-size: 12px; font-weight: bold; color: #222; margin-bottom: 4px;">
                Rail Lines
            </div>
            {legend_rows_html}
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # Title
    res_label = "Small" if resolution == 8 else "Medium"
    title_html = f"""
    <div style="
        position: fixed; top: 15px; left: 60px; z-index: 1000;
        background-color: rgba(255,255,255,0.92); padding: 10px 16px;
        border-radius: 6px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
        font-family: Arial, sans-serif; pointer-events: none;
    ">
        <div style="font-size: 16px; font-weight: bold; color: #222;">
            Los Angeles: Population Density &amp; Transit Network
        </div>
        <div style="font-size: 11px; color: #666; margin-top: 3px;">
            H3 Hex Bins (res {resolution}, {res_label}) &nbsp;|&nbsp;
            2020 Decennial Census Blocks &nbsp;|&nbsp; LA Metro, Metrolink &amp; 13 Municipal Agencies GTFS
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    print(f"  Saving to {output_path}...")
    m.save(str(output_path))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    configs = [
        (8, OUTPUT_DIR / "la_transit_density_hex_blocks_small.html"),
        (7, OUTPUT_DIR / "la_transit_density_hex_blocks_medium.html"),
    ]

    for resolution, output_path in configs:
        hex_gdf = build_hex_density(blocks_gdf, resolution)
        build_map(hex_gdf, routes_gdf, stops_gdf, resolution, output_path)

    print("\nDone. Output files:")
    for _, path in configs:
        print(f"  {path}")
