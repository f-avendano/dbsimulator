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
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext,
                       QgsProcessingUtils,
                       QgsProcessingParameterVectorDestination)
from datetime import datetime


class FlowPaths(QgsProcessingAlgorithm):



    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Visualising flow pathways '

    def displayName(self):
        return '3) Visualising flow pathways'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return FlowPaths()

    def shortHelpString(self):
        return self.tr('''This algorithm quickly identifies approximate flow pathways from an input flow accumulation raster. This tool generates a line vector which may not contain the right line direction. For more accurate (and suitable for post-processing) flow pathways, use the 'Identifying flow pathways' tool.
        
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
        
        
        ''')


    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterRasterLayer('FlowAcc', 'Flow accumulation raster'))
        self.addParameter(QgsProcessingParameterNumber('AreaThr', 'Area threshold (ha)', QgsProcessingParameterNumber.Double, defaultValue=1,))
        self.addParameter(QgsProcessingParameterVectorDestination('FlowPaths', 'Streams vector'))



    def processAlgorithm(self, parameters, context, feedback):

        flowacc = self.parameterAsRasterLayer(parameters, 'FlowAcc', context)
        areathr=self.parameterAsDouble(parameters,'AreaThr', context)
        output_flowpaths = self.parameterAsOutputLayer(parameters,'FlowPaths',context)

        
        feedback.pushInfo('''
        
        --------- Extracting streams -------------------
        
        ''')
        #Conversion from squared metres to hectares
        
        pixels=flowacc.rasterUnitsPerPixelX()
        expression = f'(({flowacc.name()}@1*{pixels})/10000)'

        flowacc_ha= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': flowacc,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        
        
        #Selecting streams more than the limit specified and vectorising 
        
        expression = f'(({flowacc_ha}@1>={areathr})*1)'
        
        drainage_network= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': flowacc_ha,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        
        #Converting to 'CELL' format to be handled by GRASS
        
        expression = f'(if(A>0, 1, null()))'
        
        to_cell = processing.run(
            "grass7:r.mapcalc.simple",{
            'a': drainage_network,
            'expression': expression,
            'output': 'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['output']

        #Filtering out zeros
        
        thinned = processing.run(
            "grass7:r.thin",{
            'input': to_cell,
            'output': 'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['output']
        
        #Converting to vector
        
        vector = processing.run(
            "grass7:r.to.vect",{
            'input': thinned,
            'type': 0,
            'output':output_flowpaths},context=context,feedback=feedback)['output']
        

        # Return results
        return {
        'FlowPaths': vector,
        }
        
        
        
    # def stream_net_by_threshold(self, flowacc, areathr,output_flowpaths, context, feedback):
        
        
        

