#!/usr/bin/env python

from hresman import utils
from hresman.utils import json_request, json_reply, json_error
from hresman.resources_view import ResourcesView
import net_managers_view 
import copy
from hresman.utils import get

class NETResourcesView(ResourcesView):

    def _get_resources(self):       
       resources = { }
       for r in NETResourcesView.resources:
          resources.update(NETResourcesView.resources[r])
       
       return { "Resources": resources }
       
       
    ################################  get allocation specification ##############  
    def _get_alloc_spec(self):
        managers = copy.copy(net_managers_view.NETManagersView.managers)
        types = {}
        constraints = {}
        agg = {}
        metrics = {}
        
        for id in managers:          
           ret = get("getAllocSpec", managers[id]["Port"], managers[id]["Address"])
           if "result" in ret:
              spec = ret["result"]
              if ("Monitor" in spec) and ("Metrics" in spec["Monitor"]):
                 metrics.update(spec["Monitor"]["Metrics"])
              if ("Types" in spec):    
                 types.update(spec["Types"])
                 
        return { "Types": types, "Constraints":  constraints, "Monitor": { "Metrics": metrics, \
                                                                           "Aggregation": agg } }
                                                                           
