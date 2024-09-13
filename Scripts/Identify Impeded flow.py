import processing
import os
import tempfile
from qgis.PyQt.QtCore import QCoreApplication
from qgis.analysis import QgsZonalStatistics
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingOutputNumber,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext,
                       QgsProcessingUtils,
                       QgsProject)
from datetime import datetime




class ImpededFlow(QgsProcessingAlgorithm):

    """
    This algorithm identifies impeded flow by subtracting an unfilled DEM from a filled DEM 
    and extracting only positive values from the difference raster.
    """


    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Identify Impeded Flow'

    def displayName(self):
        return '2) Identify impeded flow'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return ImpededFlow()

    def shortHelpString(self):
        return self.tr('''This algorithm identifies impeded flow by subtracting an unfilled DEM from a filled DEM and extracting only positive values from the difference raster.
        
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    

        ''')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer('DEM', 'Unfilled DEM Raster (hydroconditioned)'))
        self.addParameter(QgsProcessingParameterRasterLayer('FilledDEM', 'Filled DEM Raster'))
        self.addParameter(QgsProcessingParameterRasterDestination('DepthGrid', 'Impeded flow'))

    def processAlgorithm(self, parameters, context, feedback):
        # Get parameter values
        dem = self.parameterAsRasterLayer(parameters, 'DEM', context)
        filled=self.parameterAsRasterLayer(parameters, 'FilledDEM', context)
        output_depthgrid= self.parameterAsOutputLayer(parameters, 'DepthGrid', context)
        
        
        # Perform the necessary processing using PyQGIS functions
        if not dem.isValid():
            print('Invalid layers. Check file paths.')
        
        else:
            
            # #Creating a temporary raster. SAGA needs a raster destination as it does not handle well the 'OUTPUT' = 'TEMPORARY_OUTPUT' like other
            # #processing tools
            # temp_output = QgsProcessingUtils.generateTempFilename('raster_difference.tif')
            
            
            # #Using SAGA for substracting the Unfilled DEM from the Filled DEM
            # raster_difference = processing.run("saga:rasterdifference", {
            # 'A': filled,
            # 'B': dem,
            # 'C': temp_output
            # }, context=context, feedback=feedback)["C"]
            
            
            expression =f'\"{filled.name()}@1\" - \"{dem.name()}@1\"'
            
            
            raster_difference = processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': [filled, dem],
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
            
            
            #Declaring the expression to use in the raster calculator
            expression = f'((\"{raster_difference}@1\" > 0) * \"{raster_difference}@1\")'
            
            
            
            #We use raster calculator for making all negative values as zero
            output_noneg = processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': raster_difference,
            'OUTPUT': output_depthgrid
            }, context=context, feedback=feedback)["OUTPUT"]
            
            
            # #We use GDAL translate tool to eliminate all zero values and obtain only positive numbers
            # depthgrid = processing.run("gdal:translate", {
            # 'INPUT': output_noneg,
            # 'NODATA': 0,
            # 'OUTPUT': output_depthgrid
            # }, context=context, feedback=feedback)["OUTPUT"]
            
            

        # Return results
        return {
            'DepthGrid': output_noneg
            }
