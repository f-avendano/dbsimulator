import os
import shutil
import tempfile
import processing
from qgis.PyQt.QtCore import QTimer
from qgis.utils import iface
from qgis.PyQt.QtCore import QCoreApplication
from processing.core.ProcessingConfig import ProcessingConfig
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterString,
                       QgsProcessingParameterNumber,
                       QgsProcessingContext,
                       QgsSettings, 
                       QgsApplication, 
                       QgsProviderRegistry,
                       QgsProcessingProvider)


class InstallDepProcessingAlgorithm(QgsProcessingAlgorithm):

    
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)
        
    def name(self):
        return 'install_dependencies'

    def displayName(self):
        return '0a) Installing dependencies (admin rights)'

    def group(self):
        return 'DB simulator'

    def groupId(self):
        return 'dbsimulator'

    def createInstance(self):
        return InstallDepProcessingAlgorithm()
    
    def shortHelpString(self):
        return self.tr('''This algorithm installs addons "r.stream.order" and "r..stream.basins" from GRASS GIS.
    
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


        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt') as temp_file:
            temp_filename = temp_file.name
            
        
        extensions = processing.run(
            "grass7:g.extension.list",{
            '-a': True,
            'html': temp_filename},context=context,feedback=feedback)['html']

        # Read the contents of the temporary file
        with open(temp_filename, 'r') as file:
            extensions_content = file.read()

        # Check if 'r.stream.order' exists in the extensions content
        if 'r.stream.order' in extensions_content:
            feedback.pushInfo("Extension 'r.stream.order' is installed.")
        else:
            feedback.pushInfo("Extension 'r.stream.order' is NOT installed.")
            
            install.stream.order = processing.run(
            "grass7:g.extension.manage",{
            'extension': 'r.stream.order',
            'operation':0},context=context,feedback=feedback)
        
            feedback.pushInfo("Extension 'r.stream.order' has been installed.")
        
        if 'r.stream.basins' in extensions_content:
            feedback.pushInfo("Extension 'r.stream.basins' is installed.")
        else:
            feedback.pushInfo("Extension 'r.stream.basins' is NOT installed.")
            
            install.stream.basins = processing.run(
            "grass7:g.extension.manage",{
            'extension': 'r.stream.basins',
            'operation':0},context=context,feedback=feedback)
        
            feedback.pushInfo("Extension 'r.stream.basins' has been installed.")        
        




        appdata_path=os.environ["APPDATA"]

        #Obtaining GRASS version:


        # Get the GRASS provider
        provider_registry = QgsProviderRegistry.instance()
        grass_provider = provider_registry.providerMetadata("grass")


        if grass_provider is not None:
            # Access description and metadata
            grass_description = grass_provider.description()

            # Remove "GRASS" and "vector provider" from the description
            parts = grass_description.split()
            if len(parts) > 1:
                version_number = parts[1]  # Assuming the version number is always the second part
            else:
                version_number = "Unknown"
        
        

        # Check for GRASS8 directory
        grass_path = os.path.join(appdata_path, f'GRASS{version_number}')
        if os.path.exists(grass_path):
            grass_lib_path = os.path.join(grass_path, 'addons', 'bin')
        
        
        #fuzzy='r.fuzzy.system.exe'
        r_order_name = 'r.stream.order.exe'
        r_basins_name = 'r.stream.basins.exe'

        r_order_file_path = os.path.join(grass_lib_path, r_order_name)
        r_basins_file_path = os.path.join(grass_lib_path, r_basins_name)
        #path=os.path.join(grass_lib_path, fuzzy)
        
        
        gisbase= os.environ["GISBASE"]
        destination_dir = os.path.join(gisbase, 'bin')

        destination_r_order_path = os.path.join(destination_dir, r_order_name)
        destination_r_basins_path = os.path.join(destination_dir, r_basins_name)
        #destination_file_path = os.path.join(destination_dir, fuzzy)        

        # Copy the file if the source exists
        if os.path.exists(destination_dir):
            try:
                shutil.copy2(r_order_file_path, destination_r_order_path)
                print(f"File {r_order_name} copied successfully to {destination_r_order_path}")
                shutil.copy2(r_basins_file_path, destination_r_basins_path)
                print(f"File {r_basins_name} copied successfully to {destination_r_basins_path}")                
                # shutil.copy2(path, destination_file_path)
                # print(f"File {fuzzy} copied successfully to {destination_file_path}")                
                
                
                
            except Exception as e:
                print(f"Error copying file: {e}")
        else:
            print(f"Directory {destination_dir} not found")




        # Retrieve the settings object
        scripts_path = ProcessingConfig.getSetting('SCRIPTS_FOLDERS')
        
        # Get the parent directory
        parent_dir = os.path.dirname(scripts_path)
        
        #Get description dir
        description_dir=os.path.join(parent_dir, 'GRASS descriptions')
        
        
        #Description names
        #fuzzy_txt='r.fuzzy.system.txt'
        r_order_txt = 'r.stream.order.txt'
        r_basins_txt = 'r.stream.basins.txt'        
        
        #Files dirs
        #fuzzy_path=os.path.join(description_dir,fuzzy_txt)
        r_order_file_path = os.path.join(description_dir,r_order_txt)
        r_basins_file_path = os.path.join(description_dir,r_basins_txt)
        
        
        
        #Retrieving GRASS modules directory
    
        prefix_path=os.environ["QGIS_PREFIX_PATH"]
        destination_dir2 = os.path.join(prefix_path, 'python', 'plugins', 'grassprovider', 'description')
        #destination_descr_path = os.path.join(destination_dir2, fuzzy_txt)
        destination_r_order_desc = os.path.join(destination_dir2, r_order_txt)
        destination_r_basins_desc = os.path.join(destination_dir2, r_basins_txt)
        
        if os.path.exists(destination_dir2):
            
        # Copy the file
            try:
                # shutil.copy2(fuzzy_path,destination_descr_path)
                # print(f"File {fuzzy_txt} copied successfully to {destination_descr_path}")
                shutil.copy2(r_order_file_path,destination_r_order_desc)
                print(f"File {r_order_txt} copied successfully to {destination_r_order_desc}")                
                shutil.copy2(r_basins_file_path,destination_r_basins_desc)
                print(f"File {r_basins_txt} copied successfully to {destination_r_basins_desc}")
                
            except FileNotFoundError:
                print(f"File {r_order_txt} not found in {r_order_file_path}")
                print(f"File {r_basins_txt} not found in {r_basins_file_path}")                
                #print(f"File {fuzzy_txt} not found in {fuzzy_path}")                
                
            except Exception as e:
                print(f"Error copying file: {e}")
                
                
 
        else: 
            print(f"Directory {destination_dir2} not found")


        return {}

    







