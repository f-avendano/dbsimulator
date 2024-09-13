import processing
from qgis.PyQt.QtCore import (QCoreApplication,QVariant)
from qgis.analysis import QgsZonalStatistics
from qgis.core import (QgsProcessing,
                       QgsProject,
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
                       QgsField,
                       QgsProcessingUtils,
                       QgsVectorLayer,
                       QgsProcessingParameterVectorDestination)
from datetime import datetime


class AreaThreshold(QgsProcessingAlgorithm):




    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Identifying flow pathways (detailed)'

    def displayName(self):
        return '5) Identifying flow pathways (detailed)'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return AreaThreshold()

    def shortHelpString(self):
        return self.tr(    """
    This algorithm identifies flow pathways from a previously corrected DEM and flow accumulation rasters. 
    
    The 'Area threshold (ha)' parameter indicates the minimum drainage area of which flow pathways will be generated from. A larger value will take less processing time but will generate less detailed flow pathways.
    
    The 'Max. memory usage (MB)' parameter the amount of physical memory that can be used by this process.
    
    A line vector with an empty 'StreamType' field is generated from this tool, which has to be filled based on the strahler order category (field 'Strahler'). 
    
    Other outputs include a flow direction and a strahler order rasters.
    
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
    
    """)


    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterRasterLayer('FilledDEM', 'Filled DEM'))
        self.addParameter(QgsProcessingParameterRasterLayer('FlowAcc', 'Flow accumulation raster'))
        self.addParameter(QgsProcessingParameterNumber('AreaThr', 'Area threshold (ha)', QgsProcessingParameterNumber.Double, defaultValue=1,))
        self.addParameter(QgsProcessingParameterNumber('Memory', 'Max. memory usage (MB)', QgsProcessingParameterNumber.Double, defaultValue=2000,))
        self.addParameter(QgsProcessingParameterRasterDestination('streams_ras', 'Streams raster'))
        self.addParameter(QgsProcessingParameterVectorDestination('FlowPaths', 'Flow pathways'))
        self.addParameter(QgsProcessingParameterRasterDestination('flowdir', 'Flow direction'))


    def processAlgorithm(self, parameters, context, feedback):

        dem =  self.parameterAsRasterLayer(parameters, 'FilledDEM', context)
        areathr=self.parameterAsDouble(parameters,'AreaThr', context)
        flowacc = self.parameterAsRasterLayer(parameters, 'FlowAcc', context)
        streams_raster=self.parameterAsOutputLayer(parameters, 'streams_ras', context)
        flowdir=self.parameterAsOutputLayer(parameters, 'flowdir', context)
        memory = self.parameterAsDouble(parameters, 'Memory', context)
        output_flowpaths = self.parameterAsOutputLayer(parameters,'FlowPaths',context) 
        

        
        #Converting from hectares to squared meters
        thresh_meters = areathr * 10000
        
        #Dividing threshold in square meters by pixel size
        number_cells = int(thresh_meters / flowacc.rasterUnitsPerPixelX())
        
        result = processing.run("grass7:r.stream.extract", {
        'elevation': dem,
        'threshold': number_cells,
        'memory': memory,
        'GRASS GIS 7 region extent': dem,
        'GRASS_OUTPUT_TYPE_PARAMETER':2,
        'GRASS_REGION_CELLSIZE_PARAMETER' : 0,
        'GRASS_VECTOR_EXPORT_NOCAT' : False,
        'stream_length': 10,
        'accumulation' : None, 'd8cut' : None, 'depression' : None,
        'stream_vector':'TEMPORARY_OUTPUT',
        'stream_raster': streams_raster,
        'direction': flowdir,
        }, context=context, feedback=feedback)
        
        temp_stream_vector = result['stream_vector']
        
        # streams_raster=result['stream_raster']
        
        # flowdir=result['direction']
        
        # processing.run("saga:copyfeatures", {
        # 'SHAPES': temp_stream_vector,
        # 'COPY': output_flowpaths
        # }, context=context, feedback=feedback)        
        
        temp_output = QgsProcessingUtils.generateTempFilename('strahler.tif')
        
        # Run r.stream.order algorithm
        output_strahler = processing.run("grass7:r.stream.order", {
            'stream_ras': streams_raster,
            'direction': flowdir,
            'memory': memory,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'strahler': temp_output
        }, context=context, feedback=feedback)["strahler"]

        
        # Convert raster to vector
        output_strahler_v = processing.run("grass7:r.to.vect", {
            'input': output_strahler,
            'type': 0,
            'column': 'Strahler',
            #'-v': True,
            'output': 'TEMPORARY_OUTPUT' ###THIS MUST REMAIN AS THE VECTOR (VARIABLE) NAME!!!! ESPECIALLY WHEN IT'S A PARAMETERASOUTPUTLAYER'
        }, context=context, feedback=feedback)["output"]
        
        matched= processing.run("native:extractbyexpression", {
            'INPUT':output_strahler_v,
            'EXPRESSION':'length(@geometry)>=3',
            'OUTPUT':'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        joined=processing.run("native:joinattributesbylocation", {
            'INPUT':temp_stream_vector,
            'PREDICATE':[0],
            'JOIN':matched,
            'JOIN_FIELDS':['Strahler'],
            'METHOD':2,
            'DISCARD_NONMATCHING':False,
            'PREFIX':'',
            'OUTPUT':output_flowpaths}, context=context, feedback=feedback)['OUTPUT']
        
        # Open the output vector layer
        output_flowpaths_layer = QgsVectorLayer(output_flowpaths, 'FlowPaths', 'ogr')
        
        
        # Add a new field
        stream_type = 'StreamType'
        stream_type_index = output_flowpaths_layer.dataProvider().fieldNameIndex(stream_type)
        
        if stream_type_index == -1:  # Field doesn't exist, add it
            output_flowpaths_layer.dataProvider().addAttributes([QgsField(stream_type, QVariant.Double)])
            output_flowpaths_layer.updateFields()
        
        # Commit changes
        output_flowpaths_layer.updateFields()

        
        #Start editing
        output_flowpaths_layer.startEditing()
        
        for feature in output_flowpaths_layer.getFeatures():
            output_flowpaths_layer.changeAttributeValue(feature.id(),stream_type_index, 5)
        
        
        #Rename 'cat' field
        
        idx = output_flowpaths_layer.fields().indexFromName('cat')
        if idx != -1:
            output_flowpaths_layer.renameAttribute(idx, 'Strahler')
            
        #Delete 'label' field
        idx = output_flowpaths_layer.fields().indexFromName('label')
        if idx != -1:
            output_flowpaths_layer.deleteAttribute(idx)
            
        #Delete 'stream_typ' field
        idx = output_flowpaths_layer.fields().indexFromName('stream_typ')
        if idx != -1:
            output_flowpaths_layer.deleteAttribute(idx)

        #Delete 'type_code' field
        idx = output_flowpaths_layer.fields().indexFromName('type_code')
        if idx != -1:
            output_flowpaths_layer.deleteAttribute(idx)

        #Delete 'network' field
        idx = output_flowpaths_layer.fields().indexFromName('network')
        if idx != -1:
            output_flowpaths_layer.deleteAttribute(idx)
            
            
        # Commit changes
        output_flowpaths_layer.commitChanges()

        return {'FlowPaths': output_flowpaths,
        'streams_ras': streams_raster,
        'flowdir': flowdir
        }
        

