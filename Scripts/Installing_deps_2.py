import os
import shutil
import tempfile
import processing
from qgis.PyQt.QtCore import QCoreApplication
from processing.core.ProcessingConfig import ProcessingConfig
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterString,
                       QgsApplication)

def has_write_permission(directory):
    """Check if the directory has write permission."""
    return os.access(directory, os.W_OK)

class InstallDepProcessingAlgorithm(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'Installing_deps_2'

    def displayName(self):
        return '0b) Installing dependencies (no admin rights)'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return InstallDepProcessingAlgorithm()
    
    def shortHelpString(self):
        return self.tr('''This algorithm installs addons "r.stream.order" and "r.stream.basins" from GRASS GIS.
    
    --- Developed and adapted on July 2024 by Fernando Avendaño Veas (Massey University) using ArcPy scripts from the ACPF project (USDA) ---
    ''')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterString(
                'DUMMY',
                'This is a dummy parameter and will not be used',
                optional=True
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo("Starting the installation process...")

        with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt') as temp_file:
            temp_filename = temp_file.name

        try:
            extensions = processing.run(
                "grass7:g.extension.list", {
                    '-a': True,
                    'html': temp_filename
                }, context=context, feedback=feedback)['html']

            feedback.pushInfo("Checked installed GRASS extensions.")

            with open(temp_filename, 'r') as file:
                extensions_content = file.read()

            if 'r.stream.order' in extensions_content:
                feedback.pushInfo("Extension 'r.stream.order' is installed.")
            else:
                feedback.pushInfo("Installing 'r.stream.order'...")
                processing.run(
                    "grass7:g.extension.manage", {
                        'extension': 'r.stream.order',
                        'operation': 0
                    }, context=context, feedback=feedback)
                feedback.pushInfo("Extension 'r.stream.order' has been installed.")

            if 'r.stream.basins' in extensions_content:
                feedback.pushInfo("Extension 'r.stream.basins' is installed.")
            else:
                feedback.pushInfo("Installing 'r.stream.basins'...")
                processing.run(
                    "grass7:g.extension.manage", {
                        'extension': 'r.stream.basins',
                        'operation': 0
                    }, context=context, feedback=feedback)
                feedback.pushInfo("Extension 'r.stream.basins' has been installed.")

            scripts_path = ProcessingConfig.getSetting('SCRIPTS_FOLDERS')
            parent_dir = os.path.dirname(scripts_path)
            description_dir = os.path.join(parent_dir, 'GRASS descriptions')

            r_order_txt = 'r.stream.order.txt'
            r_basins_txt = 'r.stream.basins.txt'

            r_order_file_path = os.path.join(description_dir, r_order_txt)
            r_basins_file_path = os.path.join(description_dir, r_basins_txt)

            grass_provider = QgsApplication.processingRegistry().providerById('grass7')

            if grass_provider:
                feedback.pushInfo("GRASS Provider is available.")
                if hasattr(grass_provider, 'descriptionFolders'):
                    description_folders = grass_provider.descriptionFolders

                    for folder in description_folders:
                        feedback.pushInfo(f"Checking write permissions for folder: {folder}")
                        
                        if has_write_permission(folder):
                            feedback.pushInfo(f"Write permission granted for folder: {folder}")

                            prefix_path = folder
                            destination_r_order_desc = os.path.join(prefix_path, r_order_txt)
                            destination_r_basins_desc = os.path.join(prefix_path, r_basins_txt)

                            if os.path.exists(prefix_path):
                                try:
                                    shutil.copy2(r_order_file_path, destination_r_order_desc)
                                    feedback.pushInfo(f"File {r_order_txt} copied successfully to {destination_r_order_desc}")
                                    shutil.copy2(r_basins_file_path, destination_r_basins_desc)
                                    feedback.pushInfo(f"File {r_basins_txt} copied successfully to {destination_r_basins_desc}")

                                except FileNotFoundError:
                                    feedback.pushInfo(f"File {r_order_txt} not found in {r_order_file_path}")
                                    feedback.pushInfo(f"File {r_basins_txt} not found in {r_basins_file_path}")

                                except Exception as e:
                                    feedback.pushInfo(f"Error copying file: {e}")
                        else:
                            feedback.pushInfo(f"No write permission for folder: {folder}")

            else:
                feedback.pushInfo("GRASS provider is not available.")

        except Exception as e:
            feedback.pushInfo(f"Error encountered: {e}")
        
        feedback.pushInfo("Installation process completed.")
        return {}