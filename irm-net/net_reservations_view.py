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
from net_links import link_create_reservation, link_release_reservation, link_check_reservation
import copy

class NETReservationsView(ReservationsView):

    # we rank each type according to the order in which we create it
    SupportedTypes = { "Machine": 2, "PublicIP": 3, "Subnet": 1, "Link": 4 }
    LinkReservations = {}

    ###############################################  create reservation ############ 
    def _create_reservation(self, scheduler, alloc_req, alloc_constraints, monitor):
        NETManagersView.expect_ready_manager()
        
        groups = {}
        #print "alloc_req=", json.dumps(alloc_req)
        #print "monitor=", monitor
        
        NETResourcesView()._get_alloc_spec()
                 
        # first check that we can support all allocation requests
        for req in alloc_req:
           if req["Type"] not in NETReservationsView.SupportedTypes:
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
              if req["Type"] in NETResourcesView.ManagersTypes:
                 manager = NETManagersView.managers[NETResourcesView.ManagersTypes[req["Type"]]] 
              else:
                 manager = None
                
              if req["Type"] == "PublicIP" and "Attributes" in req and "VM" in req["Attributes"] and \
                     req["Attributes"]["VM"] in groups:
                 req["Attributes"]["VM"] = groups[req["Attributes"]["VM"]]["resID"]  
              
              if req["Type"] == "Link" and "Attributes" in req and "Source" in req["Attributes"] and \
                     req["Attributes"]["Source"] in groups:
                 req["Attributes"]["Source"] = groups[req["Attributes"]["Source"]]["ID"]

              if req["Type"] == "Link" and "Attributes" in req and "Target" in req["Attributes"] and \
                     req["Attributes"]["Target"] in groups:
                 req["Attributes"]["Target"] = groups[req["Attributes"]["Target"]]["ID"]
                                         
              if manager != None:              
                 ret = post({"Allocation": [req], "Monitor": monitor}, "createReservation", \
                            manager["Port"], manager["Address"])
              elif req["Type"] == "Link":
                 topology = NETResourcesView.Topology
                 id = link_create_reservation(topology["links"], topology["paths"], topology["link_list"],\
                                              NETReservationsView.LinkReservations, req) 
                 ret = { "result": { "ReservationID": [id] }} 
              else:
                 raise Exception("internal error: type %s not supported!" % req["Type"])
                               
              if "result" in ret and "ReservationID" in ret["result"]:
                 rID = ret["result"]["ReservationID"]
                 if len(rID) != 1:
                    raise Exception("Wrong reservation ID (%s), expecting one element; manager info: %s" % (str(rID), str(manager)))
                  
                 if "Group" in req:
                    groups[req["Group"]] = {"resID": rID[0] } # reservation ID
                    if "ID" in req:
                       groups[req["Group"]]["ID"] = req["ID"] # ID of the physical resource
                                  
                 if manager:  
                    reservations.append({ "addr": manager["Address"], "port": manager["Port"], \
                                          "name": manager["Name"], "ManagerID": manager["ManagerID"], \
                                          "iRes": rID, "pos": req["pos"], "type": req["Type"] })
                 else:                                       
                     reservations.append({ "addr": None, "port": None, \
                                          "name": "IRM-NET", "ManagerID": None, \
                                          "iRes": rID, "pos": req["pos"], "type": req["Type"] })                                     
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
           for iResID in reservations[::-1]:
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
             if alloc["addr"] != None:
                ret = hresman.utils.post( { "ReservationID" : alloc["iRes"] }, "checkReservation", alloc["port"], alloc["addr"])
             elif alloc["type"] == "Link": 
                res = link_check_reservation(NETReservationsView.LinkReservations, alloc["iRes"])
                ret = { "result": res }
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
             if alloc["addr"] != None:
                ret = hresman.utils.delete_( { "ReservationID" : alloc["iRes"] }, "releaseReservation", alloc["port"], alloc["addr"])
             elif alloc["type"] == "Link":
                topology = NETResourcesView.Topology   
                res = link_release_reservation(topology["links"], topology["paths"], topology["link_list"],\
                      NETReservationsView.LinkReservations, alloc["iRes"])
                ret = { "result": res }
             #if "result" not in ret:
             #   raise Exception("Error in deleting reservation: ", str(ret))
                
       return { }   
  
    ###############################################  release all reservations ############        
    def _release_all_reservations(self):
       managers = NETManagersView.managers
       for m in managers:
          hresman.utils.delete_({}, "releaseAllReservations", managers[m]['Port'], managers[m]['Address'])
       ReservationsView.reservations = {}

       topology = NETResourcesView.Topology                                                     
       for id in copy.copy(NETReservationsView.LinkReservations):
          link_release_reservation(topology["links"], topology["paths"], topology["link_list"],\
                                   NETReservationsView.LinkReservations, [id])
                                   
       if len(NETReservationsView.LinkReservations) > 0:
          raise Exception("could not release all reservations!")                           
       
       return {}            
                   
  

