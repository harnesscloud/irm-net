import requests, subprocess
import ConfigParser, optparse
import logging, logging.handlers as handlers
import json
import copy
import uuid
import os
import sys
import time

import re           # grep IPs using regex
import paramiko     # ssh remote commands

import itertools    # create combinations from list

# Floating IP of conpaas-director
FIP_CONPAAS_DIRECTOR = None

# MINIMUM guaranteed bandwidth in Mbit/sec
MIN_BANDWIDTH_MBPS = 10


################################## CLI Stuff - Start ##################################

#
# Config and format for logging messages
#
logger = logging.getLogger("Rotating Log")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(fmt='%(asctime)s.%(msecs)d - %(levelname)s: %(filename)s - %(funcName)s: %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
handler = handlers.TimedRotatingFileHandler("n-irm.log",when="H",interval=24,backupCount=0)
## Logging format
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

irm_net_path = os.path.dirname(os.path.abspath(__file__))

def init():
    #
    # Read OpenStack configuration
    #
    global CONFIG
    if 'CONFIG' not in globals():
        #
        # FIXME Not elegant to read config file outside of the repository
        # TODO Pass configuration through app.py and NetReservationView;
        # see irm-neutron and supervisord.conf under iaas-deployment-docker-image.
        #
        CONFIG = ConfigParser.RawConfigParser()
        CONFIG.read(irm_net_path + '/../../cfg/irm-net.cfg')

    if CONFIG.has_option('main', 'USERNAME'):
        os.environ['OS_USERNAME'] = CONFIG.get('main', 'USERNAME')

    if CONFIG.has_option('main', 'TENANT_NAME'):
        os.environ['OS_TENANT_NAME'] = CONFIG.get('main','TENANT_NAME')

    if CONFIG.has_option('main', 'PASSWORD'):
        os.environ['OS_PASSWORD'] = CONFIG.get('main','PASSWORD')

    if CONFIG.has_option('main', 'NOVA_ENDPOINT'):
        os.environ['OS_AUTH_URL'] = "http://%s/v2.0" % CONFIG.get('main','NOVA_ENDPOINT')


################################## CLI Stuff - End ####################################
################################## UTI Stuff - Start ##################################

def load_spec_nodes(mchn):
   curr = os.path.dirname(os.path.abspath(__file__))
   with open(curr + '/net.json') as data_file:    
      rules = json.load(data_file)

   inf = sys.maxint

   spec_nodes = { "DC-01234": { "DC": { "LT":0, "BW":inf }, "LT": 0, "BW":inf}, "LT": 0, "BW": inf}

   dc = spec_nodes["DC-01234"]["DC"]

   clusters = {}
   for m in mchn:
      rule = {}
      for r in rules:
         if r["name"] in m:
            rule = r
            break
      if rule == {} or 'cluster' not in rule:
         raise Exception("IRM-NET: cannot find network information about machine: %s!" % m)

      if r['cluster'] not in clusters:
         clusters[r['cluster']] = {}
      clusters[r['cluster']][m] = {}


   for c in clusters:
      rule = {}
      for r in rules:
         if r["name"] in c:
            rule = r
            break
      bw = -1
      latency = 0

      if rule != {}:
         if 'bandwidth' in rule:
            bw = rule['bandwidth']
         if 'latency' in rule:
            latency = rule['latency']
      if bw == -1:
         bw = inf

      clusters[c]['BW'] = bw
      clusters[c]['LT'] = latency

   dc_rule = {}        
   for r in rules:    
      if r['name'] == 'DC':
         dc_rule = r

   #print ":::::::::::>", dc_rule
   if dc_rule != {}:
      if 'bandwidth' in dc_rule:
          bw = dc_rule['bandwidth']
          if bw == -1:
             bw = inf
          dc['BW'] = bw   
      if 'latency' in dc_rule:
         dc['LT'] = dc_rule['latency']
   dc.update(clusters)

   #print ":::::::::::::>", json.dumps(spec_nodes, indent=4)   
   return spec_nodes


def link_gen_topology(machines):

   mchn = { k:{} for k,v in machines.items() }

   load_spec_nodes(mchn)
   '''
   spec_nodes = {
    "DC": {
        "Cluster0": {
            "Switch0": {
                "controller": {},
                "LT": 20,
                "BW": 70
            },
            "Switch1": {
                "compute-001": {},
                "compute-002": {},                
                "LT": 20,
                "BW": 1500
            },
            "LT": 230,
            "BW": 30
        },
        "LT": 0,
        "BW": 1500
    },
    "LT": 0,
    "BW": 1000
   }
   '''
   spec_nodes = load_spec_nodes(mchn)
   #print "spec_nodes = ", spec_nodes

   links,nodes=gen_topology(spec_nodes)

   #print "links=", json.dumps(links, indent=4)
   #print "nodes=", json.dumps(nodes, indent=4)
   paths, link_list, constraint_list = gen_paths(links, nodes)
   return { "links": links, "nodes": nodes, "paths": paths, "link_list": link_list, "constraint_list": constraint_list }


def process_spec(links, nodes, source, spec_nodes, level, n, context):
    if spec_nodes == {}:
       nodes[n[0]] = { "Datacenter": context[0], "Cluster": context[1], "Switch": context[2], "ID": source }
       n[0] = n[0] + 1
       return 
    if "LT" in spec_nodes:
       latency = spec_nodes['LT']
    else:
       raise Exception("Cannot determine latency: %s, level: %d!" % (source, level))

    if 'BW' in spec_nodes:
       bandwidth = spec_nodes['BW']      
    else:
       raise Exception("Cannot determine bandwidth: %s, level: %d" % (source, level))

    for target in spec_nodes:
       if target != 'BW' and target != 'LT':
          key = "l_" + source + "_" + target   
          #cprint ":::>", ' ' * level*4, key, ":", context[0], ":", context[1], ":", context[2]    
          links[key] = { "Type": "Link", "Source": source, "Target": target, \
                        "Attributes": { "Latency": latency, "Bandwidth": bandwidth, \
                        "RealBandwidth": bandwidth} }
          if level < len(context):
             context[level] = target
          process_spec(links, nodes, target, spec_nodes[target], level+1, n, context)


def gen_topology(spec_nodes):
    # Generate nodes and links
    links = { }
    nodes = { }
    context = ["", "", ""]

    process_spec(links, nodes, "root", spec_nodes, 0, [0], context)
    #print "LINKS=", json.dumps(links, indent=4) 
    #print "NODES=", json.dumps(nodes, indent=4)

    return links, nodes


def gen_paths(links, nodes):

    paths = { }
    link_list = { }
    z = 0

    # Generate link lists for each path
    for i in range( len(nodes) ):
        for j in range( i+1, len(nodes) ):

            # Generate PathId
            pathID = "P" + `z`
            z  = z + 1


            ######################
            ##  Generate links  ##
            ######################

            link_list[ pathID ] = [ ]

            dc1 = nodes[i]["Datacenter"]
            dc2 = nodes[j]["Datacenter"]
            c1 = nodes[i]["Cluster"]
            c2 = nodes[j]["Cluster"]
            s1 = nodes[i]["Switch"]
            s2 = nodes[j]["Switch"]

            # Assume that nodes are:
            # - Under the same DC
            # - Under the same Cluster
            # - Under the same Switch
            intraDatacenter = True
            intraCluster    = True
            intraSwitch     = True

            if ( dc1 != dc2 ):
                intraDatacenter = False
                intraCluster    = False
                intraSwitch     = False

            elif ( c1 != c2 ):
                intraCluster = False
                intraSwitch  = False

            elif ( s1 != s2 ):
                intraSwitch = False

            '''
            # Ignore all non-intraSwitch paths;
            # Reduce the previously-increased z;
            # TODO just increase z at the end of the loop
            if not intraSwitch:
                z = z - 1
                continue
            '''

            # Inter-Datacenter links
            if not ( intraDatacenter ):
                key = "l_" + "root" + "_" + dc1
                link_list[ pathID ].append( key )
                key = "l_" + "root" + "_" + dc2
                link_list[ pathID ].append( key )

            # Inter-Cluster links
            if not ( intraCluster ):
                key = "l_" + dc1 + "_" + c1
                link_list[ pathID ].append( key )
                key = "l_" + dc2 + "_" + c2
                link_list[ pathID ].append( key )

            # Inter-Switch links
            if not ( intraSwitch ):
                key = "l_" + c1 + "_" +  s1
                link_list[ pathID ].append( key )
                key = "l_" + c2 + "_" + s2
                link_list[ pathID ].append( key )

            # Intra-Switch links
            key = "l_" + s1 + "_" + nodes[i]["ID"]
            link_list[ pathID ].append( key )
            key = "l_" + s2 + "_" + nodes[j]["ID"]
            link_list[ pathID ].append( key )


            ######################
            ##  Generate paths  ##
            ######################

            # The dictionary of @paths MUST conform
            # to the format expected by the CRS

            paths[ pathID ] = { };

            paths[ pathID ]["Type"]   = "Link"
            #paths[ pathID ]["Source"] = nodes[i]["ID"]
            #paths[ pathID ]["Target"] = nodes[j]["ID"]
            paths[ pathID ]["Attributes"] = { }
            paths[ pathID ]["Attributes"]["Bandwidth"] = 0
            paths[ pathID ]["Attributes"]["Latency"]   = 0
            paths[ pathID ]["Attributes"]["Source"] = nodes[i]["ID"]
            paths[ pathID ]["Attributes"]["Target"] =  nodes[j]["ID"]

    #print "paths :::>", json.dumps(paths, indent=4) 

    #print "link_list :::>", json.dumps(link_list, indent=4)          
    # Calculate bandwidth/latency
    calculate_attribs(paths, link_list, links)

    # Generate constraints
    constraint_list = gen_constraints(link_list, links)

    return paths, link_list, constraint_list


def calculate_attribs(paths, link_list, links):
    for id in paths:
         # Calculate PATH latency & BW
         latency = 0
         bandwidth = links[ link_list[id][0] ]["Attributes"]["Bandwidth"]

         for k in range( len(link_list[id]) ):

             key = link_list[id][k]
             aLink = links[key]

             latency = latency + aLink["Attributes"]["Latency"]
             linkBW = aLink["Attributes"]["Bandwidth"]

             if ( linkBW < bandwidth ):
                     bandwidth = linkBW

         paths[id]["Attributes"]["Bandwidth"] = bandwidth
         paths[id]["Attributes"]["Latency"]   = "%.2f" % latency


def gen_constraints(link_list, links):

    # Initialize constraints json and bandwidths
    constraints = {}
    for link_id in links:
        constraints[link_id] = {}
        constraints[link_id]["Paths"] = []
        constraints[link_id]["Bandwidth"] = links[link_id]["Attributes"]["Bandwidth"]

    # Iterate all paths
    for path_id in link_list:

        # Iterate all links within a path
        for link_id in link_list[path_id]:

            # Add path_id to the lists of the links it traverses
            constraints[link_id]["Paths"].append( path_id )

    ##################
    ##  Conversion  ##
    ##################

    constraint_list = {}

    for constraintID in constraints:

        # Create new ID;
        # update bandwidth
        cID = "C" + constraintID

        constraint_list[cID] = {}
        constraint_list[cID]["Attribute"] = "Bandwidth"

        inequality = ""
        for pathID in constraints[constraintID]["Paths"]:

            # If not empty, add "+"
            if ( inequality != "" ):
                inequality = inequality + " + "

            inequality = inequality + pathID

        # Finally, add the bandwidth constraint, if there are any paths
        if ( inequality != "" ):
            inequality = inequality + " <= " + `constraints[constraintID]["Bandwidth"]`
            constraint_list[cID]["Constraint"] = inequality
        else:
            del constraint_list[cID]

    return constraint_list


def link_calc_capacity(resource, allocation, release):

    if "Bandwidth" not in resource["Attributes"]:
       raise Exception("Bandwidth attribute must be specified in Resource!")
    if "Source" not in resource["Attributes"]:
       raise Exception("Source attribute must be specified in Resource!")
    if "Target" not in resource["Attributes"]:
       raise Exception("Target attribute must be specified in Resource!")

    bandwidth = resource["Attributes"]["Bandwidth"]
    source = resource["Attributes"]["Source"]
    target = resource["Attributes"]["Target"]

    bandwidth_release = 0
    for rel in release:
       if "Bandwidth" not in rel["Attributes"]:
          raise Exception("Bandwidth attribute must be specified in Release!")
       if "Source" not in rel["Attributes"]:
          raise Exception("Source attribute must be specified in Release!")
       if "Target" not in rel["Attributes"]:
          raise Exception("Target attribute must be specified in Release!")   

       if rel["Attributes"]["Source"] != source:
          return {}
       if rel["Attributes"]["Target"] != target:
          return {}       

       bandwidth = bandwidth + rel["Attributes"]["Bandwidth"]

    for alloc in allocation:
       if "Bandwidth" not in alloc["Attributes"]:
          raise Exception("Bandwidth attribute must be specified in Allocation!")
       if "Source" not in alloc["Attributes"]:
          raise Exception("Source attribute must be specified in Allocation!")
       if "Target" not in alloc["Attributes"]:
          raise Exception("Target attribute must be specified in Allocation!")

       if alloc["Attributes"]["Source"] != source:
          return {}
       if alloc["Attributes"]["Target"] != target:
          return {}       

       bandwidth = bandwidth - alloc["Attributes"]["Bandwidth"]
       if bandwidth < 0:
          return {}

    return {"Resource": {"Type": "Link", "Attributes": { "Source": source, "Target": target, "Bandwidth": bandwidth } }} 


################################## UTI Stuff - End ####################################
################################## API Stuff - Start ##################################

def bwadapt_add_tenant (links, paths, link_list, link_res, tenantID,
        reservedMachineResources, reservedLinkResources ):

    # Add tenant to database
    add_tenant( tenantID, paths, reservedMachineResources, reservedLinkResources )
    update_tenant_bandwidth( links, paths, link_list )
    return 0


def bwadapt_remove_tenant (links, paths, link_list, link_res, tenantID):

    # Find tenant in database and remove
    remove_tenant( tenantID )
    update_tenant_bandwidth( links, paths, link_list )
    return 0


def bwadapt_delete_all_tenants():
    delete_all_tenants()
    return 0


def link_create_reservation (links, paths, link_list, link_res, req, reservedMachineResources):
    #logger.info("Called")

    #logger.info("paths=%s", json.dumps(paths))
    #logger.info("links=%s", json.dumps(links))
    #logger.info("link_list=%s", json.dumps(link_list))
    #logger.info("link_res=%s", json.dumps(link_res))
    #logger.info("req=%s", json.dumps(req))

    # find the ID; it is either provided (Damian's CRS, or it needs to be found)

    pathID = None
    if 'ID' not in req:
       if ('Source' not in req["Attributes"]) or ('Target' not in req["Attributes"]):
          raise Exception("ID not found, so Source/Target attributes must be specified!")       
       for p in paths:
          if (paths[p]["Attributes"]["Source"] == req["Attributes"]["Source"]) and \
             (paths[p]["Attributes"]["Target"] == req["Attributes"]["Target"]):
             pathID = p
             break
          elif (paths[p]["Attributes"]["Source"] == req["Attributes"]["Target"]) and \
             (paths[p]["Attributes"]["Target"] == req["Attributes"]["Source"]):
             pathID = p
             break

       if pathID == None:
          raise Exception("Cannot find a path with source: %s and target: %s" % (req["Attributes"]["Source"], \
                                                                                 req["Attributes"]["Target"]))
    else:
       if req['ID'] not in paths:
          raise Exception("Cannot find path: %s" % req['ID'])
       pathID = req['ID']

    #
    # Sanity check: proper bandwidth has been provided
    #
    if 'Bandwidth' not in req['Attributes']:
       raise Exception("Bandwidth attribute required!")
    bandwidth = req['Attributes']['Bandwidth']
    if bandwidth <= 0:
       raise Exception("Invalid bandwidth %.2f requested!" % bandwidth)

    #
    # Check available bandwidth and reserve
    #
    error = path_check_bandwidth( pathID, link_list, bandwidth )
    if ( error ):
        raise Exception("Not enough bandwidth (%.2f) in path: %s" % (bandwidth, pathID))
    path_reserve_bandwidth( pathID, link_list, bandwidth )

    #
    # Create the reservation ID
    #
    resID = str(uuid.uuid1())
    link_res[resID] = { "pathID": pathID, "bandwidth": bandwidth }

    #
    # Update the paths, since we might have reserved bandwidth
    # on a bottleneck link
    #
    calculate_attribs(paths, link_list, links)
    install_traffic_rules( paths[pathID]["Attributes"]["Source"],
            paths[pathID]["Attributes"]["Target"],
            bandwidth, reservedMachineResources )

    return resID

def link_release_reservation (links, paths, link_list, link_res, resIDs):

    for resID in resIDs:
        if resID not in link_res:
           raise Exception("Cannot find reservation ID: %s" % resID)

        pathID    = link_res[ resID ]["pathID"]
        bandwidth = link_res[ resID ]["bandwidth"]

        #
        # Release the bandwidth
        # from that path.
        #
        path_release_bandwidth( pathID, link_list, bandwidth )

        # Remove reservation from list
        del( link_res[resID] )

    calculate_attribs(paths, link_list, links)

    return { }

def link_check_reservation (link_res, resIDs):
    result = { }
    for resID in resIDs:
        if resID not in link_res:
           raise Exception("Cannot find reservation ID: %s" % resID)

        result[resID] = { "Ready": "True", "Address": ["virtual-link://%s" % resID] }

    return { "Instances": result }


################################## API  Stuff - End ####################################
################################## Fair Stuff - Start ##################################

#
# FairCloud "global" internal variables
# @tenantTable  Table with tenants and associated machines
#
tenantTable={}

#
# Add tenant in @tenantTable
#
def add_tenant( tenantID, paths, reservedMachineResources, reservedLinkResources ):

    #
    # Initialize tenant json
    #
    tenantTable[ tenantID ] = {}

    #
    # Generate all combinations from the
    # reserved machines
    # NOTE: if importing just "combinations" from itertools,
    # do not give the same name to 'combinations'
    #
    combinationList = list( itertools.combinations(reservedMachineResources, 2) )

    # Iterate all pairs
    # We will register within the tenant's record:
    # - Every pathID; for each pathID:
    # -- sourceID
    # -- targetID
    # -- used Bandwidth
    for pair in combinationList:

        sourceHost = pair[0]["Host"]
        targetHost = pair[1]["Host"]

        #
        # Iterate all paths to find the corresponding pathID
        #
        pathID = None
        for p in paths:

            if (paths[p]["Attributes"]["Source"] == sourceHost) and \
                    (paths[p]["Attributes"]["Target"] == targetHost):
                    pathID = p
                    break

            elif (paths[p]["Attributes"]["Source"] == targetHost) and \
                    (paths[p]["Attributes"]["Target"] == sourceHost):
                    pathID = p
                    break

        if pathID == None:
            raise Exception("Cannot find a path with source: %s and target: %s" % (sourceHost,targetHost))

        #
        # Iterate all reserved link resources
        # to find the requested bandwidth.
        # Negative bandwidth implies undefined.
        # FIXME assuming that no two paths overlap,
        # i.e., the tenant has not made two virtual path reservations
        # across the SAME path.
        #
        requestedBandwidth = -1
        for linkResource in reservedLinkResources:
            tmpSourceHost = linkResource["Attributes"]["Source"]
            tmpTargetHost = linkResource["Attributes"]["Target"]

            if ((tmpSourceHost == sourceHost) and (tmpTargetHost == targetHost)) \
                    or ((tmpSourceHost == targetHost) and (tmpTargetHost == sourceHost)):

                requestedBandwidth = linkResource["Attributes"]["Bandwidth"]
                break

        if requestedBandwidth < 0:
            raise Exception("Could not find requested bandwidth for path " % pathID)

        #
        # Initialize path json.
        # Initialize values.
        # Store ID values of machines.
        #
        tenantTable[ tenantID ][ pathID ] = {}
        tenantTable[ tenantID ][ pathID ]["UsedBandwidth"] = requestedBandwidth
        tenantTable[ tenantID ][ pathID ]["MaxUsedBandwidth"] = requestedBandwidth

        #
        # Iterate the reservedMachineResources
        # to find the sourceID and targetID
        # FIXME assuming no two containers have been scheduled
        # on the SAME host for the same tenant.
        #
        for resource in reservedMachineResources:

            machineHost = resource["Host"]
            machineID   = resource["ID"]

            if machineHost == source :
                tenantTable[ tenantID ][ pathID ]["SourceID"] = machineID
            elif machineHost == target :
                tenantTable[ tenantID ][ pathID ]["TargetID"] = machineID

    return 0


#
# Remove tenant from @tenantTable
#
def remove_tenant( tenantID ):

    if tenantID in tenantTable:
        del tenantTable[ tenantID ]
    else:
        raise Exception("Tenant not found " % tenantID)

    return 0


#
# Delete all tenants from @tenantTable
#
def delete_all_tenants():

    delList = []
    for key in tenantTable:
        delList.append( key )

    for key in delList:
        del tenantTable[key]

    return 0


#
# Update links & paths after tenant update.
#
def update_tenant_bandwidth( links, paths, link_list ):

    calc_tenant_bandwidth( links, paths, link_list )
    calculate_attribs( paths, link_list, links )

    return 0


#
# Calculate the bottleneck of each path:
#
def calc_tenant_bandwidth( links, paths, link_list ):

    #
    # Iterate all active tenants
    #
    for tenantID in tenantTable:

        #
        # Iterate all paths of tenant to measure the bandwidth
        # Measuring at source is enough.
        #
        for pathID in tenantTable[ tenantID ]:

            # Get source/target IDs
            sourceID = tenantTable[ tenantID ][ pathID ]["SourceID"]
            targetID = tenantTable[ tenantID ][ pathID ]["TargetID"]

            #
            # TODO this is the bandwidth that will be measured
            # SSH to source machine; measure bandwidth
            # Note: MEASURED bandwidth is how much we are consuming
            # The 'UsedBandwidth' in the tenant entry refers to how much it's being currently used;
            # thus, we can infer how much more/less we need.
            #
            measuredBandwidth = measure_bandwidth( sourceID, targetID )

            # Never exceed the maximum requested bandwidth, in case more was measured
            # due to an error.
            # TODO raise a warning?
            maxUsedBandwidth = tenantTable[ tenantID ][ pathID ]["MaxUsedBandwidth"]
            if measuredBandwidth > maxUsedBandwidth:
                measuredBandwidth = maxUsedBandwidth

            # If below the minimum guaranteed bandwidth,
            # set it to that.
            # Exception: if the user initially requested less than the
            # minimum guaranteed.
            if maxUsedBandwidth > MIN_BANDWIDTH_MBPS and measuredBandwidth < MIN_BANDWIDTH_MBPS:
                measuredBandwidth = MIN_BANDWIDTH_MBPS

            #
            # Calculate the bandwidth we have to "release":
            # diff = before - after > 0
            # If diff < 0, then we reserve.
            # NO sanity check in case we have to reserve bandwidth;
            # check the @path_release_bandwidth comments.
            #
            oldBandwidth = tenantTable[ tenantID ][ pathID ]["UsedBandwidth"]
            releasedBandwidth = oldBandwidth - measuredBandwidth

            path_release_bandwidth( pathID, link_list, releasedBandwidth )

            #
            # Set the path's consumed bandwidth based on the measurements
            # A minimum bandwidth is always guaranteed.
            #
            tenantTable[ tenantID ][ pathID ]["UsedBandwidth"] = measuredBandwidth

    return 0


################################## Fair Stuff - End ####################################
################################## Lib Stuff  - Start ##################################

#
# Function:
#   path_check_bandwidth
# Purpose:
#   Checks whether a given @pathID has available @bandwidth.
# Returns:
#   0 - true
#   1 - false
#
def path_check_bandwidth( pathID, link_list, bandwidth ):

    bandwidth_abs = abs(bandwidth)
    for linkID in link_list[ pathID ]:
        if bandwidth_abs > links[ linkID ]["Attributes"]["Bandwidth"]:
            return 1

    return 0


#
# Function:
#   path_release_bandwidth
# Purpose:
#   Release bandwidth from a given path;
#   iterates all links and releases the appropriate bandwidth.
#   If @bandwidth is zero, nothing happens.
#   If @bandwidth is negative, bandwidth is reserved, instead.
#
#   'RealBandwidth' attribute may be negative, if we are oversubscribing.
#   'Bandwidth' attribute is the reported bandwidth, used to determine
#   if we can create a new reservation; set to 'RealBandwidth',
#   unless the latter is negative, in which case it's set to zero.
#
def path_release_bandwidth( pathID, link_list, bandwidth ):

    if bandwidth != 0:

        #
        # Iterate all links in this path
        # Reserve/Release bandwidth on the links
        # Add/subtract to/from "RealBandwidth"; it may be negative.
        #
        for linkID in link_list[ pathID ]:
            links[ linkID ]["Attributes"]["RealBandwidth"] = \
                links[ linkID ]["Attributes"]["RealBandwidth"] + bandwidth

            #
            # Is the resulting bandwidth negative?
            # If so, report 'zero'; otherwise, report the 'real' bandwidth.
            #
            realBandwidth = links[ linkID ]["Attributes"]["RealBandwidth"]
            if realBandwidth <= 0 :
                links[ linkID ]["Attributes"]["Bandwidth"] = 0
            else :
                links[ linkID ]["Attributes"]["Bandwidth"] = realBandwidth

    return 0


#
# Function:
#   path_reserve_bandwidth
# Purpose:
#   Reserve bandwidth from a given path;
#   iterates all links and reserves the appropriate bandwidth.
#   Calls @path_release_bandwidth with (-1) * @bandwidth
#   If @bandwidth is zero, nothing happens.
#   If @bandwidth is negative, bandwidth is released, instead.
#
def path_reserve_bandwidth( pathID, link_list, bandwidth ):
    return path_release_bandwidth( pathID, link_list, (-1)*bandwidth )


################################## Lib Stuff - End ####################################
################################## Traffic Rules - Start ##############################

def measure_bandwidth( sourceID, targetID ):

    measuredBandwidth = -1

    # Retrieve the following IPs:
    # source Public IP (to connect)
    # source Private IP
    # target Private IP

    sourcePublicIP  = get_public_IP_from_ID( sourceID )
    sourcePrivateIP = get_private_IP_from_ID( sourceID )
    targetPrivateIP = get_private_IP_from_ID( targetID )

    #
    # Connect to the source host
    #
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect( sourcePublicIP, username='root', password='contrail' )
    except paramiko.AuthenticationException:
        raise Exception("Authentication failed when connecting to " % sourcePublicIP)

    bwperfCommand="IF=$(/sbin/ifconfig | grep HWaddr | grep -v eth0 | awk '{print $1}'); " \
            + "/root/bwperf -i $IF " \
            + "-f 'host " + sourcePrivateIP + " and host " + targetPrivateIP + "' " \
            + "-t 3"
    stdin, stdout, stderr = client.exec_command( bwperfCommand )
    error = stderr.readlines()

    #
    # Was the connection established?
    # Retry if not. Cap the retry times.
    #
    retry = 50
    while (retry > 0) and len(error) and re.search("Connection refused", error[0]) > 0:
        time.sleep(1)
        retry = retry - 1
        stdin, stdout, stderr = client.exec_command( conpaasCommand )
        error = stderr.readlines()

    # Read the output
    output = stdout.readlines()

    # Close the connection
    client.close()

    # Abort if failed
    if ( retry <= 0 ):
        raise Exception("Could not connect to " + sourcePublicIP)

    return measuredBandwidth


#
# TODO close processes
# http://kendriu.com/how-to-use-pipes-in-python-subprocesspopen-objects
#
# @param reservedMachineResources List of reserved machines resources.
#
def install_traffic_rules( sourceHost, targetHost, bandwidth, reservedMachineResources ):

    
    #print "sourceHost:", sourceHost    
    #print "targetHost:", targetHost
    #print "reservedMachineResources: ", reservedMachineResources
    
    #reservedMachineResources:  [{'Host': u'compute-001', 'Type': u'Machine',
    # 'ID': u'ac244a32-2913-49a4-bbb2-07a627bdb101'}, {'IP': u'192.168.13.42', 
    #'Host': u'web-wikipedia', 'Type': u'Web-Wikipedia', 'ID': u'web-wikipedia'}]
    

    #
    # Iterate @reservedMachineResources and find the IDs.
    # FIXME we assume that there is a 1-1 match between hosts and containers.
    # TODO scenario when two containers are on the same host.
    # json format of each machine element in @reservedMachineResources:
    #   {"Host" : compute-host, "ID": ID of container}
    #
    
    
    sourceIP = None
    targetIP = None
    sourceType = None
    targetType = None
    for resource in reservedMachineResources:
        if resource["Host"] == sourceHost :
            sourceType = resource["Type"]
            if sourceType == "Machine":
                sourceIP = get_private_IP_from_ID(resource["ID"])
            else:
                sourceIP = resource["IP"]    
        if resource["Host"] == targetHost :
            targetType = resource["Type"]        
            if targetType == "Machine":
                targetIP = get_private_IP_from_ID(resource["ID"])
            else:
                targetIP = resource["IP"]    

        if sourceIP is not None and targetIP is not None :
            break

    if not sourceIP or not targetIP :
        raise Exception("Could not find Private IPs for resources " + sourceHost + ", " + targetHost)

    #
    # Install rules on both containers
    #
    if sourceType == "Machine":
       traffic_rules_propagate( sourceIP, targetIP, [bandwidth] )
    
    if targetType == "Machine":
       traffic_rules_propagate( targetIP, sourceIP, [bandwidth] )


#
# Parameters:
#   @srcIP          Private IP of container where the rules will be installed
#   @dstIP          Private IP of the second container that these rules concern
#   @bandwidthList  List Requested bandwidth in Mbit/sec
#
def traffic_rules_propagate( srcIP, dstIP, bandwidthList ):

    #
    # Craft bandwidth requests
    #
    bwReq = []
    for bandwidth in bandwidthList:
        bwReq.append({'Target': dstIP, 'Rate': str(bandwidth)+"mbit"})

    #
    # TC Installation Base File
    # Read it; replace the placeholders.
    #
    tcBaseFile = "tcinstall-base.sh"
    file_ = open(irm_net_path + "/../" + tcBaseFile,'r')

    tcBaseData = file_.read()
    file_.close()
    tcCommand = tcBaseData.replace('__BWRATESTRING',json.JSONEncoder().encode(bwReq))

    #
    # Retrieve conpaasIP if not already there.
    # We assume that it does not change.
    # TODO retrieve again if cannot connect
    #
    global FIP_CONPAAS_DIRECTOR
    if FIP_CONPAAS_DIRECTOR is None :
        FIP_CONPAAS_DIRECTOR = get_public_IP_from_ID( 'conpaas-director' )

    #
    # Use a local variable now
    #
    conpaasIP = FIP_CONPAAS_DIRECTOR
    if conpaasIP is None:
        raise Exception("Could not retrieve Public IP of conpaas-director")

    #
    # Craft remote command @ conpaas-director
    #
    conpaasCommand = 'ssh root@' + srcIP + ' bash -s << EOF\n' + tcCommand + '\nEOF'

    #
    # Connect to conpaas-director
    #
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(conpaasIP, username='root')
    except paramiko.AuthenticationException:
        raise Exception("Authentication failed when connecting to conpaas-director")

    stdin, stdout, stderr = client.exec_command( conpaasCommand )
    error = stderr.readlines()

    #
    # Was the connection established?
    # Retry if not. Cap the retry times.
    #
    retry = 50
    while (retry > 0) and len(error) and re.search("Connection refused", error[0]) > 0:
        time.sleep(1)
        retry = retry - 1
        stdin, stdout, stderr = client.exec_command( conpaasCommand )
        error = stderr.readlines()

    #
    # Close the connection
    #
    client.close()

    #
    # Abort if failed
    #
    if ( retry <= 0 ):
        raise Exception("Could not connect to " + sourceMachineIP)

    return 0


#
# Methods:
#   get_private_IP_from_ID
#   get_public_IP_from_ID
# Purpose:
#   Returns the private or the public IP of a container
#   FIXME assuming private IP of 192.168.xxx.xxx
#   FIXME assuming public  IP of  10.xxx.xxx.xxx
#   TODO import private IP range from config file.
# Parameters:
#   @entryID    The ID of the container
# Returns:
#   Success:    First match found
#   Else:       None
#
def get_private_IP_from_ID( entryID ):
    return get_IP_from_ID( entryID, '192\.168\.[0-9]+\.[0-9]+' )
def get_public_IP_from_ID( entryID ):
    return get_IP_from_ID( entryID, '10\.[0-9]+\.[0-9]+\.[0-9]+' )

#
# Method:
#   get_IP_from_ID
# Purpose:
#   Retrieves the IP of a container based on a regular expression
# Parameters:
#   @entryID    The ID of the container
#   @regexIP    The IP regular expression to look up
# Returns:
#   Success:    First match found
#   Else:       None
#
def get_IP_from_ID( entryID, regexIP ):

    novaIn = ["nova", "show", entryID]
    process = subprocess.Popen(novaIn, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    novaOut, novaErr = process.communicate()

    if novaErr:
        logger.error(novaErr)
        return None

    matches=re.findall(regexIP, novaOut)

    if matches is None:
        logger.error("Unable to find IP for " + entryID + " from regex " + regexIP)
        return None

    return matches[0]


################################## Traffic Rules - End ################################

#
# Initialize config variables
#
init()
