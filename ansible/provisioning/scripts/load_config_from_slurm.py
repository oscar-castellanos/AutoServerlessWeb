#!/usr/bin/python

import sys
from pathlib import Path
from ruamel.yaml import YAML
import os
import subprocess
import re
import yaml
from load_inventory_from_conf import write_container_list, get_disks_dict
import socket

def getHostList():
    rc = subprocess.Popen(["scontrol", "show", "hostnames"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = rc.communicate()
    hostlist = output.decode().splitlines()
    server = hostlist[0]
    hostlist.pop(0)

    server_ip = socket.gethostbyname(server)

    print("Server: {0}".format(server))
    print("Client nodes: {0}".format(hostlist))

    return server, server_ip, hostlist

def getNodesCpus():

    #export CPUS_PER_NODE=`grep "^physical id" /proc/cpuinfo | sort -u | wc -l`     # CPUs per node
    #export CORES_PER_CPU=`grep "^core id" /proc/cpuinfo | sort -u | wc -l` # Cores per CPU
    #export CORES_PER_NODE=$(( $CPUS_PER_NODE * $CORES_PER_CPU ))   # Cores per node

    cpus_per_node_string = os.getenv('SLURM_JOB_CPUS_PER_NODE')
    if cpus_per_node_string != "":
        try:
            cpus_per_node = int(cpus_per_node_string)
        except ValueError:
            # We assume that it has format: 16(x2)
            #formatted_cpus = cpus_per_node_string.replace('x','*').replace("(","").replace(")","")
            #cpus_per_node = eval(formatted_cpus)
            formatted_cpus = re.sub("[\(\[].*?[\)\]]", "", cpus_per_node_string)
            cpus_per_node = int(formatted_cpus)

            # TODO: check if the system actually has HT
            # adjust to hyperthreading system
            cpus_per_node = cpus_per_node * 2
    else:
        raise Exception("Can't get node CPUs")

    return cpus_per_node

# Not used ATM
def getNodesMemory_scontrol(server):
    rc = subprocess.Popen(["scontrol", "-o", "show", "nodes", server], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = rc.communicate()
    itemlist = output.decode().split(" ")

    allocMem = ""
    for item in itemlist:
        if "AllocMem" in item:
            # We assume that it has format: AllocMem=40960
            allocMem = int(item.split("=")[1])
    if allocMem == "":
        raise Exception("Can't get node Memory")

    return allocMem

def getNodesMemory():

    #export MEMORY_PER_NODE=$((`grep MemTotal /proc/meminfo | awk '{print $2}'`/1024))	# Total Memory per node

    job = os.getenv('SLURM_JOB_ID')
    #paramater_list = "JobID,AllocCPUs,MaxRSSNode,NCPUs,ReqMem,MinCPUNode"
    paramater_list = "ReqMem"

    #rc = subprocess.Popen(["sacct", "-j", job, "--format={0}".format(paramater_list), "-n", "-P", "--units", "M"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rc = subprocess.Popen(["grep", "MemTotal", "/proc/meminfo"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #rc = subprocess.Popen(["awk", "'{print $2}'"], stdin=get_mem.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = rc.communicate()
    #memlist = output.decode().splitlines()
    memlist = re.findall(r'\b\d+\b', output.decode())

    memory_factor = 0.9

    try:
        allocMem_string = memlist[0]

        # We assume it has format: 3800Mc
        #allocMem = int(re.sub(r'[^0-9]', '', allocMem_string))

        allocMem = int(int(int(re.sub(r'[^0-9]', '', allocMem_string)) / 1024) * memory_factor)

    except IndexError:
        raise Exception("Can't get node Memory")

    return allocMem

def getDisksFromConfig(config_file):

    with open(config_file, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    hdd_disks_per_client_node = config['hdd_disks_per_client_node']
    hdd_disks_path_list = config['hdd_disks_path_list'].split(",")
    ssd_disks_per_client_node = config['ssd_disks_per_client_node']
    ssd_disks_path_list = config['ssd_disks_path_list'].split(",")

    return get_disks_dict(hdd_disks_per_client_node, hdd_disks_path_list, ssd_disks_per_client_node, ssd_disks_path_list)

def update_config_file(config_file, server, server_ip, client_nodes, cpus_per_node, memory_per_node):
    #server_ip = server
    cpus_server_node = cpus_per_node
    memory_server_node = memory_per_node
    number_of_client_nodes = len(client_nodes)
    cpus_per_client_node = cpus_per_node
    memory_per_client_node = memory_per_node

    ## Change config file
    yaml_utils = YAML()
    yaml_utils.default_flow_style = False
    yaml_utils.preserve_quotes = True
    out = Path(config_file)
    data = yaml_utils.load(out)

    for elem in data:
        # General
        if elem == 'virtual_mode':
            data[elem] = "no"
        elif elem == 'container_engine':
            data[elem] = "apptainer"
        elif elem == 'cgroups_version':
            data[elem] = "v1"

        # Server
        elif elem == 'server_ip':
            data[elem] = server_ip
        elif elem == 'cpus_server_node':
            data[elem] = cpus_server_node
        elif elem == 'memory_server_node':
            data[elem] = memory_server_node

        # Client nodes
        elif elem == 'number_of_client_nodes':
            data[elem] = number_of_client_nodes
        elif elem == 'cpus_per_client_node':
            data[elem] = cpus_per_client_node
        elif elem == 'memory_per_client_node':
            data[elem] = memory_per_client_node

    yaml_utils.dump(data, out)
    #yaml_utils.dump(data, sys.stdout)

def update_inventory_file(inventory_file, server, client_nodes, cpus_per_node, memory_per_node, disks_dict):

    # Server
    with open(inventory_file, 'w') as f:
        content = ["[server]", server, "[nodes]",""]
        f.write("\n".join(content))

    # Nodes
    for host in client_nodes:
        write_container_list([],host,cpus_per_node,memory_per_node,disks_dict)

if __name__ == "__main__":

    scriptDir = os.path.realpath(os.path.dirname(__file__))
    config_file = scriptDir + "/../config/config.yml"
    inventory_file = scriptDir + "/../../ansible.inventory"

    # Get config values
    server, server_ip, client_nodes = getHostList()
    cpus_per_node = getNodesCpus()
    memory_per_node = getNodesMemory()
    disks_dict = getDisksFromConfig(config_file)

    # Change config
    update_config_file(config_file, server, server_ip, client_nodes, cpus_per_node, memory_per_node)

    # Update ansible inventory file
    update_inventory_file(inventory_file, server, client_nodes, cpus_per_node, memory_per_node, disks_dict)
