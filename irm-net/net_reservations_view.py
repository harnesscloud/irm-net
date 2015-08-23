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
from operator import itemgetter

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
        
        # add original order, so that we do not lose it when we sort
        n = 1
        for elem in alloc_req:
           elem['pos'] = n
           n = n + 1
                
        # sort the allocation requests
        salloc_req = sorted(alloc_req, key=lambda x: NETReservationsView.SupportedTypes[x["Type"]])
        
        #print "salloc_req=", json.dumps(salloc_req)
        reservations=[]
        rollback = False
        error_msg = ""
        try:
           for req in salloc_req:
              manager = NETManagersView.managers[NETResourcesView.ManagersTypes[req["Type"]]] 
                
              if req["Type"] == "PublicIP" and "Attributes" in req and "VM" in req["Attributes"] and \
                     req["Attributes"]["VM"] in groups:
                 req["Attributes"]["VM"] = groups[req["Attributes"]["VM"]]             
              ret = post({"Allocation": [req], "Monitor": monitor}, "createReservation", \
                         manager["Port"], manager["Address"])
              if "result" in ret and "ReservationID" in ret["result"]:
                 rID = ret["result"]["ReservationID"]
                 if len(rID) != 1:
                    raise Exception("Wrong reservation ID (%s), expecting one element; manager info: %s" % (str(rID), str(manager)))
                    
                 if "Group" in req:
                    groups[req["Group"]] = rID[0]
                    
                 reservations.append({ "addr": manager["Address"], "port": manager["Port"], \
                                       "name": manager["Name"], "ManagerID": manager["ManagerID"], \
                                       "iRes": rID, "pos": req["pos"] })
              else:
                 raise Exception("internal error: %s" % str(ret))
        except Exception as e:
           print "rolling back! " + str(e)
           error_msg = str(e)
           rollback = True
        
        if not rollback:
           resID = uuid.uuid1()
           ReservationsView.reservations[str(resID)] = reservations
        else:
           for iResID in reservations:
              print "backtracking...%s" % str(iResID)
              data = {"ReservationID": iResID["iRes"]}
              try:                
                hresman.utils.delete_(data, 'releaseReservation', iResID["port"], iResID["addr"])
              except:
                pass  
           raise Exception("cannot make reservation! (rollbacking): %s" % error_msg)  
        
        return { "ReservationID" : [str(resID)] }          
           
    ###############################################  check reservation ############   
    def _check_reservation(self, reservations):
       check_result = { "Instances": {} }
 
       for reservation in reservations:
          if reservation not in ReservationsView.reservations: 
             raise Exception("cannot find reservation: " + reservation)
          
          # we must check with the original requested order
          data = sorted(ReservationsView.reservations[reservation], key=itemgetter('pos')) 
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
       for reservation in reservations:
          if reservation not in ReservationsView.reservations: 
             raise Exception("cannot find reservation: " + reservation)
          # reverse the order in which they were created
          data = ReservationsView.reservations[reservation][::-1]
          del ReservationsView.reservations[reservation] 
          
          for alloc in data:  
             ret = hresman.utils.delete_( { "ReservationID" : alloc["iRes"] }, "releaseReservation", alloc["port"], alloc["addr"])
             #if "result" not in ret:
             #   raise Exception("Error in deleting reservation: ", str(ret))
                
       return { }   
  
    ###############################################  release all reservations ############        
    def _release_all_reservations(self):
       managers = NETManagersView.managers
       for m in managers:
          hresman.utils.delete_({}, "releaseAllReservations", managers[m]['Port'], managers[m]['Address'])
       ReservationsView.reservations = {}
       
       return {}            
                   
  

