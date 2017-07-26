import json
import os           # to get current path
import subprocess   # to get IPs through nova calls
import time         # to retry when ssh fails

import re           # grep IPs using regex
import paramiko     # ssh remote commands
import sys          # get last exception message

import logging, logging.handlers as handlers

## Logger handler
logger = logging.getLogger("Rotating Log")

## Current folder
irm_net_path = os.path.dirname(os.path.abspath(__file__))

################################## Lib Stuff - Start ##################################

#
# Function:
#   install_traffic_rules
# Purpose:
#   Install a SINGLE traffic rule between two hosts during a CRS reservation.
#   FIXME this assumes that a tenant does not reserve two containers
#   on the SAME host machine. The behavior is undefined in this case.
# Parameters:
#   @sourceHost         Hostname of machine to install the traffic rules (e.g., paranoia-1)
#   @targetHost         Hostname of machine to impose a bandwidth limitation with @sourceHost
#   bandwidth               (int) Bandwidth cap in Mbit/sec
#   reservedLinkResouces    List of the reserved Machine Resources in this CRS reservation.
#                           Used to translate hostnames to machine IDs.
#
def install_traffic_rules( sourceHost, targetHost, bandwidth, ReservedMachineResources ):

    #print "sourceHost:", sourceHost
    #print "targetHost:", targetHost
    #print "ReservedMachineResources: ", ReservedMachineResources

    #ReservedMachineResources:  [{'Host': u'compute-001', 'Type': u'Machine',
    # 'ID': u'ac244a32-2913-49a4-bbb2-07a627bdb101'}, {'IP': u'192.168.13.42',
    #'Host': u'web-wikipedia', 'Type': u'Web-Wikipedia', 'ID': u'web-wikipedia'}]

    #
    # Iterate @ReservedMachineResources and find the IDs.
    # FIXME we assume that there is a 1-1 match between hosts and containers.
    # TODO scenario when two containers are on the same host.
    # json format of each machine element in @ReservedMachineResources:
    #   {"Host" : compute-host, "ID": ID of container}
    #

    sourceIP = None
    targetIP = None
    sourceType = None
    targetType = None
    for resource in ReservedMachineResources:
        if resource["Host"] == sourceHost :
            sourceType = resource["Type"]
            if sourceType == "Machine":
                sourceIP = get_private_IP_from_ID(resource["ID"])
                sourceFIP = get_public_IP_from_ID(resource["ID"])
            else:
                sourceIP = resource["IP"]
        if resource["Host"] == targetHost :
            targetType = resource["Type"]
            if targetType == "Machine":
                targetIP = get_private_IP_from_ID(resource["ID"])
                targetFIP = get_public_IP_from_ID(resource["ID"])
            else:
                targetIP = resource["IP"]

        if sourceIP is not None and targetIP is not None \
                and sourceFIP is not None and targetFIP is not None:
            break

    if not sourceIP or not targetIP :
        raise Exception("Could not find Private IPs for resources " + sourceHost + ", " + targetHost)
    if not sourceFIP or not targetFIP :
        raise Exception("Could not find Public IPs for resources " + sourceHost + ", " + targetHost)

    #
    # Install rules on both containers
    #
    if sourceType == "Machine":
       traffic_rules_propagate( sourceFIP, targetIP, [bandwidth] )

    if targetType == "Machine":
       traffic_rules_propagate( targetFIP, sourceIP, [bandwidth] )


#
# Parameters:
#   @srcIP          Public  IP of container where the rules will be installed
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

    # Connect to the container
    retry = 50
    connected = False
    while not connected and retry > 0:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect( srcIP, username='root', password='contrail' )
            connected = True
        except:
            connected = False
            retry = retry - 1
            logger.info("Unknown exception: %s", sys.exc_info()[0])


    # Execute the command
    stdin, stdout, stderr = client.exec_command( tcCommand )
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

    # Close the connection
    client.close()

    # Abort if failed
    if ( retry <= 0 ):
        raise Exception("Could not connect to " + srcIP)

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


################################## Lib Stuff - End ####################################
