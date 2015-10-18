#!/usr/bin/env python

import deps
from flask.ext.classy import FlaskView, route
from flask import  render_template
import threading;
from hresman.manager import HarnessResourceManager
import hresman.utils
import logging
from optparse import OptionParser

from net_managers_view import NETManagersView
from net_resources_view import NETResourcesView
from net_reservations_view import NETReservationsView
'''
from crs_status_view import CRSStatusView
from crs_managers_view import CRSManagersView
from crs_resources_view import CRSResourcesView
from crs_reservations_view import CRSReservationsView
from crs_metrics_view import CRSMetricsView
from crs_cost_view import CRSCostView
          
crs_views=[CRSManagersView,  \
           CRSStatusView, \
           CRSMetricsView, \
           CRSResourcesView, \
           CRSReservationsView,
           CRSCostView
          ]
'''

net_views=[NETManagersView, \
           NETResourcesView, \
           NETReservationsView]
             
mgr = HarnessResourceManager(net_views)

parser = OptionParser()
parser.add_option("-p", "--port", dest="PORT", default=7779,
                  help="IRM-NET port", type="int")
                  
parser.add_option("-o", "--chost", dest="CRS_HOST", default="localhost",
                  help="CRS host", type="string")      
                  
parser.add_option("-t", "--cport", dest="CRS_PORT", default=56788,
                  help="CRS port", type="int") 
                           
parser.add_option("-d", "--disable-crs", dest="CRS_DISABLE", default=False,
                  help="disable CRS", action="store_true")       
                  
parser.add_option("-i", "--ignore-irms", dest="IGNORE_IRMS", default=False,
                  help="ignore IRM-NOVA and IRM-NEUTRON", action="store_true")                                        
                
(options,_) = parser.parse_args()

def request_resources (): 
  global options
  threading.Timer(5, request_resources).start (); 
  try:
     hresman.utils.get('v3/resources/request', options.PORT)
  except Exception as e:
     pass


request_resources()

#NETResourcesView.load_topology()

NETManagersView.CRS_DISABLE=options.CRS_DISABLE
NETManagersView.IGNORE_IRMS=options.IGNORE_IRMS
NETManagersView.CRS_HOST = options.CRS_HOST
NETManagersView.CRS_PORT = options.CRS_PORT
NETManagersView.PORT = options.PORT

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

if not NETManagersView.CRS_DISABLE:
   NETManagersView.register_crs()   
print "running..."        
mgr.run(options.PORT)

   
   

      

  
   

