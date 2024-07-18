import processing

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
                       QgsProcessingContext)

from datetime import datetime


class ManualCutterAlgorithm(QgsProcessingAlgorithm):

    ATTRIBUTE_FIELD = 'ATTRIBUTE_FIELD'
    CutLines = 'CutLines'


    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Manual Cutter'

    def displayName(self):
        return 'Manual Cutter'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return ManualCutterAlgorithm()

    def shortHelpString(self):
        return self.tr('''This tool takes an input line vector and burns it into an input DEM raster. 
    
    
    Please be patient, since this proces might take some time and computer resources.
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
    
    ''')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer('CutLines', 'Cut Lines'))
        #self.addParameter(QgsProcessingParameterVectorLayer('DamLines', 'Dam Lines', optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer('DEM', 'Filled DEM Raster'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputNewDEM', 'Output New DEM'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputFillDEM', 'Output New Filled DEM'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputFlowAcc', 'Output Flow Accumulation'))
        self.addParameter(QgsProcessingParameterRasterDestination('OutputHshd', 'Output Hillshade'))
        self.addParameter(QgsProcessingParameterNumber('ZFactor', 'Z Factor', type=QgsProcessingParameterNumber.Double, minValue=0.0, defaultValue=1))

    def processAlgorithm(self, parameters, context, feedback):
        # Get parameter values
        cut_lines = self.parameterAsVectorLayer(parameters, 'CutLines', context)
        #dam_lines = self.parameterAsVectorLayer(parameters, 'DamLines', context)
        #attribute_field = self.parameterAsString(parameters, self.ATTRIBUTE_FIELD, context)
        dem = self.parameterAsRasterLayer(parameters, 'DEM', context)
        output_new_dem = self.parameterAsOutputLayer(parameters, 'OutputNewDEM', context)
        output_fill_dem = self.parameterAsOutputLayer(parameters, 'OutputFillDEM', context)
        output_flow_acc = self.parameterAsOutputLayer(parameters, 'OutputFlowAcc', context)
        output_hillshade = self.parameterAsOutputLayer(parameters, 'OutputHshd', context)
        z_factor = self.parameterAsDouble(parameters, 'ZFactor', context)
        
        cut_zmin = None  # Initialize cut_zmin to None
        dam_zmax = None # Initialize dam_zmax to None
        
        # Perform the necessary processing using PyQGIS functions
        if cut_lines:
            # Perform processing for cut lines
            feedback.pushInfo(f"Processing {cut_lines.featureCount()} Cut features")
            
            if not dem.isValid() or not cut_lines.isValid():
                print('Invalid layers. Check file paths.')
            else:
                    
                buffer_distance = 0.5
                buffer_segments = 1
                    
                    
                buffered_layer = processing.run("native:buffer", {
                'INPUT': cut_lines,
                'DISTANCE': buffer_distance,
                'SEGMENTS': buffer_segments,
                'OUTPUT': 'TEMPORARY_OUTPUT'  # Output to memory to create a temporary layer
                }, context=context, feedback=feedback) ["OUTPUT"]
                
                zonal_stats = processing.run(
                "native:zonalstatisticsfb", {
                'INPUT': buffered_layer,
                'INPUT_RASTER': dem,
                'RASTER_BAND': 1,
                'COLUMN_PREFIX': "_",
                'STATISTICS': 5,
                'OUTPUT': 'TEMPORARY_OUTPUT'  
                }, context=context, feedback=feedback)["OUTPUT"]
                    
               # QgsZonalStatistics(buffered_layer, dem, "_", QgsZonalStatistics.Min)
               # zonal_stats.calculateStatistics(None)
                
                rasterized_buffer = processing.run(
                    'gdal:rasterize',
                    {
                    'INPUT': zonal_stats,
                    'FIELD': "_min",
                    'UNITS': 1,
                    'WIDTH': 1.0,
                    'HEIGHT': 1.0,
                    'NODATA': 0.0,
                    'EXTENT': dem,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context,
                    feedback=feedback)["OUTPUT"]
                
                input_layers = [dem, rasterized_buffer]
                
                output_new_dem = processing.run(
                    'gdal:merge',
                    {
                    'INPUT': input_layers,
                    'NODATA_OUTPUT':0.0,
                    'OUTPUT': output_new_dem
                    },
                    context=context,
                    feedback=feedback)["OUTPUT"]
                
                
        else:
        # If cut_lines are not provided, create NewDEM from the original DEM
            output_new_dem = dem

        # Fill the NewDEM
        output_fill_dem = processing.run("saga:fillsinksxxlwangliu", {
            'ELEV': output_new_dem,
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
            'INPUT': output_new_dem,
            'AZIMUTH': 315,
            'V_ANGLE': 45,
            'Z_FACTOR': z_factor,
            'OUTPUT': output_hillshade
        }, context=context, feedback=feedback)["OUTPUT"]

        
        # Return results
        return {
            'OutputNewDEM': output_new_dem,
            'OutputFillDEM': output_fill_dem,
            'OutputFlowAcc': output_flow_acc,
            'OutputHshd': output_hillshade
        }
