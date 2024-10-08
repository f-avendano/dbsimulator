
import tempfile
import os
import processing
from qgis.PyQt.QtCore import QCoreApplication
from qgis.analysis import QgsZonalStatistics
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProject,
                       QgsProcessingException,
                       QgsProcessingOutputNumber,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext)

from datetime import datetime






class D8TerrainProcessingAlgorithm(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Terrain Processing'

    def displayName(self):
        return '1) Terrain Processing'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return D8TerrainProcessingAlgorithm()
    
    def shortHelpString(self):
        return self.tr('''This algorithm fills a DEM and generates a hillshade raster
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
    ''')


    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer('DEM', 'DEM Raster'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputFillDEM', 'Output Fill DEM'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputHshd', 'Output Hillshade'))
        self.addParameter(QgsProcessingParameterNumber('ZFactor', 'Z Factor', type=QgsProcessingParameterNumber.Double, minValue=0.0, defaultValue=1))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputFlowAcc', 'Output Flow Accumulation'))


    def processAlgorithm(self, parameters, context, feedback):
        # Get parameter values
        dem = self.parameterAsRasterLayer(parameters, 'DEM', context)
        output_fill_dem = self.parameterAsOutputLayer(parameters, 'OutputFillDEM', context)
        output_flow_acc = self.parameterAsOutputLayer(parameters, 'OutputFlowAcc', context)       
        output_hillshade = self.parameterAsOutputLayer(parameters, 'OutputHshd', context)
        z_factor = self.parameterAsDouble(parameters, 'ZFactor', context)
        
        
        
        ''' Processing'''

        if not dem.isValid():
            print('Invalid layers. Check file paths.')
        else:
            output_fill_dem = processing.run("saga:fillsinksxxlwangliu", { 
            'ELEV': dem,
            'MINSLOPE':0.0,
            'FILLED': output_fill_dem,
            }, context=context, feedback=feedback)["FILLED"]

            # Calculate Flow Accumulation
            output_flow_acc = processing.run("grass7:r.watershed", {
                'elevation': output_fill_dem,
                'threshold': 500000,
                'memory': 3000,
                '-s': True,
                '-a': True,
                'accumulation': output_flow_acc
            }, context=context, feedback=feedback)["accumulation"]
        
            # Calculate Hillshade
            output_hillshade = processing.run("native:hillshade", {
            'INPUT': output_fill_dem,
            'AZIMUTH': 315,
            'V_ANGLE': 45,
            'Z_FACTOR': z_factor,
            'OUTPUT': output_hillshade
            }, context=context, feedback=feedback)["OUTPUT"]
            
        # Return results
        return {
            'OutputFillDEM': output_fill_dem,
            'OutputHshd': output_hillshade,
            'OutputFlowAcc': output_flow_acc
        }
    
    
    


