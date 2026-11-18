import processing
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsCoordinateReferenceSystem,
                       QgsProcessingException,
                       QgsProcessingOutputNumber,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterFeatureSink,
                       QgsFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext,
                       QgsProcessingUtils,
                       QgsVectorLayer,
                       QgsRasterLayer, 
                       QgsField,
                       QgsFields,
                       QgsFeature,
                       QgsGeometry,
                       QgsPoint,
                       QgsPointXY,
                       QgsProject,
                       QgsExpression,
                       QgsWkbTypes,
                       QgsVectorFileWriter,
                       QgsFeatureRequest,
                       QgsSpatialIndex,
                       QgsProcessingParameterVectorDestination)
from datetime import datetime
from qgis.utils import iface
import math
import tempfile
import time, gc, os


def safe_remove(path, feedback, retries=5, wait=0.1):
    """
    Try to os.remove(path) with GC + small sleep + retries to
    work around transient Windows file‐lock issues.
    """
    for _ in range(retries):
        if not os.path.exists(path):
            return
        try:
            os.remove(path)
            return
        except PermissionError:
            gc.collect()
            time.sleep(wait)
    feedback.pushWarning(f"Could not delete temp file: {path}")




def ensure_valid_vector(layer, name="layer", require_features=False):
    if layer is None:
        raise QgsProcessingException(f"{name} is None.")
    if not layer.isValid():
        raise QgsProcessingException(f"{name} is invalid.")
    if require_features and layer.featureCount() == 0:
        raise QgsProcessingException(f"{name} has no features.")
    return layer

def save_vector_layer(layer, path, transform_context, driver="GPKG", layer_name="saved_layer"):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, transform_context, options
    )

    # PyQGIS bindings vary a bit by version, so we only validate the reloaded layer.
    saved = QgsVectorLayer(path, layer_name, "ogr")
    if not saved.isValid():
        raise QgsProcessingException(f"Saved vector layer is not valid: {path}")
    return saved

def save_raster_path(path):
    if not os.path.exists(path):
        raise QgsProcessingException(f"Raster output does not exist: {path}")
    return path

