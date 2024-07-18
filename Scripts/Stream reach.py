import processing
import subprocess
import os
import multiprocessing
import tempfile
import shutil
import time
from qgis.PyQt.QtCore import (QCoreApplication,QVariant)
from qgis.core import (QgsProcessingAlgorithm, 
                        QgsProcessing,
                        QgsProcessingParameterEnum,
                        QgsProcessingParameterField,
                        QgsProcessingParameterFeatureSource, 
                        QgsProcessingParameterRasterLayer, 
                        QgsProcessingParameterRasterDestination,
                        QgsProcessingParameterString,
                        QgsProcessingParameterNumber, 
                        QgsProcessingParameterVectorLayer,
                        QgsProcessingParameterVectorDestination,
                        QgsProcessingParameterFeatureSink,
                        QgsProcessingParameterFolderDestination,
                        QgsProcessingUtils,
                        QgsVectorLayer,
                        QgsRasterLayer,
                        QgsProject,
                        QgsFields,
                        QgsVectorFileWriter,
                        QgsWkbTypes)
from os import listdir, remove
from os.path import isfile, realpath, join, split, basename, splitext
from subprocess import run
from datetime import datetime
import getpass



class StreamReachAlgorithm(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'StreamReachAlgorithm'

    def displayName(self):
        return 'Stream Reach Algorithm'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return StreamReachAlgorithm()
        

    def shortHelpString(self):
        return self.tr('''This algorithm identifies the main reaches from the previous step 'Identify flow pathways (detailed)' and creates a stream reach and catchments vector layer using Taudem

    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
    
    ''')

    
    def initAlgorithm(self, config=None):
        # Define parameters

        
        self.addParameter(QgsProcessingParameterVectorLayer('FlowNetwork', 'Flow Network', types=[QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterRasterLayer('D8FlowDir', 'D8 Flow Direction'))
        self.addParameter(QgsProcessingParameterRasterLayer('DEMFill', 'DEM Fill'))
        self.addParameter(QgsProcessingParameterField('LimitField', 'LimitField', type=QgsProcessingParameterField.Numeric, parentLayerParameterName='FlowNetwork', allowMultiple=False, defaultValue=None, optional=True))
        self.addParameter(QgsProcessingParameterNumber('ClassValue', 'Class Value', type=QgsProcessingParameterNumber.Double, defaultValue=1))
        self.addParameter(QgsProcessingParameterVectorDestination('OutStreamReach', 'Output Stream Reach'))
        self.addParameter(QgsProcessingParameterVectorDestination('OutCatchments', 'Output Catchments'))


    def processAlgorithm(self, parameters, context, feedback):
        

        
        # Retrieve parameters
        flow_network = self.parameterAsVectorLayer(parameters, 'FlowNetwork', context)
        d8_flow_dir = self.parameterAsRasterLayer(parameters, 'D8FlowDir', context)
        dem_fill = self.parameterAsRasterLayer(parameters, 'DEMFill', context)
        limit_field = self.parameterAsString(parameters, 'LimitField', context)
        class_value = self.parameterAsString(parameters, 'ClassValue', context)
        out_stream_reach = self.parameterAsOutputLayer(parameters, 'OutStreamReach', context)
        out_catchments = self.parameterAsOutputLayer(parameters, 'OutCatchments', context)
        
        
        '''FIRST WE CLASSIFY ACCORDING TO CRITERIA OF LIMIT FIELD AND CREATE A NEW VECTOR FROM THIS'''
        

        if limit_field == '':
            flow_network.selectAll()
            # Save the selected features to the output stream reach layer
            extracted = processing.run("native:saveselectedfeatures", {'INPUT': flow_network, 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        
            
        else:
            # There is a field that will be used to refine stream reach and catchment generation
            
            if class_value:
                
                #expression = f'"{limit_field}" IN ({class_value})'
                expression=f'"{limit_field}" >= {class_value}'
                
                extracted = processing.run("native:extractbyexpression", {
                'INPUT': flow_network, 
                'EXPRESSION': expression,
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']

            
            else:
                raise ValueError("Must select classification value...QUITTING!!!")
        
        
        '''HERE WE CREATE A NEW FIELD FOR OUR NEW LINE VECTOR'''
        
        
        ID_field=processing.run("native:fieldcalculator", {
        'INPUT':extracted , 
        'FIELD_NAME': "ID",
        'FORMULA':"@id",
        'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        
        '''HERE WE RASTERISE OUR LINE VECTOR'''
        
        
        rasterized_lines = processing.run(
            'gdal:rasterize',
            {
            'INPUT': ID_field,
            'FIELD': "ID",
            'UNITS': 1,
            'WIDTH': 1.0,
            'HEIGHT': 1.0,
            'NODATA': 0.0,
            'EXTENT': dem_fill,
            'OUTPUT': 'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
        
        
        
        '''HERE WE OBTAIN THE ABSOLUTE VALUES OF FLOWDIR OF GRASS GIS, SINCE IT HAS NEGATIVE VALUES'''
        
        expression = f'(({d8_flow_dir.name()}@1 < 0) * -1*{d8_flow_dir.name()}@1 + ({d8_flow_dir.name()}@1 >= 0) *{d8_flow_dir.name()}@1)' 

        
        flowdir_abs = processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': d8_flow_dir,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        
        
        '''HERE WE CREATE A TABLE AND REWRITE (RECLASSIFY) THE VALUES OF OUR ABSOLUTE FLOWDIR RASTER TO FOLLOW TAUDEM RULES'''
        
        
        table = ['8','8','1','1','1','2','2','2','3','3','3','4','4','4','5','5','5','6','6','6','7','7','7','8']
        

        reclassified= processing.run("native:reclassifybytable", {
        'INPUT_RASTER':flowdir_abs, 
        'RASTER_BAND': 1,
        'TABLE':table,
        'NO_DATA': None, 
        'RANGE_BOUNDARIES':2,
        'DATA_TYPE': 5,
        'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        

        '''HERE WE CALL THE TAUDEM FUNCTION TO CREATE A FLOWACC RASTER'''
        
                ###script to get script's directory and create a temporary folder'
        

        dir = QgsProject.instance().readPath("./") + '/'
        
        temp_dir = tempfile.mkdtemp(dir=dir)

        output_file_name = 'TDFlowAccumulation.tif'
        output_flow_accumulation = os.path.join(temp_dir, output_file_name)
        
        mpiexec="C:\\Program Files\\Microsoft MPI\\Bin\\mpiexec.exe"
        AreaD8="C:\\Program Files\\TauDEM\\TauDEM5Exe\\AreaD8.exe"
        num_cores = multiprocessing.cpu_count()
        
        env = os.environ.copy()
        env["GDAL_DATA"] = "C:\\Program Files\\GDAL\\gdal-data"
        env["PATH"] = (
            "C:\\GDAL"
            + os.pathsep
            + "C:\\Program Files\\GDAL"
            + os.pathsep
            + "C:\\Program Files\\TauDEM\\TauDEM5Exe"
        )

        subprocess.run([mpiexec,"-n", str(num_cores),AreaD8,"-p", reclassified,"-ad8",output_flow_accumulation],shell=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    
    
    
        '''HERE WE CALL THE TAUDEM FUNCTION TO CREATE A STREAM NET '''
        
        
        StreamNet="C:\\Program Files\\TauDEM\\TauDEM5Exe\\StreamNet.exe"
        
        order=os.path.join(temp_dir, 'TDStreamOrder.tif')
        tree=os.path.join(temp_dir, 'TDNetworkTree.txt')
        coord=os.path.join(temp_dir, 'TDNeworkCoord.txt')
        net=os.path.join(temp_dir, 'TDStreamReach.shp')
        w=os.path.join(temp_dir, 'TDWatersheds.tif')
        

        subprocess.run([mpiexec,"-n", str(num_cores),StreamNet,
        "-fel", dem_fill.source(), 
        "-p", reclassified, 
        "-ad8", output_flow_accumulation,
        "-src", rasterized_lines,
        "-ord", order,
        "-tree", tree,
        "-coord", coord,
        "-net", net,
        "-w", w],shell=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)


        #Adds stream reach to the map canvas and assigns a raster file to catchment raster
            #few lines below to create a new temporary vector 
        
        
        reach_layer = QgsVectorLayer(net, "Reach", "ogr")

        feats = [ feat for feat in reach_layer.getFeatures() ]
        
        crs = flow_network.crs()
        
        temp = QgsVectorLayer("LineString?crs="+crs.toWkt(), "result", "memory")
        temp_data = temp.dataProvider()
        attr = reach_layer.dataProvider().fields().toList()
        temp_data.addAttributes(attr)
        temp.updateFields()
        temp_data.addFeatures(feats)
        QgsProject.instance().addMapLayer(temp)
        
        # Adds memory layer with all copied attributes to ToC
        temp.selectAll()
        duplicate=processing.run("native:saveselectedfeatures", {'INPUT': temp, 'OUTPUT': out_stream_reach}, context=context, feedback=feedback)['OUTPUT']
        temp.removeSelection()

        QgsProject.instance().removeMapLayer(temp.id())
        del reach_layer
        
        
        
        #Creates copy of the raster

        temp_raster = QgsProcessingUtils.generateTempFilename('temp_raster.tif')
        
        temp_output_dir = os.path.dirname(temp_raster)

        print("Directory of temp_output:", temp_output_dir)
        
        
        # Copy the original raster to the temporary directory
        shutil.copy(w, temp_raster)       


        rlayer = QgsRasterLayer(temp_raster, "CatchmentsRaster")
        if not rlayer.isValid():
            print("Raster Layer failed to load!")
            
        QgsProject.instance().addMapLayer(rlayer)

        vector_catchments=processing.run("gdal:polygonize", {
        'INPUT':rlayer, 
        'BAND': 1,
        'FIELD':"Value",
        'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        
        fixed_geometry=processing.run("native:fixgeometries", {
        'INPUT':vector_catchments, 
        'METHOD': 1,
        'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        
        dissolved=processing.run("native:dissolve", {
        'INPUT':fixed_geometry, 
        'FIELD': ['Value'],
        'OUTPUT': out_catchments}, context=context, feedback=feedback)['OUTPUT']

        #deleting files
        
        # QgsProject.instance().removeMapLayer(new_layer.id())
        
        QgsProject.instance().removeMapLayer(rlayer.id())
        del rlayer

        shutil.rmtree(temp_dir)

        # Return results
        return {
            'OutStreamReach': out_stream_reach, 
            'OutCatchments': out_catchments,
        }
        




