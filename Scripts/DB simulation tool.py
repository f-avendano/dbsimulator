import processing
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
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
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterVectorDestination)
from datetime import datetime
from qgis.utils import iface
import math


class DBs(QgsProcessingAlgorithm):



    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'DBs'

    def displayName(self):
        return 'Detainment bunds simulation tool'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return DBs()

    def shortHelpString(self):
        return self.tr('''This algorithm identifies potential places for detainment bunds (also known as WASCOBs).
        
        Outputs include a line vector where potential detainment bunds could be built and a points vector where DBs were initially assessed to be placed.
    
    
    Please be patient, since this proces might take some time and computer resources.

    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---    
    ''')


    def initAlgorithm(self, config=None):
        
        self.addParameter(QgsProcessingParameterVectorLayer('FB', 'Fields boundaries'))
        self.addParameter(QgsProcessingParameterRasterLayer('UnfilledDEM', 'Unfilled DEM'))
        self.addParameter(QgsProcessingParameterRasterLayer('FlowAcc', 'Flow accumulation raster'))
        self.addParameter(QgsProcessingParameterVectorLayer('Flowpaths', 'Flow pathways from "Visualize flow pathways step"', types=[QgsProcessing.TypeVectorLine]))
        
        self.addParameter(QgsProcessingParameterBoolean('Checkbox','''
    Do flow lines come from previous step 'identifying flow pathways (detailed)'?
        ''', defaultValue=True))

        self.addParameter(QgsProcessingParameterVectorLayer('StreamReach', 'Stream reach or vector with perennial streams', types=[QgsProcessing.TypeVectorLine])) #or order
        self.addParameter(QgsProcessingParameterVectorLayer('CatchmentBoundary', 'Catchment boundary'))
        self.addParameter(QgsProcessingParameterNumber('Spacing', 'Point spacing (m) to simulate detainment bunds', QgsProcessingParameterNumber.Integer, defaultValue=60))
        self.addParameter(QgsProcessingParameterNumber('Height', 'Detainment bund height (m)', QgsProcessingParameterNumber.Integer, defaultValue=3))
        self.addParameter(QgsProcessingParameterNumber('Length', 'Detainment bund length (m)', QgsProcessingParameterNumber.Integer, defaultValue=20))
        
        self.addParameter(QgsProcessingParameterBoolean('Checkbox2','''
    Eliminate DBs that are too incised (> twice the height of DB)?
        ''', defaultValue=False))
        
        self.addParameter(QgsProcessingParameterNumber('Z', 'Z factor', QgsProcessingParameterNumber.Double, defaultValue=1))
        self.addParameter(QgsProcessingParameterVectorDestination('PotentialDB', 'Potential DB'))
        self.addParameter(QgsProcessingParameterVectorDestination('OutPoints','All DB simulated points', optional=True, createByDefault=False))


    def processAlgorithm(self, parameters, context, feedback):
        
        
        fb=self.parameterAsVectorLayer(parameters, 'FB', context)
        dem = self.parameterAsRasterLayer(parameters, 'UnfilledDEM', context)
        flowacc = self.parameterAsRasterLayer(parameters, 'FlowAcc', context)
        flow_network = self.parameterAsVectorLayer(parameters, 'Flowpaths', context)
        stream_reach = self.parameterAsVectorLayer(parameters, 'StreamReach', context)
        catchment = self.parameterAsVectorLayer(parameters, 'CatchmentBoundary', context)
        spacing=self.parameterAsDouble(parameters,'Spacing', context)
        height=self.parameterAsDouble(parameters,'Height', context)
        length=self.parameterAsDouble(parameters,'Length', context)
        z_factor=self.parameterAsDouble(parameters,'Z', context)
        out_db = self.parameterAsOutputLayer(parameters, 'PotentialDB', context)
        points = self.parameterAsOutputLayer(parameters, 'OutPoints', context)
        visualize_preprocess = self.parameterAsBool(parameters,'Checkbox', context)
        tooincised=self.parameterAsBool(parameters,'Checkbox2', context)

        
        ###CREATING STREAMS >=2 HA AND <=50 HA
        feedback.pushInfo('''
        
        ---------Extracting streams >=2 ha and <= 50 ha, formatting and clipping -------------------
        
        ''')
        #Conversion from squared metres to hectares
        
        pixels=flowacc.rasterUnitsPerPixelX()
        expression = f'(({flowacc.name()}@1*{pixels})/10000)'

        flowacc_ha= processing.run("qgis:rastercalculator", {
            'EXPRESSION': expression,
            'LAYERS': flowacc,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)["OUTPUT"]
        
        
        
        #Selecting stream >= 2 hectares and <= 50 hectares, vectorising and clipping to wsh boundary
        
        expression = f'((({flowacc_ha}@1>=2)AND({flowacc_ha}@1<=50))*1)'
        
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
            'output':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['output']
        
        
        #Clip network by catchment boundary 
        
        clipped= processing.run(
            "native:clip",{
            'INPUT': vector,
            'OVERLAY': catchment,
            'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
        
        
        #Create shp with only isAG>=1
        
        isAG1= processing.run(
            "native:extractbyattribute",{
            'INPUT': fb,
            'FIELD': "isAG",
            'OPERATOR':3,
            'VALUE':1,
            'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
        
        #Clip network by isAG
        
        clipped2= processing.run(
            "native:clip",{
            'INPUT': clipped,
            'OVERLAY': isAG1,
            'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
        
        
        ###Here we need to extract these lines from the 'flow_network' vector, because the direction (azimuth) is different and this affects 
            ### the results of our Detainment Bunds (place in the stream). BOTH VECTORS MUST COME FROM THE SAME FLOW ACC RASTER
        
        
        if visualize_preprocess is True: 
        
                    
            difference= processing.run(
                "native:difference",{
                'INPUT': clipped2,
                'OVERLAY': flow_network,
                'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
            
            intersection= processing.run(
                "native:multiintersection",{
                'INPUT': flow_network,
                'OVERLAYS': clipped2,
                'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
            
            merged = processing.run("native:mergevectorlayers", {
                'LAYERS': [difference, intersection], 
                'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
            
            
            dissolved2= processing.run(
                "native:dissolve",{
                'INPUT': merged,
                'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
        
        
          ###Work here: will do a conditional if flow lines came from a different tool than this set, or the same
            
        else: 
            extracted=processing.run(       ###WE USE THIS FOR WHEN THE FLOW LINES ARE DIFFERENT
                "native:extractwithindistance",{
                'INPUT': flow_network,
                'REFERENCE': clipped2,
                'DISTANCE':2,
                'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
                 
            dissolved2= processing.run(
                "native:dissolve",{
                'INPUT': extracted,
                'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']       
        
        
        ###WE USE THE FOLLOWING 3 WHEN THE FLOWLINES ARE THE SAME (DERIVED FROM R.STREAM.EXTRACT AND VISUALISE FLOWLINES)
        

            
        split2= processing.run(
            "native:splitwithlines",{
            'INPUT': dissolved2,
            'LINES': dissolved2,
            'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']        
        
        
        '''Now we calculate the direction of each line'''

  
        ID_field=processing.run("native:fieldcalculator", {
            'INPUT':split2, 
            'FIELD_NAME': "LINKNO",
            'FIELD_TYPE': 1, 
            'FORMULA':"@id",
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
        
        temp_out_path = QgsProcessingUtils.generateTempFilename("temp_out.shp")       
        
        dir = QgsProcessingUtils.generateTempFilename('dir.shp')
        
        Direction_CompassA=processing.run("native:fieldcalculator", {       ###Apparently we'll need to store this in a temporary shapefile. Works with out_db
            'INPUT':ID_field, 
            'FIELD_NAME': "Azimuth",
            'FORMULA':"azimuth(start_point($geometry), end_point($geometry)) * (180/pi())", #* (180/pi()) is to convert from radians to degrees
            'OUTPUT': dir}, context=context, feedback=feedback)['OUTPUT']


        diss = QgsProcessingUtils.generateTempFilename('diss.shp')
        
        dissolved4_path= processing.run(
            "native:dissolve",{
            'INPUT': Direction_CompassA,
            'OUTPUT':diss},context=context,feedback=feedback)['OUTPUT']


        dissolved4 = QgsVectorLayer(dissolved4_path, "Dissolved Layer", "ogr")


        feedback.pushInfo(f'--------- Creating points every {spacing} m apart in ephemeral/intermittent streams -----------------------------')

        ###THIS FUCTION CALCULATES DISTANCE BETWEEN TWO LINE FEATURE'S VERTEX AND CREATES POINTS SPACED AT 60 m


        # Create a memory layer for output points
        out_layer = QgsVectorLayer('Point?crs={}'.format(flow_network.crs().authid()), 'output_points', 'memory')
        pr = out_layer.dataProvider()

        statn_pts_spacing = spacing

        for feature in dissolved4.getFeatures():
            geom = feature.geometry()
            if geom.isMultipart():
                parts = geom.asMultiPolyline()
            else:
                parts = [geom.asPolyline()]

            for part in parts:
                if len(part) == 0:
                    continue

                # Add a point at the start of the feature
                prev_point = part[0]
                out_feature = QgsFeature()
                out_feature.setGeometry(QgsGeometry.fromPointXY(prev_point))
                pr.addFeatures([out_feature])
                
                distance_accumulated = 0.0

                for i in range(1, len(part)):
                    current_point = part[i]
                    segment_length = current_point.distance(prev_point)
                    distance_accumulated += segment_length

                    while distance_accumulated >= statn_pts_spacing:
                        ratio = (statn_pts_spacing - (distance_accumulated - segment_length)) / segment_length
                        new_x = prev_point.x() + ratio * (current_point.x() - prev_point.x())
                        new_y = prev_point.y() + ratio * (current_point.y() - prev_point.y())
                        new_point = QgsPointXY(new_x, new_y)
                        
                        out_feature = QgsFeature()
                        out_feature.setGeometry(QgsGeometry.fromPointXY(new_point))
                        pr.addFeatures([out_feature])

                        distance_accumulated -= statn_pts_spacing
                        prev_point = QgsPoint(new_x, new_y)

                    prev_point = current_point

        # Update fields in the out_layer
        out_layer.updateFields()

        # Save the memory layer to the specified output
        temp_path = points + "_temp.shp"
        transform_context = QgsProject.instance().transformContext()
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "ESRI Shapefile"
        save_options.fileEncoding = "UTF-8"

        # If exporting only points, replace the temp shp for "points"
        QgsVectorFileWriter.writeAsVectorFormatV3(out_layer, temp_path, transform_context, save_options)
        
            
            
        ###CREATION OF TRANSECTS AND DETAINMENT BUNDS
        
        # Conversion of height to same units as DEM and creatinf an ID field
        
        DB_height= height/z_factor
        
        
        ID = processing.run("native:fieldcalculator", { 
            'INPUT': temp_path,
            'FIELD_NAME': "DB_ID",
            'FIELD_TYPE': 1, 
            'FORMULA': "@id",
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']

        
        #Streams to raster
        
        rasterised_streams=processing.run('gdal:rasterize',{
            'INPUT': Direction_CompassA,
            'FIELD': 'LINKNO',
            'UNITS': 1,
            'WIDTH': 1.0,
            'HEIGHT': 1.0,
            'NODATA': 0,
            'EXTENT': flow_network,
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=feedback)['OUTPUT']
            
            #QGIS cannot do zonal statistics with point or line features, so we have to convert to polygon using buffer
        
        buffered_points = processing.run("native:buffer", {
            'INPUT': ID,
            'DISTANCE': 0.5,
            'SEGMENTS': 1,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback) ['OUTPUT']
                
        mean_CA = processing.run("native:zonalstatisticsfb", {
            'INPUT': buffered_points,
            'INPUT_RASTER': flowacc_ha,
            'RASTER_BAND': 1,
            'COLUMN_PREFIX': "_",
            'STATISTICS': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT'  
            }, context=context, feedback=feedback)['OUTPUT']
        
        mean_elev = processing.run("native:zonalstatisticsfb", {
            'INPUT': mean_CA,
            'INPUT_RASTER': dem,
            'RASTER_BAND': 1,
            'COLUMN_PREFIX': "_1",
            'STATISTICS': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT' 
            }, context=context, feedback=feedback)['OUTPUT']
            
        mean_reach = processing.run("native:zonalstatisticsfb", {
            'INPUT': mean_elev,
            'INPUT_RASTER': rasterised_streams,
            'RASTER_BAND': 1,
            'COLUMN_PREFIX': "_2",
            'STATISTICS': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT' 
            }, context=context, feedback=feedback)['OUTPUT']        
        


        joined=processing.run("native:joinattributestable", { 
            'INPUT': ID,
            'FIELD': 'DB_ID',
            'INPUT_2': mean_reach,
            'FIELD_2': 'DB_ID',
            'FIELDS_TO_COPY': ['_mean', '_1mean','_2mean'],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']
        
        
        expression = f'( ("_2mean" IS NOT NULL) AND  ("_mean" >2) AND ("_mean" <50) AND ("_mean" IS NOT NULL))'
        
        selected=processing.run("native:extractbyexpression", {
            'INPUT': joined,
            'EXPRESSION': expression,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']
        
        reach_added = processing.run("native:fieldcalculator", {
            'INPUT': selected,
            'FIELD_NAME': "Reach",
            'FIELD_TYPE': 1, 
            'FORMULA': "_2mean",
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']        
        

        

        ###RENAME
      
        # Open editing session
        reach_added.startEditing()

        # Rename field
        idx = reach_added.fields().indexFromName('_mean')
        if idx != -1:
            reach_added.renameAttribute(idx, 'Contr_area')
        
        # Rename field
        idx = reach_added.fields().indexFromName('_1mean')
        if idx != -1:
            reach_added.renameAttribute(idx, 'Elevation')

        #Delete _2mean field
        idx = reach_added.fields().indexFromName('_2mean')
        if idx != -1:
            reach_added.deleteAttribute(idx)
            
            
        # Close editing session and save changes
        reach_added.commitChanges()

        # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(reach_added, points, 'utf-8', selected.crs(), 'ESRI Shapefile')
        
        
        
        
        #Sort by catchment area
        
        sorted=processing.run("native:orderbyexpression", {   ###Leave this as temporary output, points export anyways if return:sorted
            'INPUT': reach_added,
            'EXPRESSION': "Contr_area",
            'ASCENDING' : True,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']        
        
        
        
        #Creating reach ID field and append each unique "LINKNO" to ReachList as a string
        
        ReachList = []
        for feature in sorted.getFeatures():
            reach_id = feature['Reach']
            if reach_id not in ReachList:
                ReachList.append(reach_id)
                
        
        # # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(sorted, points, 'utf-8', selected.crs(), 'ESRI Shapefile')        
        
        
        # Delete points where elevation drop is insufficient
        feedback.pushInfo('''
        
        ----------- Deleting points with an elevation drop between itself and the next upstream point less than the DB impoundment height -------------------
        
        ''')

        for Reach in ReachList:
            UpElev = float('inf')
            
            sorted.startEditing()
            for feature in sorted.getFeatures():
                if feature['Reach'] != Reach:
                    continue
                CurrentElev = feature['Elevation'] + height
                if CurrentElev < UpElev:
                    UpElev = feature['Elevation']
                else:
                    sorted.deleteFeature(feature.id())
            sorted.commitChanges()

        # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(sorted, points, 'utf-8', selected.crs(), 'ESRI Shapefile')
        
        
        #Add and populate "Height" field
        
        
        height_field = processing.run("native:fieldcalculator", {
            'INPUT': sorted,
            'FIELD_NAME': "Height (m)",
            'FIELD_TYPE': 1, 
            'FORMULA': f'{height}',
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']        
        
        
        Compass_A_points=processing.run("native:joinattributestable", {
            'INPUT': height_field,
            'FIELD': 'Reach',
            'INPUT_2': Direction_CompassA,
            'FIELD_2': 'LINKNO',
            'FIELDS_TO_COPY': ['Azimuth'],
            'METHOD': 0,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']        
        
        
        L_perp = processing.run("native:fieldcalculator", {
            'INPUT': Compass_A_points,
            'FIELD_NAME': "L_perp",
            'FIELD_TYPE': 0, 
            'FORMULA': "((360-Azimuth))",
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
        
        R_perp = processing.run("native:fieldcalculator", {
            'INPUT': L_perp,
            'FIELD_NAME': "R_perp",
            'FIELD_TYPE': 0, 
            'FORMULA': "(360-Azimuth)+180",
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
        
        
      # Create output layers for left and right lines
        loffset_layer = QgsVectorLayer('LineString?crs=', 'loffset', 'memory')
        roffset_layer = QgsVectorLayer('LineString?crs=', 'roffset', 'memory')
        loffset_provider = loffset_layer.dataProvider()
        roffset_provider = roffset_layer.dataProvider()
        
        loffset_provider.addAttributes([QgsField("DB_ID", QVariant.Int)])
        roffset_provider.addAttributes([QgsField("DB_ID", QVariant.Int)])
        loffset_layer.updateFields()
        roffset_layer.updateFields()

        # Create lines based on the angles
        def create_perpendicular_line(point, distance, angle):
            angle_rad = math.radians(angle)
            dx = distance * math.cos(angle_rad)
            dy = distance * math.sin(angle_rad)
            end_point = QgsPointXY(point.x() + dx, point.y() + dy)
            return QgsGeometry.fromPolylineXY([point, end_point])


        for feature in R_perp.getFeatures():
            geom = feature.geometry()
            point = geom.asPoint()
            l_angle = feature['L_perp']
            r_angle = feature['R_perp']
            
            # Left line
            l_line = create_perpendicular_line(point, (length / 2), l_angle)
            l_feature = QgsFeature()
            l_feature.setGeometry(l_line)
            l_feature.setAttributes([feature['DB_ID']])
            loffset_provider.addFeature(l_feature)

            # Right line
            r_line = create_perpendicular_line(point, (length / 2), r_angle)
            r_feature = QgsFeature()
            r_feature.setGeometry(r_line)
            r_feature.setAttributes([feature['DB_ID']])
            roffset_provider.addFeature(r_feature)

        loffset_layer.updateExtents()
        roffset_layer.updateExtents()


        buffered_left = processing.run("native:buffer", {
            'INPUT': loffset_layer,
            'DISTANCE': 0.7,
            'SEGMENTS': 1,
            'END_CAP_STYLE': 2,
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback) ['OUTPUT']

        buffered_right = processing.run("native:buffer", {
            'INPUT': roffset_layer,
            'DISTANCE': 0.7,
            'SEGMENTS': 1,
            'END_CAP_STYLE': 2,            
            'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback) ['OUTPUT']


        range_left = processing.run("native:zonalstatisticsfb", {
            'INPUT': buffered_left,
            'INPUT_RASTER': dem,
            'BAND': 1,
            'COLUMN_PREFIX': "left_",
            'STATISTICS': 7,
            'OUTPUT': 'TEMPORARY_OUTPUT'  
            }, context=context, feedback=feedback)['OUTPUT']
        
        range_right = processing.run("native:zonalstatisticsfb", {
            'INPUT': buffered_right,
            'INPUT_RASTER': dem,
            'BAND': 1,
            'COLUMN_PREFIX': "right_",
            'STATISTICS': 7,
            'OUTPUT': 'TEMPORARY_OUTPUT'  
            }, context=context, feedback=feedback)['OUTPUT']
            
        # Merge the left and right lines
        merged = processing.run("native:mergevectorlayers", {
            'LAYERS': [loffset_layer, roffset_layer], 
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']
        
        dissolved= processing.run(
            "native:dissolve",{
            'INPUT': merged,
            'FIELD': 'DB_ID',
            'OUTPUT':'TEMPORARY_OUTPUT'},context=context,feedback=feedback)['OUTPUT']
            
            
        joined=processing.run("native:joinattributestable", {
            'INPUT': dissolved,
            'FIELD': 'DB_ID',
            'INPUT_2': Compass_A_points,
            'FIELD_2': 'DB_ID',
            'FIELDS_TO_COPY': ['Contr_area', 'Elevation','Height (m)'],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']        
        
        
        joined_range_l=processing.run("native:joinattributestable", {
            'INPUT': joined,
            'FIELD': 'DB_ID',
            'INPUT_2': range_left,
            'FIELD_2': 'DB_ID',
            'FIELDS_TO_COPY': ['left_range'],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']                
        
        
        joined2=processing.run("native:joinattributestable", {
            'INPUT': joined_range_l,
            'FIELD': 'DB_ID',
            'INPUT_2': range_right,
            'FIELD_2': 'DB_ID',
            'FIELDS_TO_COPY': ['right_range'],
            'METHOD': 1,
            'DISCARD_NONMATCHING': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']                
        
        DB_height= height/z_factor
        
        if tooincised is True:
        
            TooIncised = DB_height*2 
        
            expression = f'( ("left_range" > "Height (m)") AND  ("right_range" > "Height (m)") AND ("left_range"<{TooIncised}) AND ("right_range"<{TooIncised}))'
        

        
            selected2=processing.run("native:extractbyexpression", {
                'INPUT': joined2,
                'EXPRESSION': expression,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)['OUTPUT']
        
        else:
            selected2=joined2
        
        #Ensure selected2 is a QgsVectorLayer
        if not isinstance(selected2, QgsVectorLayer):
            raise Exception("The output of extractbyexpression is not a QgsVectorLayer.")

        # Create a spatial index for the selected layer
        index = QgsSpatialIndex(selected2.getFeatures())

        # To track processed features
        processed_features = set()

        # Start an edit session
        selected2.startEditing()

        # Loop through each feature in the layer
        for feature in selected2.getFeatures():
            DB_ID = feature['DB_ID']

            # If the feature has been processed, skip it
            if DB_ID in processed_features:
                continue

            # Find intersecting features using the spatial index
            intersecting_ids = index.intersects(feature.geometry().boundingBox())
            intersecting_features = [f for f in selected2.getFeatures(QgsFeatureRequest().setFilterFids(intersecting_ids)) if f.geometry().intersects(feature.geometry())]

            # If more than one intersecting feature, process them
            while len(intersecting_features) > 1:
                # Find the feature with the smallest contributing area
                smallest_feature = min(intersecting_features, key=lambda f: f['Contr_area'])
                
                # Delete the feature with the smallest contributing area
                selected2.deleteFeature(smallest_feature.id())
                
                # Update the processed feature list
                processed_features.add(smallest_feature['DB_ID'])

                # Rebuild the list of intersecting features
                intersecting_ids = index.intersects(feature.geometry().boundingBox())
                intersecting_features = [f for f in selected2.getFeatures(QgsFeatureRequest().setFilterFids(intersecting_ids)) if f.geometry().intersects(feature.geometry())]

        # Commit changes
        selected2.commitChanges()

        
        temp = QgsProcessingUtils.generateTempFilename('temp.shp')
        
        # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(selected2, out_db, 'utf-8', flow_network.crs(), 'ESRI Shapefile')

        
        FB_lines=processing.run("native:polygonstolines", {
            'INPUT': isAG1,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']


        select_within_distance=processing.run("native:selectwithindistance", {
            'INPUT': selected2,
            'REFERENCE': stream_reach,
            'DISTANCE': 25,
            'METHOD': 0,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        
        # Remove selected features from line_layer_1
        select_within_distance.startEditing()
        for feature in select_within_distance.getSelectedFeatures():
            select_within_distance.deleteFeature(feature.id())
        select_within_distance.commitChanges()
        
        # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(select_within_distance, out_db, 'utf-8', flow_network.crs(), 'ESRI Shapefile')
        
        select_intersect=processing.run("native:selectbylocation", {
            'INPUT': select_within_distance,
            'PREDICATE': [0],
            'INTERSECT': FB_lines,
            'METHOD': 0,
            'OUTPUT':out_db
        }, context=context, feedback=feedback)['OUTPUT']        

        select_intersect.startEditing()
        for feature in select_intersect.getSelectedFeatures():
            select_intersect.deleteFeature(feature.id())
        select_intersect.commitChanges()
        
        # Save the renamed layer to the final output
        QgsVectorFileWriter.writeAsVectorFormat(select_intersect, out_db, 'utf-8', flow_network.crs(), 'ESRI Shapefile')

        return {'PotentialDB': select_intersect,'OutPoints': sorted}
