import os
import shutil
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
                       QgsProcessingParameterString,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext)



class DeleteTempsProcessingAlgorithm(QgsProcessingAlgorithm):

    
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'delete_temps'

    def displayName(self):
        return 'Delete Temporary Files'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return DeleteTempsProcessingAlgorithm()
    
    def shortHelpString(self):
        return self.tr('''This algorithm deletes temporary files stored by QGIS during the processing. MAKE SURE TO HAVE NO TEMPORARY FILES IN YOUR PROJECT FOR THIS TO WORK
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---
    ''')

    def initAlgorithm(self, config=None):
        # Add a dummy parameter just to show the UI
        self.addParameter(
            QgsProcessingParameterString(
                'DUMMY',
                'This is a dummy parameter and will not be used',
                optional=True
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Get the path to the system's temporary directory
        temp_dir = tempfile.gettempdir()

        # Define the prefix for the folders to delete
        folder_prefix = "processing_"

        # Iterate through the files and directories in the temporary directory
        for folder_name in os.listdir(temp_dir):
            # Check if the folder name starts with the prefix
            if folder_name.startswith(folder_prefix):
                folder_path = os.path.join(temp_dir, folder_name)
                # Check if the path is a directory
                if os.path.isdir(folder_path):
                    try:
                        # Delete the directory and its contents
                        shutil.rmtree(folder_path)
                        feedback.pushInfo(f"Deleted folder: {folder_path}")
                    except Exception as e:
                        feedback.pushInfo(f"Failed to delete folder: {folder_path}, error: {e}")
                        
        # Return an empty dictionary
        return {}
# # Create an instance of the algorithm
# alg = DeleteTempsProcessingAlgorithm()
# QgsApplication.processingRegistry().addAlgorithm(alg)