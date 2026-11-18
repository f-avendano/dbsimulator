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
        self.addParameter(QgsProcessingParameterNumber('Memory', 'Max. memory usage (MB)', QgsProcessingParameterNumber.Double, defaultValue=3000,))
        self.addParameter(QgsProcessingParameterRasterDestination('streams_ras', 'Streams raster'))
        self.addParameter(QgsProcessingParameterVectorDestination('FlowPaths', 'Flow pathways'))
        self.addParameter(QgsProcessingParameterRasterDestination('flowdir', 'Flow direction'))


    def processAlgorithm(self, parameters, context, feedback):

        dem = self.parameterAsRasterLayer(parameters, 'FilledDEM', context)
        areathr = self.parameterAsDouble(parameters, 'AreaThr', context)
        flowacc = self.parameterAsRasterLayer(parameters, 'FlowAcc', context)
        streams_raster = self.parameterAsOutputLayer(parameters, 'streams_ras', context)
        flowdir = self.parameterAsOutputLayer(parameters, 'flowdir', context)
        memory = self.parameterAsDouble(parameters, 'Memory', context)
        output_flowpaths = self.parameterAsOutputLayer(parameters, 'FlowPaths', context)

        # Converting from hectares to square meters
        thresh_meters = areathr * 10000
        
        # Dividing threshold in square meters by pixel size
        cell_area = dem.rasterUnitsPerPixelX() * dem.rasterUnitsPerPixelY()
        number_cells = int(thresh_meters / cell_area)




        # Get the vector result and export it to a temporary GPKG
        temp_gpkg_1 = QgsProcessingUtils.generateTempFilename('temp_streams_1.gpkg')
        
        # Run r.stream.extract
        result = processing.run("grass7:r.stream.extract", {
            'elevation': dem,
            'threshold': number_cells,
            'memory': memory,
            'GRASS GIS 7 region extent': dem,
            'GRASS_OUTPUT_TYPE_PARAMETER': 2,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_VECTOR_EXPORT_NOCAT': False,
            'stream_length': 10,
            'accumulation': None, 'd8cut': None, 'depression': None,
            'stream_vector': temp_gpkg_1,
            'stream_raster': streams_raster,
            'direction': flowdir,
            #'GRASS_VECTOR_LCO': 'format=GPKG'
        }, context=context, feedback=feedback)


        temp_gpkg_2 = QgsProcessingUtils.generateTempFilename('temp_streams_2.gpkg')
        temp_stream_vector = result['stream_vector']
        

        
        # Run r.stream.order algorithm
        temp_output = QgsProcessingUtils.generateTempFilename('strahler.tif')
        output_strahler = processing.run("grass7:r.stream.order", {
            'stream_ras': streams_raster,
            'direction': flowdir,
            'memory': memory,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'strahler': temp_output
        }, context=context, feedback=feedback)["strahler"]


        # 1) Fix geometries on the original GRASS stream vector (optional but recommended)
        temp_streams_fixed = processing.run(
            "native:fixgeometries",
            {"INPUT": temp_gpkg_1, "OUTPUT": "TEMPORARY_OUTPUT"},
            context=context, feedback=feedback
        )["OUTPUT"]

        # 2) Add a stable line ID field for aggregation
        #    Use $id (QGIS internal feature id) copied into an attribute so it survives joins.
        temp_streams_id = processing.run(
            "native:fieldcalculator",
            {
                "INPUT": temp_streams_fixed,
                "FIELD_NAME": "line_id",
                "FIELD_TYPE": 1,  # Integer
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 0,
                "FORMULA": "$id",
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]

        # 3) Create points along each line.
        #    Use DEM pixel size to set spacing. For 1 m DEM, spacing=1 or 2.
        #    For robustness, use 2 * pixel size (reduces point count, still dense enough).
        cellsize = dem.rasterUnitsPerPixelX()  # assumes square pixels; if not, you can take min(x,y)
        spacing = max(cellsize * 2.0, cellsize)  # 2 cells, but never less than 1 cell

        points_along = processing.run(
            "native:pointsalonglines",
            {
                "INPUT": temp_streams_id,
                "DISTANCE": spacing,
                "START_OFFSET": 0,
                "END_OFFSET": 0,
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]

        # 4) Sample strahler raster values at those points.
        #    The Strahler raster is output_strahler (NOT thinned).
        sampled_layer = processing.run(
            "native:rastersampling",
            {
                "INPUT": points_along,
                "RASTERCOPY": output_strahler,
                "COLUMN_PREFIX": "str_",
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]

        if not sampled_layer.isValid():
            raise QgsProcessingException("Failed to load sampled points layer")

        # Find the raster-sampled field (first field starting with "str_")
        str_field = None
        for f in sampled_layer.fields():
            if f.name().startswith("str_"):
                str_field = f.name()
                break
        if str_field is None:
            raise QgsProcessingException("Could not find sampled Strahler field (prefix 'str_')")

        # 5) Drop points with NULL / nodata sampling to avoid polluting statistics
        filtered_pts = processing.run(
            "native:extractbyexpression",
            {
                "INPUT": sampled_layer,
                "EXPRESSION": f"\"{str_field}\" IS NOT NULL",
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]

        # 6) Aggregate per line_id: take MAX of sampled Strahler
        #    This outputs a table with line_id + max(str_field)
        stats_layer = processing.run(
            "qgis:statisticsbycategories",
            {
                "INPUT": filtered_pts,
                "CATEGORIES_FIELD_NAME": ["line_id"],
                "VALUES_FIELD_NAME": str_field,
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]


        if not stats_layer.isValid():
            raise QgsProcessingException("Failed to load stats table")

        majority_field = None
        for f in stats_layer.fields():
            if f.name().lower() == "majority":
                majority_field = f.name()
                break
        if majority_field is None:
            raise QgsProcessingException("Could not find 'max' field in statistics table")

        # 7) Join stats back to stream lines by line_id
        joined_streams = processing.run(
            "native:joinattributestable",
            {
                "INPUT": temp_streams_id,
                "FIELD": "line_id",
                "INPUT_2": stats_layer,
                "FIELD_2": "line_id",
                "FIELDS_TO_COPY": [majority_field],
                "METHOD": 1,  # Take first matching record
                "DISCARD_NONMATCHING": False,
                "PREFIX": "",
                "OUTPUT": temp_gpkg_2
            },
            context=context, feedback=feedback
        )["OUTPUT"]


        # 8) Load joined result and finalise output attributes
        gpkg_layer = QgsVectorLayer(joined_streams, "temp_streams", "ogr")
        if not gpkg_layer.isValid():
            raise QgsProcessingException("Failed to load the joined streams layer")


        calc = processing.run(
            "native:fieldcalculator",
            {
                "INPUT": gpkg_layer,
                "FIELD_NAME": "Strahler",
                "FIELD_TYPE": 1,   # Integer
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 0,
                "FORMULA": f"to_int(round(\"{majority_field}\"))",
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context, feedback=feedback
        )["OUTPUT"]

        gpkg_layer = calc

        field_name = "SType"   # or "SType" if you prefer
        default_value = None
        
        # Rename max -> Strahler
        gpkg_layer.startEditing()

        idx_streamtype = gpkg_layer.fields().indexFromName(field_name)
        if idx_streamtype == -1:
            gpkg_layer.dataProvider().addAttributes([QgsField(field_name, QVariant.Int)])
            gpkg_layer.updateFields()
            idx_streamtype = gpkg_layer.fields().indexFromName(field_name)  # re-fetch index

        # Populate field
        for feat in gpkg_layer.getFeatures():
            gpkg_layer.changeAttributeValue(feat.id(), idx_streamtype, default_value)



        # # Ensure Strahler field exists; if not, create it
        # if gpkg_layer.fields().indexFromName("Strahler") == -1:
        #     gpkg_layer.dataProvider().addAttributes([QgsField("Strahler", QVariant.Int)])
        #     gpkg_layer.updateFields()

        # idx_strahler = gpkg_layer.fields().indexFromName("Strahler")
        # idx_max = gpkg_layer.fields().indexFromName(max_field)

        # # Copy max into Strahler (rounded to int)
        # for feat in gpkg_layer.getFeatures():
        #     val = feat[idx_max]
        #     if val is not None:
        #         gpkg_layer.changeAttributeValue(feat.id(), idx_strahler, int(val))

        # Optional: rename 'cat' to cat_id (avoid confusion)
        idx_cat = gpkg_layer.fields().indexFromName("cat")
        if idx_cat != -1:
            gpkg_layer.renameAttribute(idx_cat, "cat_id")

        # Clean up fields you don’t need (adjust list to your needs)
        fields_to_delete = ["label", "stream_type", "type_code", "network"]
        for field_name in fields_to_delete:
            idx = gpkg_layer.fields().indexFromName(field_name)
            if idx != -1:
                gpkg_layer.deleteAttribute(idx)

        gpkg_layer.commitChanges()

        # 9) Copy to final output as before
        processing.run(
            "sagang:copyfeatures",
            {"SHAPES": gpkg_layer, "COPY": output_flowpaths},
            context=context, feedback=feedback
        )

        return {
            'FlowPaths': output_flowpaths,
            'streams_ras': streams_raster,
            'flowdir': flowdir
        }

