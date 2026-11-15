"""Batch graph construction. Only the explicit submit command imports/initializes ee."""
from common import BANDS

COMMON_COLUMNS = [
    "schema_version", "run_id", "dataset_id", "catalog_sha256", "config_sha256",
    "location_id", "name", "canonical_latitude", "canonical_longitude", "year",
    "footprint_radius_m", "record_type", "image_id", "product_date_utc",
    "pixel_x", "pixel_y", "pixel_center_latitude", "pixel_center_longitude",
    "native_pixel_area_m2", "requested_footprint_area_m2", "image_count",
    "image_dates", "image_ids", "grid_crs", "grid_transform", "native_center_count", "native_pixel_keys",
]
COLUMNS = COMMON_COLUMNS + BANDS + [band + "_present" for band in BANDS]


def build_export(ee, config, location, year, run_id, catalog_hash, config_hash):
    """Native-grid pixel centres, including masked cells, plus a partition inventory."""
    collection = ee.ImageCollection(config["dataset_id"]).filterDate(config["start_date"], config["end_date_exclusive"])
    source = collection.filterDate(f"{year}-01-01", f"{year + 1}-01-01").sort("system:time_start")
    projection = ee.Image(collection.first()).select("LST_Day_1km").projection()
    region = ee.Geometry.Point([location["canonical_longitude"], location["canonical_latitude"]]).buffer(
        config["footprint_radius_m"], config["geometry_max_error_m"])
    common = {
        "schema_version": "earth-thermal-availability-raw/1.0.0", "run_id": run_id,
        "dataset_id": config["dataset_id"], "catalog_sha256": catalog_hash,
        "config_sha256": config_hash, **location, "year": year,
        "footprint_radius_m": config["footprint_radius_m"],
    }

    def sample_image(value):
        image = ee.Image(value)
        raw = image.select(BANDS)
        presence = raw.mask().unmask(0, sameFootprint=False).gt(0).rename([band + "_present" for band in BANDS])
        # Lossless signed storage keeps -9999 representable for uint8/uint16 bands.
        values = raw.toInt32().unmask(config["masked_sentinel"], sameFootprint=False)
        values = values.addBands(presence).addBands(
            ee.Image.pixelCoordinates(projection).rename(["pixel_x", "pixel_y"])
        ).addBands(ee.Image.pixelLonLat().rename(["pixel_center_longitude", "pixel_center_latitude"])).addBands(
            ee.Image.pixelArea().reproject(projection).rename("native_pixel_area_m2"))
        # No scale override, random subsampling, resampling, or drop of masked rows.
        samples = values.sample(region=region, projection=projection, dropNulls=False,
                                tileScale=config["export_tile_scale"], geometries=False)
        metadata = {**common, "record_type": "pixel", "image_id": image.get("system:index"),
                    "product_date_utc": image.date().format("YYYY-MM-dd")}
        return samples.map(lambda feature: ee.Feature(feature).set(metadata))

    pixels = ee.FeatureCollection(source.toList(source.size()).map(sample_image)).flatten()
    dates = ee.List(source.aggregate_array("system:time_start")).map(lambda value: ee.Date(value).format("YYYY-MM-dd"))
    grid = ee.Image.pixelCoordinates(projection).sample(region=region, projection=projection, geometries=False)
    def pixel_key(feature):
        feature = ee.Feature(feature)
        return feature.set("key", ee.Number(feature.get("x")).format("%.0f").cat(":").cat(ee.Number(feature.get("y")).format("%.0f")))
    grid_keys = grid.map(pixel_key).aggregate_array("key")
    inventory = ee.Feature(None, {
        **common, "record_type": "partition_inventory", "image_count": source.size(),
        "image_dates": dates.join("|"), "image_ids": ee.List(source.aggregate_array("system:index")).join("|"),
        "native_center_count": grid.size(), "native_pixel_keys": ee.List(grid_keys).sort().join("|"),
        "grid_crs": projection.crs(), "grid_transform": projection.transform(),
        "requested_footprint_area_m2": region.area(config["geometry_max_error_m"]),
    })
    return ee.FeatureCollection([inventory]).merge(pixels)
