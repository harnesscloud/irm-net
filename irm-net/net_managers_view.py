#!/usr/bin/env python

import deps
from hresman.managers_tree_view import ManagersTreeView
from threading import Timer
from net_resources_view import NETResourcesView

class NETManagersView(ManagersTreeView): 
    ChildManagers = ["IRM-NOVA", "IRM-NEUTRON"]
    
    def _acceptManager(self, addr, port, name):
       return name in NETManagersView.ChildManagers

    def _registerManager(self, data):
       Timer(0.5, NETResourcesView().request_resources_id, args=[data["ManagerID"]]).start()
       
