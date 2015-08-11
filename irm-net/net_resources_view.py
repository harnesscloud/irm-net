#!/usr/bin/env python

from hresman import utils
from hresman.utils import json_request, json_reply, json_error
from hresman.resources_view import ResourcesView
import net_managers_view 
import copy
from hresman.utils import get, post
import net_managers_view

class NETResourcesView(ResourcesView):    
    AllocSpec = None
    ManagersTypes = None
    
    def _get_resources(self):       
       resources = { }

       if net_managers_view.NETManagersView.net_operational():
          for r in NETResourcesView.resources:
             resources.update(NETResourcesView.resources[r])
       
          return { "Resources": resources }
       else:
          net_managers_view.NETManagersView.disconnect_crs()
          raise Exception("Either IRM-NOVA or IRM-NEUTRON not registered!")
       
    ################################  get allocation specification ##############  
    def _get_alloc_spec(self):

        net_managers_view.NETManagersView.expect_ready_manager()
         
        if NETResourcesView.AllocSpec == None:

           types = {}
           constraints = {}
           agg = {}
           metrics = {}
           
           managers = copy.deepcopy(net_managers_view.NETManagersView.managers)  
           NETResourcesView.ManagersTypes = {}      
           for id in managers:          
              ret = get("getAllocSpec", managers[id]["Port"], managers[id]["Address"])
              if "result" in ret:
                 spec = ret["result"]
                 if ("Monitor" in spec) and ("Metrics" in spec["Monitor"]):
                    metrics.update(spec["Monitor"]["Metrics"])
                 if ("Types" in spec):    
                    types.update(spec["Types"])
                 for t in spec["Types"]:
                    NETResourcesView.ManagersTypes[t] = id
                    
           NETResourcesView.AllocSpec = { "Types": types, "Constraints":  constraints, "Monitor": { "Metrics": metrics, \
                                                                           "Aggregation": agg } }      
        return NETResourcesView.AllocSpec
        
    def _calculate_capacity(self, resource, allocation, release):
        net_managers_view.NETManagersView.expect_ready_manager()
        
        spec = self._get_alloc_spec()
        
        if resource["Type"] not in spec["Types"]:
           raise Exception("Type %s not supported!" % resource["Type"])
        
        manager = net_managers_view.NETManagersView.managers[NETResourcesView.ManagersTypes[resource["Type"]]]    
        
        ret = post({"Resource": resource, "Allocation": allocation, "Release": release}, \
                   "calculateCapacity", manager["Port"], manager["Address"])
                 
        return ret                                                                              
