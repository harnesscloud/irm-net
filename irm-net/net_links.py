import json
import copy
import uuid

def link_get_topology():
   Latency_Table = [1, 1, 0.5, 0.1]
   BW_Table = [1, 1, 1, 10]
   spec_nodes = { "DC0": { "C0": { "S0": { "N0": {}, "N1": {}, "N2": {}, "N3": {}, "BW": 1 }, "S1": { "N4": {}, "N5": {}, "N6": {}, "N7": {} }}}} 
   
   links,nodes=gen_topology(Latency_Table, BW_Table, spec_nodes)
   paths, link_list, constraint_list = gen_paths(links, nodes)
   #print "PATHS=", json.dumps(paths, indent=4)
   #print "LINK_LIST=", json.dumps(link_list, indent=4)
   #print "CONSTRAINT_LIST=", json.dumps(constraint_list, indent=4)
   
   
   return { "links": links, "nodes": nodes, "paths": paths, "link_list": link_list, "constraint_list": constraint_list }

def process_spec(links, nodes, source, spec_nodes, level, n, counter, Latency_Table, BW_Table):
    if spec_nodes == {}:
       nodes[n[0]] = { "Datacenter": counter[0], "Cluster": counter[1], "Switch": counter[2], "ID": source }
       n[0] = n[0] + 1
       return 
    if "LT" in spec_nodes:
       latency = spec_nodes['LT']
    elif level < len(Latency_Table):
       latency = Latency_Table[level]
    else:
       raise Exception("Cannot determine latency: %s, level: %d!" % (source, level))
         
    if 'BW' in spec_nodes:
       bandwidth = spec_nodes['BW']
    elif level < len(BW_Table):
       bandwidth = BW_Table[level]         
    else:
       raise Exception("Cannot determine bandwidth: %s, level: %d" % (source, level))

    for target in spec_nodes:
       if target != 'BW' and target != 'LT':
          key = "l_" + source + "_" + target      
          links[key] = { "Type": "Link", "Source": source, "Target": target, \
                        "Attributes": { "Latency": latency, "Bandwidth": bandwidth } }
          process_spec(links, nodes, target, spec_nodes[target], level+1, n, copy.copy(counter), Latency_Table, BW_Table)
          if level < len(counter):
             counter[level] = counter[level] + 1

             
def gen_topology(Latency_Table, BW_Table, spec_nodes):    
    # Generate nodes and links
    links = { }
    nodes = { }
    counter = [0, 0, 0]
    
    for s in spec_nodes:
       process_spec(links, nodes, "root", spec_nodes, 0, [0], counter, Latency_Table, BW_Table)
       
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


            # Inter-Datacenter links
            if not ( intraDatacenter ):
                key = "l_" + "root" + "_" + "DC" + `dc1`
                link_list[ pathID ].append( key )
                key = "l_" + "root" + "_" + "DC" + `dc2`
                link_list[ pathID ].append( key )

            # Inter-Cluster links
            if not ( intraCluster ):
                key = "l_" + "DC" + `dc1` + "_" + "C" + `c1`
                link_list[ pathID ].append( key )
                key = "l_" + "DC" + `dc2` + "_" + "C" + `c2`
                link_list[ pathID ].append( key )

            # Inter-Switch links
            if not ( intraSwitch ):
                key = "l_" + "C" + `c1` + "_" + "S" + `s1`
                link_list[ pathID ].append( key )
                key = "l_" + "C" + `c2` + "_" + "S" + `s2`
                link_list[ pathID ].append( key )

            # Intra-Switch links
            key = "l_" + "S" + `s1` + "_" + "N" + `i`
            link_list[ pathID ].append( key )
            key = "l_" + "S" + `s2` + "_" + "N" + `j`
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

def link_create_reservation (links, paths, link_list, link_res, req):
        
    #print "paths=", json.dumps(paths, indent=4)
    #print "links=", json.dumps(links, indent=4)
    #print "link_list=", json.dumps(link_list, indent=4)
    #print "link_res=", json.dumps(link_res, indent=4)
    #print "req=", json.dumps(req, indent=4)
    
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
    
    if 'Bandwidth' not in req['Attributes']:
       raise Exception("Bandwidth attribute required!")
    bandwidth = req['Attributes']['Bandwidth']
    if bandwidth <= 0:
       raise Exception("Invalid bandwidth %.2f requested!" % bandwidth)
    
    # check first if there is enough bandwidth in each link
                      
    for linkID in link_list[ pathID ]:
       if bandwidth > links[ linkID ]["Attributes"]["Bandwidth"]:
          raise Exception("Not enough bandwidth (%.2f) in path: %s" % (bandwidth, pathID))

    for linkID in link_list[ pathID ]:      
       links[ linkID ]["Attributes"]["Bandwidth"] = links[ linkID ]["Attributes"]["Bandwidth"] - bandwidth 
 
    resID = str(uuid.uuid1())
     
    link_res[resID] = { "pathID": pathID, "bandwidth": bandwidth }
       
    calculate_attribs(paths, link_list, links)
    
    return resID
    
def link_release_reservation (links, paths, link_list, link_res, resIDs):

    for resID in resIDs:
    
        if resID not in link_res:
           raise Exception("Cannot find reservation ID: %s" % resID)
        
        pathID    = link_res[ resID ]["pathID"]
        bandwidth = link_res[ resID ]["bandwidth"]

        # Iterate all physical links within the path-resource
        # Add back the released bandwidth
        for linkID in link_list[ pathID ]:
            links[ linkID ]["Attributes"]["Bandwidth"] = links[ linkID ]["Attributes"]["Bandwidth"] + bandwidth

        # Remove reservation from list
        del( link_res[resID] )


    calculate_attribs(paths, link_list, links)

    return { }

def link_check_reservation (link_res, resIDs):
    result = { }
    for resID in resIDs:
    
        if resID not in link_res:
           raise Exception("Cannot find reservation ID: %s" % resID)
           
        result[resID] = { "Ready": "True", "Address": ["path://%s" % resID] }
        
    return { "Instances": result }
         


