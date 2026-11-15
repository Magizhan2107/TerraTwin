"""Server-side native-centre thermal diagnostics. Constructs graphs only; no I/O."""
import calendar
from common import DATASET, dates_in_year
from cloud_rules import METRICS, PHASES, flags

VERSION = 'earth-thermal-cloud/1.0.0'
PIPELINE = 'native-centre-cloud/1.0.0'
FLAG_NAMES = [f'{p}__{m}' for p in PHASES for m in METRICS]


def build_compact(ee, config, location, year, run_id, hashes, source_override=None):
    """One location/year -> 12 month features + one year feature, no raw rows.

    source_override is for bounded/synthetic verification only, never exposed
    by the submission CLI. Every spatial reducer is unweighted (centre inclusion).
    """
    all_source = ee.ImageCollection(config['dataset_id']).filterDate(config['start_date'], config['end_date_exclusive'])
    projection = ee.Image(all_source.first()).select('LST_Day_1km').projection()
    source = (source_override if source_override is not None else all_source).filterDate(
        f'{year}-01-01', f'{year+1}-01-01').sort('system:time_start')
    region = ee.Geometry.Point([location['canonical_longitude'], location['canonical_latitude']]).buffer(
        config['footprint_radius_m'], config['geometry_max_error_m'])
    def spatial(image):
        # A weighted reducer would change boundary-cell semantics. Never bestEffort/scale override.
        return image.reduceRegion(reducer=ee.Reducer.sum().unweighted(), geometry=region,
                                  crs=projection, maxPixels=1000000, tileScale=config['export_tile_scale'])
    area = ee.Image.pixelArea().reproject(projection).rename('area')
    grid = spatial(ee.Image.constant(1).rename('centres').setDefaultProjection(projection).addBands(area))
    centres = ee.Number(grid.get('centres'))
    total_area = ee.Number(grid.get('area'))
    zero = ee.Image.constant([0] * len(FLAG_NAMES)).rename(FLAG_NAMES).setDefaultProjection(projection)

    def daily_image(image):
        image = ee.Image(image)
        masks = {p: flags(ee, image, p, config) for p in PHASES}
        raster = ee.Image.cat([masks[p][m].rename(f'{p}__{m}') for p in PHASES for m in METRICS])
        return raster.setDefaultProjection(projection).set({
            'system:time_start': image.get('system:time_start'),
            'date': image.date().format('YYYY-MM-dd'), 'source_id': image.get('system:index')})
    rasters = source.map(daily_image)
    threshold = config['exploratory_monthly_thresholds']['same_product_date_spatial_support_fraction_min']

    def daily_feature(value):
        image = ee.Image(value)
        supports = [image.select(f'{p}__strict_qa_in_phase').multiply(area).rename(p + '_area') for p in PHASES]
        joint = image.select('day__strict_qa_in_phase').And(image.select('night__strict_qa_in_phase'))
        sums = spatial(image.addBands(supports).addBands(joint.rename('joint_pixels')).addBands(joint.multiply(area).rename('joint_area')))
        props = {'date': image.get('date'), 'source_id': image.get('source_id')}
        for name in FLAG_NAMES:
            count = ee.Number(sums.get(name))
            props[name + '__pixels'] = count
            props[name + '__dates'] = count.gt(0)
        for p in PHASES:
            support = ee.Number(sums.get(p + '_area'))
            props[p + '__supported_dates'] = support.gt(0).And(support.divide(total_area).gte(threshold))
        ja = ee.Number(sums.get('joint_area'))
        props.update(joint_pixels=sums.get('joint_pixels'), joint_dates=ee.Number(sums.get('joint_pixels')).gt(0),
                     joint_supported_dates=ja.gt(0).And(ja.divide(total_area).gte(threshold)), joint_fraction=ja.divide(total_area))
        return ee.Feature(None, props)
    daily = ee.FeatureCollection(rasters.toList(rasters.size()).map(daily_feature))
    sum_names = [name+'__'+unit for name in FLAG_NAMES for unit in ('pixels','dates')] + [
        p+'__supported_dates' for p in PHASES] + ['joint_pixels','joint_dates','joint_supported_dates','joint_fraction']
    dates = ee.List(source.aggregate_array('system:time_start')).map(lambda t: ee.Date(t).format('YYYY-MM-dd'))
    valid_source = dates.distinct().size().eq(source.size()).And(
        ee.List(source.aggregate_array('system:index')).distinct().size().eq(source.size()))
    common = {**location, 'planet': 'Earth', 'schema_version': VERSION, 'pipeline_version': PIPELINE,
              'run_id': run_id, 'dataset_id': DATASET, 'source_product_version': '061', **hashes,
              'footprint_radius_m': config['footprint_radius_m'], 'native_grid': projection.crs(),
              'grid_transform_wkt': projection.transform(), 'native_centres': centres,
              'sampled_centre_area_m2': total_area, 'requested_footprint_area_m2': region.area(config['geometry_max_error_m']),
              'threshold_status': config['threshold_status'], 'mission_suitability': 'not_assessed'}

    def period(month):
        label = str(year) if month is None else f'{year}-{month:02d}'
        start = f'{year}-01-01' if month is None else f'{label}-01'
        end = f'{year+1}-01-01' if month is None or month == 12 else f'{year}-{month+1:02d}-01'
        calendar_days = len(dates_in_year(year)) if month is None else calendar.monthrange(year, month)[1]
        subset = daily.filter(ee.Filter.gte('date', start)).filter(ee.Filter.lt('date', end))
        images = rasters.filterDate(start, end)
        # Seed zeros so explicitly empty collections produce known zero counts with the right bands/grid.
        summed = images.merge(ee.ImageCollection.fromImages([zero])).sum()
        contributing = spatial(summed.gt(0))
        size = subset.size()
        totals = ee.List(ee.Algorithms.If(size.gt(0), subset.reduceColumns(
            reducer=ee.Reducer.sum().repeat(len(sum_names)), selectors=sum_names).get('sum'),
            ee.List.repeat(0, len(sum_names))))
        def addsum(name):
            return ee.Number(totals.get(sum_names.index(name)))
        props = {**common, 'period': label, 'period_type': 'year' if month is None else 'month',
                 'calendar_dates': calendar_days, 'source_product_dates': size,
                 'source_date_fraction': size.divide(calendar_days), 'missing_product_dates': ee.Number(calendar_days).subtract(size),
                 'pixel_date_records': centres.multiply(size), 'source_image_ids': ee.List(subset.aggregate_array('source_id')).join('|'),
                 'source_product_dates_list': ee.List(subset.aggregate_array('date')).join('|')}
        for name in FLAG_NAMES:
            for unit in ('pixels', 'dates'):
                props[name + '__' + unit] = addsum(name + '__' + unit)
            props[name + '__centres'] = contributing.get(name)
            props[name + '__calendar_fraction'] = props[name + '__dates'].divide(calendar_days)
        for p in PHASES:
            props[p + '__supported_dates'] = addsum(p + '__supported_dates')
            props[p + '__supported_calendar_fraction'] = props[p + '__supported_dates'].divide(calendar_days)
        props.update(joint_pixels=addsum('joint_pixels'), joint_dates=addsum('joint_dates'),
                     joint_supported_dates=addsum('joint_supported_dates'),
                     joint_mean_calendar_fraction=addsum('joint_fraction').divide(calendar_days))
        limits = config['exploratory_monthly_thresholds']
        enough = ee.Number(1)
        for p in PHASES:
            enough = enough.And(props[p + '__supported_dates'].gte(limits['strict_qa_phase_dates_min'])).And(
                props[p + '__supported_calendar_fraction'].gte(limits['strict_qa_phase_date_fraction_min']))
        enough = enough.And(props['joint_supported_dates'].divide(calendar_days).gte(limits['strict_qa_phase_date_fraction_min']))
        nonzero = props['day__strict_qa_in_phase__dates'].gt(0).And(props['night__strict_qa_in_phase__dates'].gt(0))
        props['coverage_screen'] = 'not_evaluated_year' if month is None else ee.Algorithms.If(enough, 'meets_exploratory_screen', 'below_exploratory_screen')
        props['status'] = ee.Algorithms.If(nonzero, 'data_available' if month is None else ee.Algorithms.If(enough, 'data_available', 'insufficient_coverage'), 'no_eligible_observations')
        props['status_reason'] = ee.Algorithms.If(nonzero, 'year_screen_not_defined' if month is None else ee.Algorithms.If(enough, 'provisional_screen_only', 'below_provisional_monthly_screen'), 'one_or_both_phases_have_zero_strict_window_dates')
        props['unknown_qc_present'] = props['day__qc_missing__pixels'].add(props['night__qc_missing__pixels']).gt(0)
        # Duplicate source dates/IDs are a failure, never valid double-counted diagnostics.
        failure = {**common, 'period': label, 'period_type': props['period_type'], 'calendar_dates': calendar_days,
                   'status': 'processing_failure', 'status_reason': 'duplicate_source_date_or_id'}
        return ee.Feature(None, ee.Algorithms.If(valid_source, props, failure))
    return ee.FeatureCollection([period(m) for m in list(range(1, 13)) + [None]])
