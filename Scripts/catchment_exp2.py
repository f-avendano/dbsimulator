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
                       QgsRasterLayer,
                       QgsPointXY,
                       QgsProject,
                       QgsExpression,
                       QgsWkbTypes,
                       QgsVectorFileWriter,
                       QgsFeatureRequest,
                       QgsSpatialIndex,
                       QgsRasterBandStats,
                       QgsProcessingParameterVectorDestination)
from datetime import datetime
from qgis.utils import iface
from qgis.analysis import QgsRasterCalculatorEntry
import math


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




        

        # Step 1: Get unique combinations of 'Height (m)' and 'Length (m)' fields
        unique_combinations = set()
        for feature in locations.getFeatures():
            height = feature['Height (m)']
            length = feature['Length (m)']
            unique_combinations.add((height, length))

        feedback.pushInfo(f'Processing {len(unique_combinations)} unique Height-Length combinations.')

        # Step 2: Process each combination separately
        combined_catchments = []  # List to store the catchments for each combination
        
        
        for height, length in unique_combinations:
            feedback.pushInfo(f'Processing Height: {height}, Length: {length}')

            # Filter locations for the current height and length
            request = QgsFeatureRequest().setFilterExpression(f'"Height (m)" = {height} AND "Length (m)" = {length}')
            selected_locations = locations.materialize(QgsFeatureRequest(request))


            # Repeat your existing logic but replace `locations` with `selected_locations`
            buffer = processing.run("native:buffer", {
            'INPUT': selected_locations,
            'DISTANCE': 1,
            'SEGMENTS': 1,
            'END_CAP_STYLE': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]


            temp_depth_file = QgsProcessingUtils.generateTempFilename(f"depth_{height}_{length}.tif")


            rasterised_db_id=processing.run('grass7:v.to.rast',{
                'input': buffer, #was locations
                'attribute_column': 'DB_ID',
                'GRASS_REGION_PARAMETER': dem.extent(),
                'GRASS_REGION_CELLSIZE_PARAMETER': 1,
                'output': temp_depth_file}, context=context, feedback=feedback)['output']


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


            #Finding watersheds of all detainment bund places
            
            watersheds= processing.run(
                "grass7:r.stream.basins",{
                'direction': flowdir,
                'points': dissolve,
                'memory': memory,
                'basins':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['basins']

            
            feedback.pushInfo('''
            
            ---------Calculating DB catchments area and volume -------------------
            
            ''')


            #dem_crs = dem.crs().toWkt()
            #feedback.pushInfo(f'DEM CRS: {dem_crs}')
            #feedback.pushInfo(f'Extent: {dem.extent().toString()}')
            epsg_code = dem.crs().authid() 

            
            # #Rasterizing DBs based on height parameter

            rasterised_db_height=processing.run('gdal:rasterize',{
                'INPUT': buffer, #was locations
                'FIELD': 'Height (m)',
                'UNITS': 1,
                'WIDTH': 1.0,
                'HEIGHT': 1.0,
                'NODATA': 0,
                'EXTENT': buffer,
                'EXTRA': f'-a_srs "{epsg_code}"',
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
            
            # #Converting format, needed for GRASS zonal stats processing
            
            # id_translated=processing.run('gdal:translate',{
            #     'INPUT': rasterised_db_id,
            #     'DATA_TYPE': 5,
            #     'EXTRA': f'-a_srs "{epsg_code}"',
            #     'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']


            min_DB = processing.run('grass7:r.stats.zonal', {
                'base': rasterised_db_id,
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

            expression = f'(({fill_nodata}@1>0)*{fill_nodata}@1+({fill_nodata}@1=0)*{dem.name()}@1)'
            


            NewDEM= processing.run("qgis:rastercalculator", {
                'EXPRESSION': expression,
                'LAYERS': [dem, fill_nodata],
                'OUTPUT': 'TEMPORARY_OUTPUT'
                }, context=context, feedback=feedback)["OUTPUT"]

            FilledNewDEM = processing.run("saga:fillsinksxxlwangliu", { ##WILL HAVE TO USE WANGLIU ONLY. EXTRA VALUES ARE GENERATED WHEN MIXING XXL AND NOT XXL
                'ELEV': NewDEM,
                'MINSLOPE':0.0,
                'FILLED': 'TEMPORARY_OUTPUT',
                }, context=context, feedback=feedback)["FILLED"]

            expression =f'\"{FilledNewDEM}@1\" - \"{dem.name()}@1\"'
            
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
                'INPUT': buffer,
                'FIELD_NAME': "ID",
                'FIELD_TYPE': 0, 
                'FORMULA': f'@id', ##was+1
                'OUTPUT': 'TEMPORARY_OUTPUT'
                }, context=context, feedback=feedback)['OUTPUT']
            
            joined=processing.run("native:joinattributestable", {
                'INPUT': polygonised,
                'FIELD': 'value',
                'INPUT_2': ID_field,
                'FIELD_2': 'ID',
                'FIELDS_TO_COPY': ['DB_ID', 'Contr_area', 'Height (m)', 'Length (m)'],
                'METHOD': 1,
                'DISCARD_NONMATCHING': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            
                        
            fixed=processing.run("native:fixgeometries", {
                'INPUT': joined,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            
            
            dissolve=processing.run("native:dissolve", {
                'INPUT': fixed,
                'FIELD': 'DB_ID',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            
            volume = processing.run("native:zonalstatisticsfb", {
                'INPUT': dissolve,
                'INPUT_RASTER': FillRegCM, ##FillRegCM
                'RASTER_BAND': 1,
                'STATISTICS': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
            
            
            volume2=processing.run("native:fieldcalculator", {
                'INPUT':volume, 
                'FIELD_NAME': "Volume(m3)",
                'FIELD_TYPE': 0,
                'FORMULA':"_sum",
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
            

            
            area=processing.run("native:fieldcalculator", {
                'INPUT':volume2, 
                'FIELD_NAME': "Area (m2)",
                'FIELD_TYPE': 0,
                'FORMULA':"area(@geometry)",
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']

            smoothed=processing.run("native:smoothgeometry", { 
                'INPUT': area,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

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

            # Save the renamed layer to the final output
            QgsVectorFileWriter.writeAsVectorFormat(smoothed, catchments, 'utf-8', smoothed.crs(), 'ESRI Shapefile')

            
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
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']      
            


            #Eliminating no data from depth raster
            
            expression = f'((A > 0) * A)'
                
            nodata = processing.run("gdal:rastercalculator", {
                'INPUT_A': FillReg,
                'BAND_A': 1,
                'FORMULA': expression,
                'NO_DATA': 0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

            # Save the catchment result for this combination (you can save it to a temporary layer)
            catchment_layer = sorted

            # Append the result to the list of combined catchments
            combined_catchments.append(catchment_layer)            

        if len(combined_catchments) > 1:
            final_catchments = processing.run("native:mergevectorlayers", {
                'LAYERS': combined_catchments,
                'CRS': dem.crs().toWkt(),
                'OUTPUT': catchments
            }, context=context, feedback=feedback)['OUTPUT']
        else:
            final_catchments = combined_catchments[0]

        return {'Catchments': final_catchments}