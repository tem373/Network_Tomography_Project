import sys
import argparse
import csv
import os
import glob
import time

import matplotlib.pyplot as plt
import numpy as np

from network import *
from host import *
from algorithms import *
from packet import *

################################################################################
############################### Argparse Setup #################################
################################################################################

def check_recvrs(num_recvrs):
    if (num_recvrs not in ['2', '4', '8', '16', '32', '64', '128', '256']):
        raise argparse.ArgumentTypeError("Available experiments are 2^n up to 2^n = 128 receivers")
    return num_recvrs

def check_mode(mode):
    if (mode not in ["sdn", "tomography"]):
        raise argparse.ArgumentTypeError("Run in either <sdn> (smart router) or <tomography> mode")
    return mode

# Argparse section to take in specified parameters from command-line
parser = argparse.ArgumentParser(description="Network Tomography Simulator with Bernoulli losses.")
optional_args = parser._action_groups.pop()

# Required Args
required_args = parser.add_argument_group("Required Arguments:")
required_args.add_argument('--ticks', dest='ticks', type=int, 
    help='How many rounds of packet traffic to send', required=True)

# Optional Args
optional_args.add_argument('--num_recvrs', dest='num_recvrs', type=check_recvrs,
    help='Specify number of receivers for this experiment', required=False, default=2)

optional_args.add_argument('--mode', dest='mode', type=check_mode,
    help='Run in either <tomography> or <sdn> mode', required=False, default="tomography")
parser._action_groups.append(optional_args)

# Argument Parsing
args = parser.parse_args()
print(args)


################################################################################
###################### Network Topology Setup Functions ########################
################################################################################

def network_setup(num_recvrs):
    """Sets up the network topology based on a max-heap structure for the 
    hosts and links"""

    link_array = []
    host_array = []

    ######## LINK SETUP ########
    total_links = 2 * num_recvrs                    # omit initial link
    bernoulli_array = bernoulli_setup(total_links, 0.1) # Can change this to change true alpha

    # IF YOU WANT TO EDIT THE BERNOULLIS BY HAND, DO SO HERE
    #
    # IF YOU WANT TO EDIT THE BERNOULLIS BY HAND, DO SO HERE

    for i in range(0, total_links):
        if (i == 0):
            link_array.append(Link(0.0))    # Initial link will never fail (alpha = 0)
        else:
            link_array.append(Link(bernoulli_array[i]))

    ######## NODE SETUP ########    
    # Receiver setup
    receiver_array = []
    for j in range(0, num_recvrs):
        name = 'receiver{}'.format(j+1)
        receiver_array.append(Host(name))

    # Router setup
    router_array = []
    for k in range(0, num_recvrs): #in a heap the receivers are 1/2 of the nodes
        if (k == 0):
            name = 'sender'
        else:
            name = 'router{}'.format(k)
            
        router_array.append(Host(name))

    # Concatenate the router and receiver lists
    host_array = router_array + receiver_array

    # Connect the nodes
    incr = num_recvrs-1       # start at the last router and work down
    while(incr > 0):
        node = host_array[incr]
        if (incr > 0):
            node.downstream_nodes.append(host_array[(2 * incr)])
            node.downstream_nodes.append(host_array[(2 * incr) + 1])

        elif (incr == 0):
            node.downstream_nodes.append(host_array[incr+1])    # sender has only 1 node

        incr = incr - 1

    return link_array, host_array


def bernoulli_setup(total_links, default_bernoulli):
    """Creates an array containing the link bernoulli drop probabilities
    TODO: add ability for user to customize from the command line"""

    bernoulli_array = []

    for i in range(0, total_links):
        bernoulli_array.append(default_bernoulli)

    return bernoulli_array


def tomography_reporting(tick, host_array, yhat_dict, gamma_dict, alpha_dict):
    """Encapsulation of the tomography reporting, to be run inside 
    run_simulation()"""

    print("Probe: " + str(tick))  

    for host in host_array:
        yhat, gamma, alpha = est_bernoulli_prob(host, yhat_dict, gamma_dict, alpha_dict, tick, host_array)

        yhat_dict[host.name].append(yhat)
        gamma_dict[host.name] = gamma
        alpha_dict[host.name].append(alpha)


def sdn_reporting(tick, host_array, link_array, alpha_dict):
    """Encapsulation of the SDN reporting, to be run inside run_simulation()"""


    print("Probe: " + str(tick))

    for i in range(0, len(host_array)):
        host = host_array[i]
        incoming_link = link_array[i]
        alpha_dict[host.name].append(incoming_link.loss_rate())


