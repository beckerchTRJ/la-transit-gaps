"""
utils_hex.py
============
Shared hex grid utilities extracted from 04b_build_hex_map_blocks.py.
"""

import geopandas as gpd
import h3
import numpy as np
from shapely.geometry import Polygon

KM2_TO_MI2 = 0.386102


def build_hex_density(blocks_gdf, resolution):
    """Generate H3 hex grid over LA County and interpolate population from blocks.

    Parameters
    ----------
    blocks_gdf : GeoDataFrame
        Census blocks with 'population' and 'block_area_m2' columns, CRS EPSG:4326.
    resolution : int
        H3 resolution (7 or 8).

    Returns
    -------
    GeoDataFrame
        Hex grid with columns: hex_id, geometry, population, area_mi2, density_mi2.
    """
    print(f"  Building H3 hex grid at resolution {resolution}...")

    county_boundary = blocks_gdf.geometry.union_all()

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

    hex_polys = []
    for hid in hex_ids:
        boundary = h3.cell_to_boundary(hid)
        coords = [(lng, lat) for lat, lng in boundary]
        coords.append(coords[0])
        hex_polys.append({"hex_id": hid, "geometry": Polygon(coords)})

    hex_gdf = gpd.GeoDataFrame(hex_polys, crs="EPSG:4326")

    print("    Running areal interpolation...")
    hex_3310 = hex_gdf.to_crs("EPSG:3310")
    blocks_3310 = blocks_gdf[["geometry", "population", "block_area_m2"]].to_crs("EPSG:3310")

    hex_3310["_hex_idx"] = range(len(hex_3310))
    blocks_3310 = blocks_3310.copy()
    blocks_3310["_block_idx"] = range(len(blocks_3310))

    overlay = gpd.overlay(
        hex_3310[["_hex_idx", "geometry"]],
        blocks_3310[["_block_idx", "geometry", "population", "block_area_m2"]],
        how="intersection",
    )
    overlay["intersection_area"] = overlay.geometry.area
    overlay["allocated_pop"] = overlay["population"] * (
        overlay["intersection_area"] / overlay["block_area_m2"]
    )

    pop_by_hex = overlay.groupby("_hex_idx")["allocated_pop"].sum()

    hex_gdf["population"] = 0.0
    hex_gdf.loc[pop_by_hex.index, "population"] = pop_by_hex.values

    hex_gdf["area_mi2"] = hex_3310.geometry.area / 1e6 * KM2_TO_MI2
    hex_gdf["density_mi2"] = hex_gdf["population"] / hex_gdf["area_mi2"]

    hex_gdf["population"] = hex_gdf["population"].round(0).astype(int)
    hex_gdf["density_mi2"] = hex_gdf["density_mi2"].round(0)

    print(
        f"    Density range: {hex_gdf['density_mi2'].min():.0f} – "
        f"{hex_gdf['density_mi2'].max():.0f} persons/mi²"
    )
    return hex_gdf
