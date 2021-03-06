#!/usr/bin/env python

import deps
from hresman.managers_tree_view import ManagersTreeView
from threading import Timer
from net_resources_view import NETResourcesView
import hresman.utils

class NETManagersView(ManagersTreeView): 
    ChildManagers = set({})
    
    CRS_HOST = 'localhost'
    CRS_PORT = 56788    
    MANAGER_ID = None
    PORT = 7779
    
    CRS_DISABLE = False
    IGNORE_IRMS = False
    
    @staticmethod
    def net_operational():
       return NETManagersView.IGNORE_IRMS or len(NETManagersView.ChildManagers) == 2
       
    @staticmethod
    def expect_ready_manager():
       if not NETManagersView.net_operational():
          raise Exception("IRM-NOVA or IRM-NEUTRON are not available!")       
    
    @staticmethod
    def disconnect_crs():
       #print "disconnecting CRS..."
       
       if not NETManagersView.CRS_DISABLE and NETManagersView.MANAGER_ID != None:
          out=hresman.utils.delete_({} , 'unregisterManager/%s' % NETManagersView.MANAGER_ID,\
                     NETManagersView.CRS_PORT,\
                     NETManagersView.CRS_HOST)
       
    @staticmethod
    def register_crs():
       out=hresman.utils.post({"Port":NETManagersView.PORT, "Name": "IRM-NET"} , 'registerManager',\
                         NETManagersView.CRS_PORT,\
                         NETManagersView.CRS_HOST) 
       if not isinstance(out, dict) or "result" not in out:
          return False
       else:
          NETManagersView.MANAGER_ID = out["result"]["ManagerID"]
       return True   
          
    def _acceptManager(self, addr, port, name):
       
       if name == "IRM-NOVA" or name == "IRM-NEUTRON":
          NETManagersView.ChildManagers.add(name)
       else:
          return False   
       
       if not NETManagersView.CRS_DISABLE and NETManagersView.CRS_HOST != "" and \
              NETManagersView.net_operational():
          return NETManagersView.register_crs()
       return True   
      
    def _deleteManager(self, name, address, port, id):
       if name in NETManagersView.ChildManagers:
          NETManagersView.ChildManagers.remove(name)
          if not NETManagersView.IGNORE_IRMS:
             NETManagersView.disconnect_crs()
       

    def _registerManager(self, data):
       Timer(0.5, NETResourcesView().request_resources_id, args=[data["ManagerID"]]).start()
       
ManagersTreeView._class = NETManagersView
