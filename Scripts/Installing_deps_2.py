import os
import shutil
import tempfile
import processing
import json
from pathlib import Path
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
        return '0)a Installing dependencies'

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

            
            qgis_prefix = os.environ.get("QGIS_PREFIX_PATH", None)
            algorithms_path = os.path.join(qgis_prefix,"python", "plugins", "grassprovider", "description")
            
            description_file = os.path.join (algorithms_path, "r.stream.extract.txt")
            algo_path2=os.path.join (algorithms_path, "algorithms.json")
            
            
            if os.path.exists(description_file):





                scripts_path = ProcessingConfig.getSetting('SCRIPTS_FOLDERS')
                parent_dir = os.path.dirname(scripts_path)
                description_dir = os.path.join(parent_dir, 'GRASS descriptions')

                r_order_txt = 'r.stream.order.txt'
                r_basins_txt = 'r.stream.basins.txt'

                r_order_file_path = os.path.join(description_dir, r_order_txt)
                r_basins_file_path = os.path.join(description_dir, r_basins_txt)
                
                
                feedback.pushInfo(f"Retrieving files from folder: {r_order_file_path}")
                feedback.pushInfo(f"Retrieving files from folder: {r_basins_file_path}")

                grass_provider = QgsApplication.processingRegistry().providerById('grass7')

                if grass_provider:
                    feedback.pushInfo("GRASS Provider is available.")
                    
                    if hasattr(grass_provider, 'descriptionFolders'):
                        description_folders = grass_provider.descriptionFolders

                        for folder in description_folders:
                            feedback.pushInfo(f"Copying files to folder: {folder}")

                            destination_r_order_desc = os.path.join(folder, r_order_txt)
                            destination_r_basins_desc = os.path.join(folder, r_basins_txt)

                            if os.path.exists(r_order_file_path) and os.path.exists(r_basins_file_path):
                                try:
                                    shutil.copy2(r_order_file_path, destination_r_order_desc)
                                    feedback.pushInfo(f"File {r_order_txt} copied successfully to {destination_r_order_desc}")

                                    shutil.copy2(r_basins_file_path, destination_r_basins_desc)
                                    feedback.pushInfo(f"File {r_basins_txt} copied successfully to {destination_r_basins_desc}")

                                except FileNotFoundError:
                                    feedback.pushInfo(f"File {r_order_txt} or {r_basins_txt} not found in the project folder.")
                                except Exception as e:
                                    feedback.pushInfo(f"Error copying files: {e}")

                            else:
                                feedback.pushInfo(f"One or both description files are missing in the project folder.")
                    else:
                        feedback.pushInfo(f"ERROR: GRASS Provider does not have descriptionFolders attribute, CONTACT THE PROGRAMMER")

                else:
                    feedback.pushInfo("GRASS provider is not available.")
                    
            

            elif os.path.exists(algo_path2):
                
                # Read current JSON
                with open(algo_path2, "r") as f:
                    data = json.load(f)

                # Define new algorithms
                new_algorithms = [
                    {
                        "name": "r.stream.order",
                        "display_name": "r.stream.order",
                        "command": "r.stream.order",
                        "short_description": "Stream network order extraction",
                        "group": "Raster (r.*)",
                        "group_id": "raster",
                        "ext_path": None,
                        "hardcoded_strings": [],
                        "parameters": [
                            "QgsProcessingParameterRasterLayer|stream_ras|Streams raster (preferably from 'r.stream.extract')|None|False",
                            "QgsProcessingParameterRasterLayer|direction|Flow direction raster|None|False",
                            "*QgsProcessingParameterNumber|memory|Maximum memory to be used (in MB)|QgsProcessingParameterNumber.Integer|300|True|0|None",
                            "QgsProcessingParameterRasterDestination|strahler|strahler|None|True"
                        ]
                    },
                    {
                        "name": "r.stream.basins",
                        "display_name": "r.stream.basins",
                        "command": "r.stream.basins",
                        "short_description": "Stream basin extraction",
                        "group": "Raster (r.*)",
                        "group_id": "raster",
                        "ext_path": None,
                        "hardcoded_strings": [],
                        "parameters": [
                            "QgsProcessingParameterRasterLayer|direction|Flow direction raster|None|False",
                            "QgsProcessingParameterRasterLayer|stream_raster|Streams raster (preferably from 'r.stream.extract')|None|True",
                            "QgsProcessingParameterFeatureSource|points|Pour points layer|-1|None|True",
                            "QgsProcessingParameterNumber|memory|Maximum memory to be used (in MB)|QgsProcessingParameterNumber.Integer|300|True|0|None",
                            "QgsProcessingParameterRasterDestination|basins|Output basins raster map|None|True"
                        ]
                    }
                ]

                # Add new algorithms (avoid duplicates by checking "name")
                existing_names = [alg["name"] for alg in data]
                for alg in new_algorithms:
                    if alg["name"] not in existing_names:
                        data.append(alg)

                # Save updated JSON
                with open(algo_path2, "w") as f:
                    json.dump(data, f, indent=2)

                feedback.pushInfo("Algorithms added successfully.")
                
            else:
               feedback.pushInfo("ERROR: ALGORITHMS WERE NOT INSTALLED CORRECTLY, CONTACT THE PROGRAMMER")  

        except Exception as e:
            feedback.pushInfo(f"Error encountered: {e}")
        
        feedback.pushInfo("Installation process completed.")
        return {}