class DBs_2(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'DBs-catch2'

    def displayName(self):
        return '8b) Detainment bund catchments tool (multi-scenario) '

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return DBs_2()

    def shortHelpString(self):
        return self.tr('''This algorithm estimates the storage pond, contributing area and storage:catchment ratio for potential detainment bunds previously simulated (DB simulation tool).
            Please be patient, since this proces may take some time and computer resources.
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    

    ''')


    def initAlgorithm(self, config=None):
        
        self.addParameter(QgsProcessingParameterVectorLayer('DB_locations', 'Potential DB locations'))
        self.addParameter(QgsProcessingParameterRasterLayer('FilledDEM', 'Filled DEM'))
        self.addParameter(QgsProcessingParameterRasterLayer('FlowDir', 'Flow direction raster'))
        self.addParameter(QgsProcessingParameterNumber('Memory', 'Max. memory usage (MB)', QgsProcessingParameterNumber.Double, defaultValue=2000,))
        self.addParameter(QgsProcessingParameterNumber('Z', 'Z factor', QgsProcessingParameterNumber.Double, defaultValue=1))
        self.addParameter(QgsProcessingParameterVectorDestination('Catchments', 'Potential DB catchments'))
        self.addParameter(QgsProcessingParameterRasterDestination('Depth', 'Catchment depth raster', optional=True))



    def processAlgorithm(self, parameters, context, feedback):
        
        
        locations=self.parameterAsVectorLayer(parameters, 'DB_locations', context)
        dem = self.parameterAsRasterLayer(parameters, 'FilledDEM', context)
        flowdir = self.parameterAsRasterLayer(parameters, 'FlowDir', context)
        z_factor=self.parameterAsDouble(parameters,'Z', context)
        memory = self.parameterAsDouble(parameters, 'Memory', context)
        catchments = self.parameterAsOutputLayer(parameters, 'Catchments', context)
        depth = self.parameterAsOutputLayer(parameters, 'Depth', context)
        
        # Create unique combinations of Length and Height
        unique_combinations = set()
        for feature in locations.getFeatures():
            length = feature['Length (m)']
            height = feature['Height (m)']
            unique_combinations.add((length, height))

        temp_files = []
        
        for length, height in unique_combinations:
            # Filter locations based on the height-length combination
            expression = QgsExpression(f'"Length (m)" = {length} AND "Height (m)" = {height}')
            request = QgsFeatureRequest(expression)
            filtered_locations = locations.materialize(request)
        
            feedback.pushInfo('''
            
            ---------Calculating DB catchments raster -------------------
            
            ''')

            
            
            ###NEW CODE FROM CHAT
            
            
            # =========================================================
            # COMMON SETTINGS
            # =========================================================
            transform_context = QgsProject.instance().transformContext()

            px = abs(dem.rasterUnitsPerPixelX())
            py = abs(dem.rasterUnitsPerPixelY())
            dem_extent = dem.extent()

            feedback.pushInfo(
                f"Processing scenario Length={length}, Height={height}"
            )

            # =========================================================
            # PHASE 1 — HYDROLOGY RASTERS
            # =========================================================

            # 1A. Buffer DB lines and stabilize to disk
            # buffer0 = processing.run("native:buffer", {
            #     'INPUT': filtered_locations,
            #     'DISTANCE': 1,
            #     'SEGMENTS': 1,
            #     'END_CAP_STYLE': 2,
            #     'JOIN_STYLE': 0,
            #     'MITER_LIMIT': 2,
            #     'DISSOLVE': False,
            #     'OUTPUT': 'TEMPORARY_OUTPUT'
            # }, context=context, feedback=feedback)["OUTPUT"]

            # buffer1 = processing.run("native:fixgeometries", {
            #     'INPUT': buffer0,
            #     'METHOD': 1,
            #     'OUTPUT': 'TEMPORARY_OUTPUT'
            # }, context=context, feedback=feedback)['OUTPUT']

            # ensure_valid_vector(buffer1, "buffer1", require_features=True)

            # buffer_path = QgsProcessingUtils.generateTempFilename('buffer.gpkg')
            # buffer = save_vector_layer(buffer1, buffer_path, transform_context, driver="GPKG", layer_name="buffer")

            buffer0 = processing.run("native:buffer", {
                'INPUT': filtered_locations,
                'DISTANCE': 1,
                'SEGMENTS': 1,
                'END_CAP_STYLE': 2,
                'JOIN_STYLE': 0,
                'MITER_LIMIT': 2,
                'DISSOLVE': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            buffer_path = QgsProcessingUtils.generateTempFilename('buffer.gpkg')

            processing.run("native:fixgeometries", {
                'INPUT': buffer0,
                'METHOD': 1,
                'OUTPUT': buffer_path
            }, context=context, feedback=feedback)

            buffer = QgsVectorLayer(buffer_path, "buffer_saved", "ogr")
            if not buffer.isValid():
                raise QgsProcessingException(f"Saved buffer layer is not valid: {buffer_path}")

            if buffer.featureCount() == 0:
                feedback.pushWarning(f"No buffered DB features for Length={length}, Height={height}. Skipping.")
                continue
            


            # 1B. Outlet points (keep your current logic here, but stabilize to disk before GRASS)
            points = processing.run("qgis:generatepointspixelcentroidsinsidepolygons", {
                'INPUT_RASTER': flowdir,
                'INPUT_VECTOR': buffer,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            dissolve = processing.run("native:dissolve", {
                'INPUT': points,
                'FIELD': 'poly_id',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            outlet_path = QgsProcessingUtils.generateTempFilename('outlets.gpkg')

            processing.run("native:orderbyexpression", {
                'INPUT': dissolve,
                'EXPRESSION': 'poly_id',
                'ASCENDING': True,
                'OUTPUT': outlet_path
            }, context=context, feedback=feedback)

            outlets_saved = QgsVectorLayer(outlet_path, "outlets_saved", "ogr")
            outlets_saved = ensure_valid_vector(outlets_saved, "outlets_saved", require_features=True)

            temp_watershed_raster = QgsProcessingUtils.generateTempFilename('watersheds.tif')

            watersheds = processing.run("grass7:r.stream.basins", {
                'direction': flowdir,
                'points': outlet_path,   # pass path, not temp layer object
                'memory': memory,
                'basins': temp_watershed_raster
            }, context=context, feedback=feedback)['basins']
            save_raster_path(watersheds)

            # 1C. Rasterize DB attributes on DEM grid
            rasterised_db_id = processing.run("gdal:rasterize", {
                'INPUT': buffer_path,
                'FIELD': 'DB_ID',
                'UNITS': 1,
                'WIDTH': px,
                'HEIGHT': py,
                'NODATA': 0,
                'EXTENT': dem_extent,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            rasterised_db_height = processing.run("gdal:rasterize", {
                'INPUT': buffer_path,
                'FIELD': 'Height (m)',
                'UNITS': 1,
                'WIDTH': px,
                'HEIGHT': py,
                'NODATA': 0,
                'EXTENT': dem_extent,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            
            epsg_code = dem.crs().authid() 
            
            id_translated=processing.run('gdal:translate',{
                'INPUT': rasterised_db_id,
                'DATA_TYPE': 5,
                'EXTRA': f'-a_srs "{epsg_code}"',
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']

            min_DB = processing.run('grass7:r.stats.zonal', {
                'base': id_translated,
                'cover': dem,
                'method': 2,   # minimum
                'GRASS_REGION_PARAMETER': dem,
                'output': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['output']

            min_DB_with_crs = processing.run('gdal:assignprojection', {
                'INPUT': min_DB,
                'CRS': dem.crs().toWkt(),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            db_hgt = processing.run("qgis:rastercalculator", {
                'EXPRESSION': f'"{min_DB_with_crs}@1" + "{rasterised_db_height}@1"',
                'LAYERS': [min_DB_with_crs, rasterised_db_height],
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            fill_nodata = processing.run("native:fillnodata", {
                'INPUT': db_hgt,
                'BAND': 1,
                'FILL_VALUE': 0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            # Build modified DEM with DB crest burned in
            new_dem_path = QgsProcessingUtils.generateTempFilename('NewDEM.tif')
            
            NewDEM = processing.run("qgis:rastercalculator", {
                'EXPRESSION': f'if("{fill_nodata}@1" > 0, "{fill_nodata}@1", "{dem.name()}@1")',
                'LAYERS': [fill_nodata, dem],
                'OUTPUT': new_dem_path
            }, context=context, feedback=feedback)["OUTPUT"]
            save_raster_path(NewDEM)
            
            
            
            ##WE NEED TO IMPORT SAGA RASTER, OTHERWISE SAGA FILLS SINKS USING B SPLINE INTERPOLATION AND IT IS MISALIGNED WITH THE ORIGINAL DEM CRS AND RESOLUTION

            saga_input = processing.run("sagang:importraster", {
            'FILES': NewDEM,
            'MULTIPLE': 0,
            'SUBSETS': [],
            'SELECTION': [],
            'TRANSFORM': True,
            'RESAMPLING': 0,       # nearest neighbour
            'EXTENT_SHAPES':locations,
            'EXTENT_BUFFER':0,
            'GRIDS': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["GRIDS"]
        

            FilledNewDEM = processing.run("sagang:fillsinksxxlwangliu", { ##WILL HAVE TO USE WANGLIU ONLY. EXTRA VALUES ARE GENERATED WHEN MIXING XXL AND NOT XXL
            'ELEV': saga_input,
            'MINSLOPE':0.0,
            'FILLED': 'TEMPORARY_OUTPUT',
            }, context=context, feedback=feedback)["FILLED"]


            filled_layer = QgsRasterLayer(FilledNewDEM, 'FilledNewDEM')
            if not filled_layer.isValid():
                raise QgsProcessingException("FilledNewDEM is invalid.")

            feedback.pushInfo(
                f"DEM pixel size: {dem.rasterUnitsPerPixelX()}, {dem.rasterUnitsPerPixelY()}"
            )
            feedback.pushInfo(
                f"Filled pixel size: {filled_layer.rasterUnitsPerPixelX()}, {filled_layer.rasterUnitsPerPixelY()}"
            )

            # IMPORTANT: subtract against modified terrain
            FillReg = processing.run("qgis:rastercalculator", {
                'EXPRESSION': f'("{FilledNewDEM}@1" - "{dem.name()}@1")',
                'LAYERS': [FilledNewDEM, dem],
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            FillRegMet = processing.run("qgis:rastercalculator", {
                'EXPRESSION': f'"{FillReg}@1" * {z_factor}',
                'LAYERS': [FillReg],
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            FillRegCM = processing.run("qgis:rastercalculator", {
                'EXPRESSION': f'"{FillRegMet}@1" * {px} * {py}',
                'LAYERS': [FillRegMet],
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

            Sinks_ID = processing.run("gdal:rastercalculator", {
                'INPUT_A': FillRegCM,
                'BAND_A': 1,
                'INPUT_B': watersheds,
                'BAND_B': 1,
                'FORMULA': '((A > 0) * B)',
                'NO_DATA': 0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            # =========================================================
            # PHASE 2 — POLYGONS + ATTRIBUTES
            # =========================================================

            polygonised_path = processing.run('grass7:r.to.vect', {
                'input': Sinks_ID,
                'type': 2,
                'column': 'value',
                '-s': True,
                'output': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['output']

            polygonised_raw = QgsVectorLayer(polygonised_path, "polygonised_raw", "ogr")
            polygonised_raw = ensure_valid_vector(polygonised_raw, "polygonised_raw", require_features=True)

            polygonised_fixed_tmp = processing.run("native:fixgeometries", {
                'INPUT': polygonised_raw,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            polygonised_fixed_path = QgsProcessingUtils.generateTempFilename('polygonised_fixed.gpkg')
            polygonised = save_vector_layer(
                polygonised_fixed_tmp,
                polygonised_fixed_path,
                transform_context,
                driver="GPKG",
                layer_name="polygonised"
            )

            # Use a stable DB_ID field source
            buffer_with_id = processing.run("native:fieldcalculator", {
                'INPUT': buffer,
                'FIELD_NAME': 'DBID_INT',
                'FIELD_TYPE': 1,
                'FORMULA': f'@id',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            buffer_with_id_path = QgsProcessingUtils.generateTempFilename('buffer_with_id.gpkg')
            buffer_with_id = save_vector_layer(
                buffer_with_id, buffer_with_id_path, transform_context, driver="GPKG", layer_name="buffer_with_id"
            )

            joined_tmp = processing.run("native:joinattributesbylocation", {
                'INPUT': polygonised,
                'JOIN': buffer_with_id,
                'PREDICATE': [0],   # intersects
                'JOIN_FIELDS': ['DB_ID', 'Contr_area', 'Height (m)', 'Length (m)'],
                'METHOD': 1,        # take attributes of first matching feature
                'DISCARD_NONMATCHING': True,
                'PREFIX': '',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            

            joined_tmp = ensure_valid_vector(joined_tmp, "joined_tmp")

            joined_path = QgsProcessingUtils.generateTempFilename('joined.gpkg')
            joined = save_vector_layer(joined_tmp, joined_path, transform_context, driver="GPKG", layer_name="joined")

            if joined.featureCount() == 0:
                feedback.pushWarning(
                    f"No joined basin polygons for Length={length}, Height={height}. Skipping."
                )
                continue

            fixed_tmp = processing.run("native:fixgeometries", {
                'INPUT': joined,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            fixed_path = QgsProcessingUtils.generateTempFilename('fixed.gpkg')
            fixed = save_vector_layer(fixed_tmp, fixed_path, transform_context, driver="GPKG", layer_name="fixed")

            area_tmp = processing.run("native:fieldcalculator", {
                'INPUT': fixed,
                'FIELD_NAME': 'Area_m2',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 20,
                'FIELD_PRECISION': 3,
                'FORMULA': '$area',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            area_path = QgsProcessingUtils.generateTempFilename('area.gpkg')
            area = save_vector_layer(area_tmp, area_path, transform_context, driver="GPKG", layer_name="area")

            delete_small_tmp = processing.run("native:extractbyexpression", {
                'INPUT': area,
                'EXPRESSION': '"Area_m2" >= 5',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            delete_small_path = QgsProcessingUtils.generateTempFilename('delete_small.gpkg')
            delete_small = save_vector_layer(
                delete_small_tmp, delete_small_path, transform_context, driver="GPKG", layer_name="delete_small"
            )

            if delete_small.featureCount() == 0:
                feedback.pushWarning(
                    f"All polygons were < 5 m2 for Length={length}, Height={height}. Skipping."
                )
                continue

            fixed2_tmp = processing.run("native:fixgeometries", {
                'INPUT': delete_small,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            fixed2_path = QgsProcessingUtils.generateTempFilename('fixed2.gpkg')
            fixed2 = save_vector_layer(fixed2_tmp, fixed2_path, transform_context, driver="GPKG", layer_name="fixed2")

            dissolve_catch_tmp = processing.run("native:dissolve", {
                'INPUT': fixed2,
                'FIELD': 'DB_ID',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            dissolve_catch_path = QgsProcessingUtils.generateTempFilename('dissolve_catch.gpkg')
            dissolve_catch = save_vector_layer(
                dissolve_catch_tmp, dissolve_catch_path, transform_context, driver="GPKG", layer_name="dissolve_catch"
            )

            # =========================================================
            # PHASE 3 — FINAL METRICS
            # =========================================================

            volume_tmp = processing.run("native:zonalstatisticsfb", {
                'INPUT': dissolve_catch,
                'INPUT_RASTER': FillRegCM,
                'RASTER_BAND': 1,
                'STATISTICS': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            volume_path = QgsProcessingUtils.generateTempFilename('volume.gpkg')
            volume = save_vector_layer(volume_tmp, volume_path, transform_context, driver="GPKG", layer_name="volume")

            volume2_tmp = processing.run("native:fieldcalculator", {
                'INPUT': volume,
                'FIELD_NAME': 'Volume_m3',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 20,
                'FIELD_PRECISION': 3,
                'FORMULA': 'coalesce("_sum", 0)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            volume2_path = QgsProcessingUtils.generateTempFilename('volume2.gpkg')
            volume2 = save_vector_layer(volume2_tmp, volume2_path, transform_context, driver="GPKG", layer_name="volume2")

            smoothed_tmp = processing.run("native:smoothgeometry", {
                'INPUT': volume2,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            # remove columns with a processing tool instead of edit sessions
            cols_to_delete = [c for c in ['_sum', 'value', 'cat', 'fid'] if smoothed_tmp.fields().indexFromName(c) != -1]

            if cols_to_delete:
                smoothed_tmp = processing.run("native:deletecolumn", {
                    'INPUT': smoothed_tmp,
                    'COLUMN': cols_to_delete,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                }, context=context, feedback=feedback)['OUTPUT']

            smoothed_path = QgsProcessingUtils.generateTempFilename('smoothed.gpkg')
            smoothed = save_vector_layer(smoothed_tmp, smoothed_path, transform_context, driver="GPKG", layer_name="smoothed")

            ratio_tmp = processing.run("native:fieldcalculator", {
                'INPUT': smoothed,
                'FIELD_NAME': 'Ratio',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 20,
                'FIELD_PRECISION': 6,
                'FORMULA': 'if("Contr_area" IS NULL OR "Contr_area" = 0, NULL, "Volume_m3" / "Contr_area")',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            ratio_path = QgsProcessingUtils.generateTempFilename('ratio.gpkg')
            ratio = save_vector_layer(ratio_tmp, ratio_path, transform_context, driver="GPKG", layer_name="ratio")

            sorted_tmp = processing.run("native:orderbyexpression", {
                'INPUT': ratio,
                'EXPRESSION': '"Ratio"',
                'ASCENDING': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            sorted_path = QgsProcessingUtils.generateTempFilename('sorted_catchment.gpkg')
            sorted_layer = save_vector_layer(
                sorted_tmp, sorted_path, transform_context, driver="GPKG", layer_name="sorted_layer"
            )

            temp_files.append(sorted_path)
            
            
            
        # Merge all the temporary shapefiles
        if len(temp_files) == 0:
            raise QgsProcessingException("No catchment outputs were generated.")

        merged_catchments = processing.run("native:mergevectorlayers", {
            'LAYERS': temp_files,
            'CRS': dem.crs(),
            'OUTPUT': catchments
        }, context=context, feedback=feedback)['OUTPUT']

        feedback.pushInfo(f'Merged catchments saved to: {catchments}')
        return {'Catchments': merged_catchments}

