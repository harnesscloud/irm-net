#!/usr/bin/env python

import deps

from flask.ext.classy import FlaskView, route
from flask import request

import hresman.utils

from hresman.utils import json_request, json_reply, json_error
from hresman.reservations_view import ReservationsView
from net_managers_view import NETManagersView
from net_resources_view import NETResourcesView
import uuid
import json
from hresman.utils import post

class NETReservationsView(ReservationsView):

    # we rank each type according to the order in which we create it
    SupportedTypes = { "Machine": 2, "PublicIP": 3, "Subnet": 1 }

    ###############################################  create reservation ############ 
    def _create_reservation(self, scheduler, alloc_req, alloc_constraints, monitor):
        NETManagersView.expect_ready_manager()
        
        groups = {}
        #print "alloc_req=", json.dumps(alloc_req)
        #print "monitor=", monitor
        
        NETResourcesView()._get_alloc_spec()
        
        mantypes = NETResourcesView.ManagersTypes
         
        # first check that we can support all allocation requests
        for req in alloc_req:
           if req["Type"] not in mantypes:
              raise Exception("Do not support allocation request type: %s!" % req["Type"])
              
        # sort the allocation requests
        salloc_req = sorted(alloc_req, key=lambda x: NETReservationsView.SupportedTypes[x["Type"]])
        
        #print "salloc_req=", json.dumps(salloc_req)
        reservations=[]
        for req in salloc_req:
           manager = NETManagersView.managers[NETResourcesView.ManagersTypes[req["Type"]]] 
             
           if req["Type"] == "PublicIP" and "Attributes" in req and "VM" in req["Attributes"] and \
                  req["Attributes"]["VM"] in groups:
              req["Attributes"]["VM"] = groups[req["Attributes"]["VM"]]             
           ret = post({"Allocation": [req], "Monitor": monitor}, "createReservation", \
                      manager["Port"], manager["Address"])
           if "result" in ret and "ReservationID" in ret["result"]:
              if len(ret["result"]["ReservationID"]) == 1 and "Group" in req:
                 groups[req["Group"]] = ret["result"]["ReservationID"][0]
              reservations.extend(ret["result"]["ReservationID"])
           else:
              raise Exception("internal error: %s" % str(ret))
           
        return {"ReservationID": reservations}
  
        '''   
       schedule = CRSReservationsView._scheduler(CRSManagersView.managers, CRSResourcesView.resources, \
                                                 alloc_req, alloc_constraints, CRSResourcesView.resource_constraints) 
        
       iResIDs = []
       rollback = False
       for s in schedule:          
          addr = CRSManagersView.managers[s["manager"]]['Address']
          port = CRSManagersView.managers[s["manager"]]['Port']
          rtype = s["alloc_req"]["Type"]
          monitor_data = {}
          if rtype in monitor:
             monitor_data[rtype] = monitor[rtype]
             if "PollTime" in monitor:
                monitor_data["PollTime"] = monitor["PollTime"]
          else:
             monitor_data = {}
                
          data = { "Allocation" : [{ "Type": rtype, \
                                    "ID": s["res_id"], \
                                    "Attributes": s["alloc_req"]["Attributes"] }], \
                   
                   "Monitor": monitor_data
                 } 
          
          try:
             ret = hresman.utils.post(data, 'createReservation', port, addr)

          except Exception as e:
             print "rolling back! " + str(e)
             rollback = True
          
          if (not rollback) and "result" not in ret:
             rollback = True
          
          if rollback:
             break
          else:
             iResIDs.append({"addr": addr, "port": port, "name": CRSManagersView.managers[s["manager"]]['Name'], \
                             "iRes": ret["result"]["ReservationID"], "sched": s})
       
       if not rollback:
          resID = uuid.uuid1()
          ReservationsView.reservations[str(resID)] = iResIDs
       else:
          for iResID in iResIDs:
             data = {"ReservationID": iResID["iRes"]}
             try:                
                hresman.utils.delete_(data, 'releaseReservation', iResID["port"], iResID["addr"])
             except:
                pass  
          raise Exception("cannot make reservation! (rollbacking)")  
         
       return { "ReservationID" : [str(resID)] }                    
    '''
    ###############################################  check reservation ############   
    '''
    def _check_reservation(self, reservations):
       check_result = { "Instances": {} }
 
       for reservation in reservations:
          if reservation not in ReservationsView.reservations: 
             raise Exception("cannot find reservation: " + reservation)
          
          data = ReservationsView.reservations[reservation]
          ready = True
          addrs = []
          for alloc in data:
             ret = hresman.utils.post( { "ReservationID" : alloc["iRes"] }, "checkReservation", alloc["port"], alloc["addr"])
             if "result" not in ret:
                raise Exception("Error in checking reservation: ", str(ret))
             
             instances = ret["result"]["Instances"]
             
             for i in instances:                
                addrs.extend(instances[i]["Address"])
                ready = ready and instances[i]["Ready"].upper() == "TRUE"
          if ready:
             check_result["Instances"][reservation] = { "Ready": "True", "Address": addrs }
          else:
             check_result["Instances"][reservation] = { "Ready": "False" }      
       return check_result

    ###############################################  release reservation ############   
    def _release_reservation(self, reservations):
       print "releasing..." + str(reservations)
       for reservation in reservations:
          if reservation not in ReservationsView.reservations: 
             raise Exception("cannot find reservation: " + reservation)
          
          data = ReservationsView.reservations[reservation]
          del ReservationsView.reservations[reservation] 
          for alloc in data:
    
             ret = hresman.utils.delete_( { "ReservationID" : alloc["iRes"] }, "releaseReservation", alloc["port"], alloc["addr"])
             #if "result" not in ret:
             #   raise Exception("Error in deleting reservation: ", str(ret))
  
                
       return { }   
    '''
    ###############################################  release all reservations ############        
    def _release_all_reservations(self):
       managers = NETManagersView.managers
       for m in managers:
          hresman.utils.delete_({}, "releaseAllReservations", managers[m]['Port'], managers[m]['Address'])
       reservations = ReservationsView.reservations.keys()
       return self._release_reservation(reservations)           
                   
  