def run_simulation(ticks, link_array, host_array, yhat_dict, gamma_dict, alpha_dict):
    """A note on how the simulation runs: the links and nodes are stored as
    heaps in arrays. When the simulation runs, the links simply send to the 
    router sharing their incremented position in the array. See the below 4 recv example:

    R = [s, r1, r2,  r3,  rv1, rv2, rv3, rv4]
         ^   ^   ^    ^    ^    ^    ^    ^
         |   |   |    |    |    |    |    |
    L = [i, sr, r12, r13, rv1, rv2, rv3, rv4]
    """

    start_time = time.time()

    num_recv = int(len(host_array) / 2)
    num_other = num_recv

    for tick in range(0, ticks):

        # Run the traffic through the network
        first_packet = Packet(tick)
        for i in range(0, len(link_array)):     # Run through all links

            # Initial link
            if (i == 0):
                link_array[i].recv(first_packet)
            
                # All links perform this step
            link_array[i].tick(tick, host_array[i])
            
            # Sender performs this step (since it has only 1 downstream node)
            if (i == 0):
                link = link_array[i+1]
                host_array[i].send(tick, link)            

            # All <routers> must perform this step (but not sender or receivers)
            if (i > 0 and i < num_other):
                # Create the two downstream links to the node
                # Links after sender are located at 2i and 2i+1 (heap property)                    
                link1 = link_array[(2 * i)]
                link2 = link_array[(2 * i) + 1]                
                host_array[i].send(tick, link1, link2)                
        
        # Reset sender to be ready to send
        host_array[0].ready_to_send = True

        # Estimation - Tomography
        if(args.mode == 'tomography'):
            tomography_reporting(tick, host_array, yhat_dict, gamma_dict, alpha_dict)

        # Estimation - SDN
        if(args.mode == 'sdn'):
            sdn_reporting(tick, host_array, link_array, alpha_dict)

    print("Simulation ran in %s milliseconds" % ((time.time() - start_time) * 1000))


################################################################################
############################ Reporting Functions ###############################
################################################################################

def enum_tree_structure(host_array, link_array):
    """Uses graphviz program to create a .gv file (must be compiled separately)
    to illustrate the structure of the tree. Mostly created to help keep track 
    of large trees."""

    filepath = "results/graph_structure.gv"
    filestring = "digraph {\n"

    string_fragment = ""

    # Run through the tree and append to the filestring
    for i in range(0, int(len(host_array)/2)):       
        host = host_array[i]

        # Handle sender case 
        if (host.name == 'sender'):
            link = link_array[i+1]
            next_host = host_array[i+1]
            string_fragment = string_fragment + "\t{} -> {}[label=\"{}\",weight=\"{}\"];\n".format(host.name, next_host.name, link.bernoulli_alpha, link.bernoulli_alpha)

        # Handle router cases
        else:
            link1 = link_array[(2*i)]
            link2 = link_array[(2*i)+1]
            nexthost1 = host_array[(2*i)]
            nexthost2 = host_array[(2*i)+1]

            frag1 = "\t{} -> {}[label=\"{}\",weight=\"{}\"];\n".format(host.name, nexthost1.name, link1.bernoulli_alpha, link1.bernoulli_alpha)
            frag2 = "\t{} -> {}[label=\"{}\",weight=\"{}\"];\n".format(host.name, nexthost2.name, link2.bernoulli_alpha, link2.bernoulli_alpha)
            string_fragment = string_fragment + frag1 + frag2

    # Write the filestring into the file    
    filestring = filestring + string_fragment
    filestring = filestring + '}\n'

    with open(filepath, 'w') as outfile:
        outfile.write(filestring)

    # To run the file
    print("To generate the graph in .png format, run: ")
    print("dot -Tpng -O results/graph_structure.gv")


def convergence_report():
    """Reports the tick on which each estimation algorithm can be said to 
    converge to within 1% of the true value"""
    pass


def graph_convergence_path(host_array, alpha_dict, ticks):

    # Graph 4 hosts per graph
    num_hosts = len(host_array)
    iterations = int(num_hosts / 4)

    x_axis_vals = np.arange(ticks)

    for i in range(0, iterations):

        plt.plot(x_axis_vals, alpha_dict[host_array[(4*i)].name])
        plt.plot(x_axis_vals, alpha_dict[host_array[(4*i)+1].name])
        plt.plot(x_axis_vals, alpha_dict[host_array[(4*i)+2].name])
        plt.plot(x_axis_vals, alpha_dict[host_array[(4*i)+3].name])
        
        # Create labels
        plt.ylabel("Estimated loss value (%)")
        plt.ylim(0.0, 0.5)
        plt.xlabel("Sent packets")
        plt.title("Algorithm Convergence Comparison")
        plt.legend([host_array[(4*i)].name, host_array[(4*i)+1].name, host_array[(4*i)+2].name, host_array[(4*i)+3].name], loc='upper left')

        graphpath = 'results/graph' + str(i) + '.png'
        plt.savefig(graphpath)
        plt.clf()


################################################################################
################################ Setup and Run #################################
################################################################################

num_recvrs = int(args.num_recvrs)
link_heap, host_heap = network_setup(num_recvrs)
yhat_dict = {}
gamma_dict = {}
alpha_dict = {}
    
for host in host_heap:
    # yhat_dict
    yhat_dict[host.name] = []    
    # gamma_dict
    gamma_dict[host.name] = 0
    # alpha_dict
    alpha_dict[host.name] = []

run_simulation(args.ticks, link_heap, host_heap, yhat_dict, gamma_dict, alpha_dict)


################################################################################
################################# Reporting ####################################
################################################################################

# Delete results of last run so not to confuse current results
files = glob.glob('results/*')
for f in files:
    os.remove(f)

# Graph results of convergence
graph_convergence_path(host_heap, alpha_dict, args.ticks)

#for host in host_heap:
#    print(host.name + " Yhat:  " + str(yhat_dict[host.name]))
#    print(host.name + " gamma: %.4f" % gamma_dict[host.name])
#    formatted_alpha = ['%.4f' % elem for elem in alpha_dict[host.name]]
#    print(host.name + " alpha: " + str(formatted_alpha))

for host in host_heap:
    with open('results/' + host.name + '.csv', 'w') as outfile:
        for item in alpha_dict[host.name]:
            outfile.write(str(item))
            outfile.write('\n')

# Graph tree structure
enum_tree_structure(host_heap, link_heap)
