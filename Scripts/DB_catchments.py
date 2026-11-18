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


class DBs(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'DBs-catch'

    def displayName(self):
        return '8a) Detainment bund catchments tool'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return DBs()

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





        
        # List of potential field names for height
        potential_height_fields = ['EmbankHgt', 'Height']
        field_name_to_use = "Height (m)"  # New valid field name without special characters
        
        # Get the existing field names
        fields = locations.fields()
        
        # Find the first existing height field
        existing_field = None
        for field in fields:
            if field.name() in potential_height_fields:
                existing_field = field.name()
                break

        # If we found a field, use fieldcalculator to create a new field with a valid name
        if existing_field:
            feedback.pushInfo(f"Found existing field: {existing_field}. Creating new field '{field_name_to_use}'")
            
            # Step 1: Create a new field and populate it with the same values (temporary output)
            renamed = processing.run("qgis:fieldcalculator", {
                'INPUT': locations,
                'FIELD_NAME': field_name_to_use,
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 10,
                'FIELD_PRECISION': 3,
                'NEW_FIELD': True,
                'FORMULA': f'"{existing_field}"',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
            
            feedback.pushInfo(f"New field '{field_name_to_use}' created and populated from '{existing_field}'.")

            # Step 2: Optionally delete the old field (temporary output)
            deleted = processing.run("qgis:deletecolumn", {
                'INPUT': renamed,  # Use the renamed layer here
                'COLUMN': [existing_field],  # List of columns to delete
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
            
            feedback.pushInfo(f"Old field '{existing_field}' deleted.")

        else:
            feedback.pushInfo("No valid height field found in the input layer.")
            
            deleted = locations

        feedback.pushInfo('''
        ---------Calculating DB catchments raster -------------------
        ''')

        # Step 3: Now, run buffer on the `deleted` layer (or `renamed` if you didn’t delete the field)
        buffer = processing.run("native:buffer", {
            'INPUT': deleted,
            'DISTANCE': 1,
            'SEGMENTS': 1,
            'END_CAP_STYLE': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)["OUTPUT"]

        feedback.pushInfo("Buffer operation completed.")


        points= processing.run("qgis:generatepointspixelcentroidsinsidepolygons", {
            'INPUT_RASTER': flowdir,
            'INPUT_VECTOR':buffer,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]


        dissolve= processing.run("native:dissolve", {
            'INPUT': points,
            'FIELD':'poly_id',
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]


        dissolved_sorted=processing.run("native:orderbyexpression", {   
            'INPUT': dissolve,
            'EXPRESSION': 'poly_id',
            'ASCENDING': True,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']


        temp_raster = QgsProcessingUtils.generateTempFilename('temp_raster.tif')

        #Finding watersheds of all detainment bund places
        
        watersheds= processing.run(
            "grass7:r.stream.basins",{
            'direction': flowdir,
            'points': dissolved_sorted,
            'memory': memory,
            'basins':temp_raster},context=context,feedback=feedback)['basins']

        
        feedback.pushInfo('''
        
        ---------Calculating DB catchments area and volume -------------------
        
        ''')


        #dem_crs = dem.crs().toWkt()
        #feedback.pushInfo(f'DEM CRS: {dem_crs}')
        #feedback.pushInfo(f'Extent: {dem.extent().toString()}')
        epsg_code = dem.crs().authid() 
        
        #Rasterizing DBs based on ID parameter

        rasterised_db_id=processing.run('gdal:rasterize',{
            'INPUT': buffer, #was locations
            'FIELD': 'DB_ID',
            'UNITS': 1,
            'WIDTH': 1.0,
            'HEIGHT': 1.0,
            'NODATA': 0,
            'EXTENT': buffer.extent(), #was dem
            'EXTRA': f'-a_srs "{epsg_code}"',
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']


        #Rasterizing DBs based on height parameter

        rasterised_db_height=processing.run('gdal:rasterize',{
            'INPUT': buffer, #was locations
            'FIELD': 'Height (m)',
            'UNITS': 1,
            'WIDTH': 1.0,
            'HEIGHT': 1.0,
            'NODATA': 0,
            'EXTENT': buffer.extent(), #was dem
            'EXTRA': f'-a_srs "{epsg_code}"',
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        #Converting format, needed for GRASS zonal stats processing
        
        id_translated=processing.run('gdal:translate',{
            'INPUT': rasterised_db_id,
            'DATA_TYPE': 5,
            'EXTRA': f'-a_srs "{epsg_code}"',
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']


        min_DB = processing.run('grass7:r.stats.zonal', {
            'base': id_translated,
            'cover': dem,
            'method': 2,
            'GRASS_REGION_PARAMETER': dem,
            'output': 'TEMPORARY_OUTPUT' 
            }, context=context, feedback=feedback)['output']
            
        min_DB_with_crs = processing.run('gdal:assignprojection', {
            'INPUT': min_DB,
            'CRS': dem.crs().toWkt(),
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            
        expression =f'\"{min_DB_with_crs}@1\" + \"{rasterised_db_height}@1\"'
        
        db_hgt= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [rasterised_db_height, min_DB_with_crs],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        #Filling db_hgt no data cells with zeros for processing, then creating New DEM with DBs burned, and filling DEM
        fill_nodata= processing.run("native:fillnodata", {
            'INPUT': db_hgt,
            'BAND':1,
            'FILL_VALUE': 0,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

        expression = f'(({fill_nodata}@1>0)*{fill_nodata}@1+({fill_nodata}@1=0)*\"{dem.name()}@1\")'
        


        NewDEM= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [dem, fill_nodata],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
            
            
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


        expression =f'\"{FilledNewDEM}@1\" - \"{dem.name()}@1\"'
        #expression =f'\"{FilledNewDEM}@1\" - \"{saga_input}@1\"'
        
        
        FillReg= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [FilledNewDEM, dem],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]        



        # Convert FillReg (which represents the volume of storage at every sink cell in the DEM) to volume in cubic metres        
        expression = f'({FillReg}@1 * {z_factor})'
        
        FillRegMet = processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [FillReg],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        pixels=dem.rasterUnitsPerPixelX()
        
        expression = f'({FillRegMet}@1 * {pixels} * {pixels})'
        
        FillRegCM = processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [FillRegMet],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]

        # Convert values of all sink cells to the WASCOBID of the watershed that it falls in


        expression = f'((A > 0) * B)' ##EXPRESSIONS IN GDAL NEEDS SPACES!
        
        Sinks_ID = processing.run("gdal:rastercalculator", {
            'INPUT_A': FillRegCM,
            'BAND_A': 1,
            'INPUT_B':watersheds,
            'BAND_B': 1,
            'FORMULA': expression,
            'NO_DATA': 0,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        polygonised = processing.run('grass7:r.to.vect', {
            'input': Sinks_ID,
            'type': 2,
            'column': 'value',
            '-s': True,
            'output': 'TEMPORARY_OUTPUT' 
            }, context=context, feedback=feedback)['output']
        
        ID_field = processing.run("native:fieldcalculator", {
            'INPUT': locations,
            'FIELD_NAME': "ID",
            'FIELD_TYPE': 0, 
            'FORMULA': f'@id+1', #was id+1
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
        
        joined=processing.run("native:joinattributestable", {
            'INPUT': polygonised,
            'FIELD': 'value',
            'INPUT_2': ID_field,
            'FIELD_2': 'ID',
            'FIELDS_TO_COPY': ['DB_ID', 'Contr_area', 'Height (m)'],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        
        fixed=processing.run("native:fixgeometries", {
            'INPUT': joined,
            'METHOD': 1,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']



        area=processing.run("native:fieldcalculator", {
            'INPUT':fixed, 
            'FIELD_NAME': "Area (m2)",
            'FIELD_TYPE': 1,
            'FORMULA':"area(@geometry)",
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']


        expression = f'( ("Area (m2)" >=5))'


        # delete_small = processing.run("native:extractbyexpression", {
        #     'INPUT': area,
        #     'EXPRESSION': expression,
        #     'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']        
        

        fixed2=processing.run("native:fixgeometries", {
            'INPUT': area,
            'METHOD': 1,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']


    
        dissolve=processing.run("native:dissolve", {
            'INPUT': fixed2,
            'FIELD': 'DB_ID',
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        
        volume = processing.run("native:zonalstatisticsfb", {
            'INPUT': dissolve,
            'INPUT_RASTER': FillRegCM,
            'RASTER_BAND': 1,
            'STATISTICS': 1,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']
        
        
        volume2=processing.run("native:fieldcalculator", {
            'INPUT':volume, 
            'FIELD_NAME': "Volume(m3)",
            'FIELD_TYPE': 1,
            'FORMULA':"_sum",
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        

        smoothed=processing.run("native:smoothgeometry", { 
            'INPUT': volume2,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']



        # Recalculate area AFTER dissolve and smoothing, for the full pond footprint.
        # The earlier area value belongs to an individual pre-dissolve polygon.
        smoothed.startEditing()
        area_idx = smoothed.fields().indexFromName('Area (m2)')
        if area_idx < 0:
            smoothed.rollBack()
            raise QgsProcessingException('Missing Area (m2) field in pond output')
        for pond_feature in smoothed.getFeatures():
            smoothed.changeAttributeValue(
                pond_feature.id(), area_idx, float(pond_feature.geometry().area())
            )
        if not smoothed.commitChanges():
            raise QgsProcessingException('Could not save recalculated pond areas')

        # Open editing session
        smoothed.startEditing()
        
        
        #Delete _sum field
        idx = smoothed.fields().indexFromName('_sum')
        if idx != -1:
            smoothed.deleteAttribute(idx)
        
        #Delete value  field
        idx = smoothed.fields().indexFromName('value')
        if idx != -1:
            smoothed.deleteAttribute(idx)
        
        #Delete cat  field
        idx = smoothed.fields().indexFromName('cat')
        if idx != -1:
            smoothed.deleteAttribute(idx)
        
        #Delete fid field
        idx = smoothed.fields().indexFromName('fid')
        if idx != -1:
            smoothed.deleteAttribute(idx)
            
            
        # Close editing session and save changes
        smoothed.commitChanges() 



        transform_context = QgsProject.instance().transformContext()
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "ESRI Shapefile"
        save_options.fileEncoding = "UTF-8"

        
        QgsVectorFileWriter.writeAsVectorFormatV3(smoothed, catchments, transform_context, save_options)

         
         

        
        ratio=processing.run("native:fieldcalculator", {
            'INPUT':smoothed, 
            'FIELD_NAME': "Ratio",
            'FIELD_TYPE': 1,
            'FORMULA':'"Volume(m3)"/"Contr_area"',
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        
        sorted=processing.run("native:orderbyexpression", {   
            'INPUT': ratio,
            'EXPRESSION': "Ratio",
            'ASCENDING': False,
            'OUTPUT': catchments
        }, context=context, feedback=feedback)['OUTPUT']      
        
        
        expression = f'((A > 0) * A)'
            
        nodata = processing.run("gdal:rastercalculator", {
            'INPUT_A': FillReg,
            'BAND_A': 1,
            'FORMULA': expression,
            'NO_DATA': 0,
            'OUTPUT': depth
        }, context=context, feedback=feedback)['OUTPUT']

        

        

        return {'Catchments':sorted,'Depth': nodata}
