#!/bin/bash

# Usage: variables initialized as:
# VAR=__VAR
# have to be externally initialized through 'sed'


##########################
##	PARAMETERS	##
##########################

# Bandwidth capping for unmatched traffic
MINBW="10mbit"

# Line rate
MAXBW="10gbit"

# Rules to install:
# BWRATESTRING='[{"Target":"10.158.0.3","Rate":"100mbit"},{"Target":"10.158.0.4","Rate":"200mbit"},{"Target":"10.158.0.5","Rate":"300mbit"}]'
BWRATESTRING='__BWRATESTRING'


##########################
##	CONFIGURATION	##
##########################

# Name of the traffic control command.
TC=/sbin/tc

# The network interface we're planning on limiting bandwidth.
IF=$(/sbin/ifconfig | grep HWaddr | grep -v eth0 | awk '{print $1}')

# Filter options for limiting the intended interface.
U32="$TC filter add dev $IF protocol ip parent 1:0 prio 1 u32"
U32P7="$TC filter add dev $IF protocol ip parent 1:0 prio 7 u32"


##########################
##	FUNCTIONS	##
##########################

#
# Check if root is installed;
#
ROOTCHECK=$($TC qdisc ls dev $IF)
ROOTINSTALL=$(echo $ROOTCHECK | grep "htb 1:" -c)
NUMCLASSES=0

if [ $ROOTINSTALL -eq 0 ]; then

	#
	# Root HTB not installed; add it.
	# Also add parent class; nominal link rate;
	# no filters for this class.
	#
	$TC qdisc add dev $IF handle 1: root htb
	$TC class add dev $IF parent 1: classid 1:1 htb rate $MAXBW

	#
	# default class;
	# minimum guaranteed bandwidth for all
	# filters should have the lowest (higher numbered) priority
	#
	$TC class add dev $IF parent 1:1 classid 1:10 htb rate $MINBW
	$U32P7 match ip dst 0.0.0.0/0 flowid 1:10
	$U32P7 match ip src 0.0.0.0/0 flowid 1:10

	#
	# Number of rules: 1, the default.
	#
	NUMCLASSES=1
else
	#
	# There existing HTB rules;
	# count them
	#
	NUMCLASSES=$($TC class show dev $IF | grep -E 'class htb 1:[0-9]{2} parent' -c)
fi


#
# Sanity check: $BWRATESTRING must be defined
#
if [ -z "$BWRATESTRING" ]; then
	exit
fi

#
# Delete any previous rule that might exist
# Reset the rule root.
#
$TC qdisc del dev $IF root
$TC qdisc add dev $IF handle 1: root htb
$TC class add dev $IF parent 1: classid 1:1  htb rate 20000mbit

#
# Bandwidth shaping classes.
# Will have numerous sub-classes, one per rule.
#
# Takes @BWRATESTRING, a json in a single string
# We parse the string using python and the output is:
#	BWRATEARRAY[0] = "Target0;Rate0"
#	BWRATEARRAY[1] = "Target1;Rate1"
#	...
#	BWRATEARRAY[N] = "TargetN;RateN"
#
BWRATEARRAY=($(echo $BWRATESTRING | python3 -c 'import json,sys;obj=json.load(sys.stdin);[print(x["Target"],x["Rate"],sep=";") for x in obj]'))

MINORNUM=$(($NUMCLASSES * 10))
for TARGETBW in ${BWRATEARRAY[@]}; do
	TARGET=$(echo $TARGETBW | awk -F ';' '{print $1}')
	RATE=$(echo $TARGETBW | awk -F ";" '{print $2}')

	# Increase class minor number
	MINORNUM=$(( $MINORNUM + 10 ))

	$TC class add dev $IF parent 1:1 classid 1:$MINORNUM htb rate $RATE
	$U32 match ip dst $TARGET flowid 1:$MINORNUM

done
