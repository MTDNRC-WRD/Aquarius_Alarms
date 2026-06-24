from pathlib import Path
import geopandas as gpd
import fiona

# --------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------
GDB_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form.gdb')
FILE_GDB = 'WSB_Discharge_Measurement_Form_Data'
AGOL_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form_Data.shp')

# --------------------------------------------------------------------
# Helper to get field names from a GeoDataFrame
# (excluding geometry column)
# --------------------------------------------------------------------
def get_field_names(gdf):
    geom_col = gdf.geometry.name
    return [c for c in gdf.columns if c != geom_col]

# --------------------------------------------------------------------
# Read FGDB feature class and shapefile
# --------------------------------------------------------------------
# FGDB: pass the .gdb folder as path and the feature class as "layer"
gdb_path = str(GDB_FILE)

# Optional sanity check: list layers in the gdb
print("GDB layers:", fiona.listlayers(gdb_path))

gdf_gdb = gpd.read_file(gdb_path, layer=FILE_GDB)
gdf_shp = gpd.read_file(AGOL_FILE)

gdb_fields = get_field_names(gdf_gdb)
shp_fields = get_field_names(gdf_shp)

print("GDB fields:", gdb_fields)
print("SHP fields:", shp_fields)

# --------------------------------------------------------------------
# Build mapping dict by index position
# e.g. {'GDB_field_1': 'SHP_field_1', ...}
# --------------------------------------------------------------------
min_len = min(len(gdb_fields), len(shp_fields))
field_map = {
    gdb_fields[i]: shp_fields[i]
    for i in range(min_len)
}

print("Field mapping:")
for k, v in field_map.items():
    print(f"{k} -> {v}")

# --------------------------------------------------------------------
# Save mapping to JSON (optional)
# --------------------------------------------------------------------
import json
out_json = Path("field_mapping_gdb_to_shp.json")
with out_json.open("w", encoding="utf-8") as f:
    json.dump(field_map, f, indent=2)

print(f"Saved mapping to {out_json.resolve()}")