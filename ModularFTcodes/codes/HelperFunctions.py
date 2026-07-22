import numpy as np
import json
import networkx as nx
from itertools import islice
import random
import json
import networkx as nx
import matplotlib.pyplot as plt
from decimal import Decimal
from copy import deepcopy
from collections import defaultdict
from functools import partial
from deap import base, creator, tools, algorithms
import random
import time
import plotly.graph_objects as go
import plotly.express as px
import os, json
from collections import defaultdict
from typing import Dict, Any


       
################################################################### Helper functions ######################################################################################

def Read_Parent_AM(json_data):     # Returning a dictionary about the Application graph
  AMx = json_data['application']
  #print("The Parent AM is ",AMx)
  return AMx

def Read_Parent_PM(json_data):     # Returning a dictionary about the Platform graph
  PMx = json_data['platform']
  return PMx

def read_application_model(FullAMAddress):
    with open(FullAMAddress) as f:
        app_model = json.load(f)
    return app_model

# Function to read the Platform Model from the JSON file 
def read_platform_model(FullPMAddress):
    with open(FullPMAddress) as pf:
        pltf_model = json.load(pf)
    PMl = pltf_model['platform']
    return PMl


########################################################################################################################
# Returns a list of messages preserving real task IDs (not their indices)
def extract_message_list(APP_MODEL):
    messages = APP_MODEL['messages']
    message_list = []
    for msg in messages:
        message_info = {
            'id': msg['id'],
            'sender': msg['sender'],     # <== Real ID, untouched
            'receiver': msg['receiver'], # <== Real ID, untouched
            'size': msg['size']
        }
        message_list.append(message_info)
    return message_list
###########################################################################################################################


###############################################################################################################################
# Extract the schedule endtime
def compute_makespan(schedule):    # passing the Re-construction function result
    
    end_times = [info[2] for info in schedule.values()]
    # The makespan is the maximum end time
    makespan = max(end_times)
    return makespan
###############################################################################################################################



##################################################################################################################################
# Function for constructing the PM , returns a graph object
def construct_graph_from_json(PLAT_MODEL):         
    # Extract nodes and links from JSON data
    nodes = PLAT_MODEL['nodes']
    links = PLAT_MODEL['links']

    # Create an empty graph
    graph = nx.Graph()

    # Add nodes to the graph
    for node in nodes:
        node_id = node['id']
        node_type = 'processor' if not node['is_router'] else 'switch'
        graph.add_node(node_id, node_type=node_type)

    # Add edges (links) to the graph
    for link in links:
        start = link['start']
        end = link['end']
        graph.add_edge(start, end)

    return graph


    path_indexes = {}                             # Initialzing a dict. to store results (paths and costs)
    path_id = 0
    for source in processors:                     # iterating through the processors list in the PM [0,1,2]
        for target in processors:                 # iterating through processors list in PM [0,1,2], done to consider all pairs between source and target nodes
            if source == target:
                # Handle self-loop
                path_indexes[path_id] = {"path": [source, source], "cost": 0}
                path_id += 1
            else:
                all_paths = find_all_paths(source, target)
                all_paths = [path for path in all_paths if any(node in path for node in switches)] # filtering the paths to keep the ones with only one switch node
                if all_paths:
                    for path in all_paths:
                        # Compute the cost as the number of edges in the path
                        path_cost = len(path) - 1                                   # Computing the cost by subtracting 1 from the number of nodes in the path.
                        # Add the path, its ID, and its cost to the result
                        path_indexes[path_id] = {"path": path, "cost": path_cost}
                        path_id += 1
    return path_indexes
###################################################################################################################################



#########################################################################################################################################
# Function to get the processor IDs from the platform model
def get_processor_ids(data):
    processor_ids = [node['id'] for node in data['platform']['nodes'] if not node['is_router']]
    return processor_ids
########################################################################################################################################

######################################################################################################################################
# Plot schedule with the messages 
def plot_schedule_w_dep_full(schedule, message_list):
    task_list = sorted(schedule.items(), key=lambda x: x[1][0])
    task_to_y = {task_id: idx for idx, (task_id, _) in enumerate(task_list)}
    processors = sorted(set(p for p, _, _, _ in schedule.values()))
    color_map = {p: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)] for i, p in enumerate(processors)}

    fig = go.Figure()
    processor_to_trace_idxs = {p: [] for p in processors}
    seen_processors = set()
    trace_idx = 0

    # Add task bars with legend only once per processor
    for task_id, (processor, start, end, _) in task_list:
        y = task_to_y[task_id]
        show_legend = processor not in seen_processors
        seen_processors.add(processor)

        bar = go.Bar(
            x=[end - start],
            y=[y],
            base=start,
            orientation='h',
            marker=dict(color=color_map[processor]),
            hovertemplate=f"Task: {task_id}<br>Processor: {processor}<br>Start: {start}<br>End: {end}<extra></extra>",
            name=f"Processor {processor}",
            showlegend=show_legend
        )
        fig.add_trace(bar)
        processor_to_trace_idxs[processor].append(trace_idx)
        trace_idx += 1

    # Add directional arrows using annotations
    annotations = []
    for msg in message_list:
        s, r = msg['sender'], msg['receiver']
        if s in task_to_y and r in task_to_y:
            sx = schedule[s][2]
            sy = task_to_y[s]
            rx = schedule[r][1]
            ry = task_to_y[r]
            if abs(sx - rx) < 5:
                rx = sx + 10
            arrow_offset = 0.2
            annotations.append(dict(
                ax=sx, ay=sy + arrow_offset,
                x=rx, y=ry + arrow_offset,
                xref="x", yref="y",
                axref="x", ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.5,
                arrowwidth=1.2,
                arrowcolor="black",
                opacity=0.6
            ))

    # Dropdown filtering buttons
    buttons = [
        dict(
            label="All Processors",
            method="update",
            args=[
                {"visible": [True] * trace_idx},
                {"title": "All Processor Tasks"}
            ]
        )
    ]
    for p in processors:
        visibility = [False] * trace_idx
        for idx in processor_to_trace_idxs[p]:
            visibility[idx] = True
        buttons.append(
            dict(
                label=f"Processor {p}",
                method="update",
                args=[
                    {"visible": visibility},
                    {"title": f"Tasks for Processor {p}"}
                ]
            )
        )

    # Final layout
    fig.update_layout(
        title="Interactive Task Schedule with Dependencies and Filter",
        xaxis=dict(title="Time", showgrid=True, gridcolor='lightgray', gridwidth=1),
        yaxis=dict(
            title="Task",
            showgrid=True,
            gridcolor='lightgray',
            gridwidth=1,
            tickmode='array',
            tickvals=list(task_to_y.values()),
            ticktext=[f"Task {task_id} ({schedule[task_id][0]})" for task_id in task_to_y],
            autorange="reversed"
        ),
        height=max(600, 25 * len(task_to_y)),
        plot_bgcolor='white',
        hovermode="closest",
        annotations=annotations,
        updatemenus=[
            dict(
                buttons=buttons,
                direction="down",
                showactive=True,
                x=1.05,
                xanchor="left",
                y=1.15,
                yanchor="top"
            )
        ],
        legend_title="Processors",
        legend=dict(
            orientation="v",
            x=1.05,
            y=1,
            xanchor="left",
            yanchor="top"
        )
    )

    fig.show()
###################################################################################################################################    
    
#################################################################################################################################    
"""
Count how many tasks are assigned to each processor.

Args:
    schedule (dict): Dictionary with format:
                        {task_id: (processor, start_time, end_time, [dependencies])}

Returns:
    dict: A mapping of processor IDs to the number of tasks assigned to them.
"""
def count_tasks_per_processor(schedule):
    processor_count = {}

    for task_id, (processor, start_time, end_time, deps) in schedule.items():
        if processor in processor_count:
            processor_count[processor] += 1
        else:
            processor_count[processor] = 1

    return processor_count
################################################################################################################################


###############################################################################################################################
"""
Calculates the makespan (maximum finish time) for a partition based on job end times.

Parameters:
- list_schedule: List of tuples in the format (job_id, processor_id, start_time, end_time)
- partition_data: Dictionary parsed from JSON, containing jobs in a partition

Returns:
- A dictionary mapping each job ID to its end time
- The maximum end time (makespan) across all jobs in the partition
"""
def calculate_partition_makespan(list_schedule, partition_data):

    # Create a lookup for end times
    job_end_times = {job_id: end for (job_id, _, _, end) in list_schedule}

    job_times = {}
    max_finish_time = 0

    for job in partition_data["application"]["jobs"]:
        job_id = job["id"]
        if job_id in job_end_times:
            job_times[job_id] = job_end_times[job_id]
            max_finish_time = max(max_finish_time, job_end_times[job_id])
        else:
            job_times[job_id] = None  # Mark as missing if job_id isn't in schedule

    return job_times, max_finish_time
###############################################################################################################################

###############################################################################################################################
# Function to extract the Communication Cost from the Application model.
def communication_costs_task(json_data):
    messages = json_data['application']['messages']
    communication_costs = {}

    for message in messages:
        sender = message['sender']
        receiver = message['receiver']
        size = message['size']
        communication_costs[(sender,receiver)] = size

    return communication_costs
##############################################################################################################################

##############################################################################################################################
# Function to find the processing time for each job in the application model
def finding_ProcessTime(APP_MODEL):
    #  Function to find the the processing time  for each job
    
    jobs = APP_MODEL['application']['jobs']
   
    # Extract the processing values
    proc_time = {}
    for job in jobs:
        job_id = job['id']
        proc_time[job_id] = job['processing_times']  # extracting the processing time for each job
    


    return proc_time  # returning the task_dag and the processing time for each job
###############################################################################################################################

##################################################################################################################################
# Function to find the processors in the platform model
def find_processors(PM):
    processors = []
    for i in range(len(PM['nodes'])):
        if PM['nodes'][i]['is_router'] == False:
            processors.append(PM['nodes'][i]['id'])
    return processors
##################################################################################################################################

##################################################################################################################################
def calculate_earliest_start_time(graph, processing_time, communication_costs ):
    earliest_start_time = {}
    for task in nx.topological_sort(graph):
        max_comm_time = 0
        for sender, receiver in graph.in_edges(task):
            max_comm_time = max(max_comm_time, earliest_start_time[sender] + communication_costs[(sender, receiver)])
        earliest_start_time[task] = max_comm_time
    return earliest_start_time
#################################################################################################################################


#################################################################################################################################
def plot_graph(vertex_edge_pairs):
    G = nx.DiGraph()
    for v,e in vertex_edge_pairs:
        G.add_edge(v,e)
   
    pos = nx.spring_layout(G, k=30)
    plt.figure(figsize=(18, 15))
    if True:
        nx.draw(G, with_labels=True, node_size=500, node_color='lightblue', font_size=10, font_color='black', arrowsize=10)
        # plt.show()
    return G
###################################################################################################################################

#################################################################################################################################
def find_sender_receiver_pairs_tuple(sender_receiver_pair):
    vertex_edge_pairs = []

    for source, targets in sender_receiver_pair.items():
        for target in targets:
            vertex_edge_pairs.append((source, target))
    return vertex_edge_pairs
################################################################################################################################


################################################################################################################################
def find_sender_receiver_pairs(AM):
    sender_receiver_pair = {}
    for sd_re in AM["application"]["messages"]:
        sender = sd_re["sender"]
        receiver = sd_re["receiver"]
        if sender not in sender_receiver_pair:
            sender_receiver_pair[sender] = [receiver]
        else:
            sender_receiver_pair[sender].append(receiver)
    return sender_receiver_pair
###############################################################################################################################


################################################################################################################################
def construct_task_dag_from_json(APP_MODEL): # where APP_MODELis an instance from the function Read_Parent_AM(json_data)
    # this function returns 2 lists one for task_dag (list of lists) for the successors
    # Another list tis the wcet_values showing the worst excution times for each job
    jobs = APP_MODEL['jobs']
    messages = APP_MODEL['messages']

    num_tasks = len(jobs)

    # Create a mapping of sender and receiver tasks for each message
    message_mapping = {}
    for message in messages:
        sender = message['sender']
        receiver = message['receiver']
        if sender not in message_mapping:
            message_mapping[sender] = [receiver]
        else:
            message_mapping[sender].append(receiver)

    # Create the task DAG
    task_dag = [[] for _ in range(num_tasks)]

    for job_id, successors in message_mapping.items():
        task_dag[job_id] = successors

    # Extract the WCET values
    wcet_values = [job['processing_times'] for job in jobs]

    return task_dag, wcet_values
#############################################################################################################################

################################################################################################################################
def get_partition_processing_times(partition_data):
    jobs = partition_data['jobs']
    wcet_values = [job['processing_times'] for job in jobs]

    return  wcet_values
##############################################################################################################################

#################################################################################################################################
def list_scheduling(graph, processing_time, communication_costs, processors ):
    # Calculate earliest start time for each task
    earliest_start_time = calculate_earliest_start_time(graph, processing_time, communication_costs)
    #print("Earlist Start Time",earliest_start_time)
    # Initialize the finish time for each processor
    finish_time = {processor: 0 for processor in processors}
    
    
    # Initialize the schedule list
    schedule = []
    mk = []
    # Iterate through each task in topological order
    for task in nx.topological_sort(graph):
        min_finish_time =    float('inf')
        selected_processor = None
        selected_start_time = None
        #print("Min Finish Time",min_finish_time)
         
        
        # Find the processor with the minimum finish time
        for processor in processors:

                #start_time = max(earliest_start_time[task], finish_time[processor])
                #finish_time_task = start_time + processing_time[task]  
                #print(start_time, finish_time_task, processor,task)
                #if finish_time_task < min_finish_time:
                #    min_finish_time = finish_time_task
                #    selected_processor = processor
                    
                #    processor_assigned.append(processor)
            
            #elif (len(processor_assigned) == len(processors)):
            #    processor_assigned = []

            start_time = max(earliest_start_time[task], finish_time[processor])
            finish_time_task = start_time + processing_time[task] + 50*random.randint(18,20)# adding a random number to accound the cost of processor communication
            #print(start_time, finish_time_task, processor,task)
            if finish_time_task < min_finish_time:
                min_finish_time = finish_time_task
                selected_processor = processor
                selected_start_time = start_time
            
        
        # Update finish time for the selected processor
        finish_time[selected_processor] = min_finish_time
        #print("Finish Time",finish_time)
        mk.append(min_finish_time)
        
        # Append task and processor to the schedule
        schedule.append((task, selected_processor, selected_start_time, min_finish_time))
        max_time = max(mk)
    return schedule, max_time
##################################################################################################################################


###################################################################################################################################
# def compute_paths_cloud_costs(json_data, k=4):
#     """
#     Compute merged diverse k-shortest paths between processing nodes in a three-tier platform,
#     applying constraints on intermediate routers based on the endpoint types.
    
#     The following constraints are applied:
#       • For a cloud-to-cloud connection (e.g., P1002 to P1013) that are in the same cloud, 
#         intermediate nodes with IDs in {"RID1","RID2","RID3","RID4","RID5","RID6"} are disallowed.
#       • For a fog-to-fog connection (e.g., F101 to F102), disallow both {"RID1",...,"RID6"} and "RTSN1".
#       • For an edge-to-edge connection (e.g., P31 to P32), disallow "RTSN1".
#       • For any connection involving an edge, disallow "RTSN1" except in the specific allowed case
#         (edge-to-fog when the edge is P31 and the fog is F110).
#       • In all other cases, no additional router restrictions are applied.
    
#     In addition, the path cost is computed such that for each occurrence of any of the routers 
#     "RID1" through "RID6", the cost is increased by 10; other router nodes add a cost of 1.
    
#     Parameters:
#         json_data (dict): JSON data containing a "platform" key with "nodes" and "links".
#         k (int): The number of k-shortest paths to compute between any two processing nodes.
        
#     Returns:
#         dict: A dictionary (merged_paths_dict) mapping merged identifiers to a dictionary containing:
#               - 'path': a list of node ids representing the path.
#               - 'cost': an integer cost computed based on the path and router penalties.
#     """
    
#     # Extract nodes and links
#     nodes = json_data['platform']['nodes']
#     links = json_data['platform']['links']

#     # Create an undirected graph and add nodes (with is_router property) and edges
#     G = nx.Graph()
#     for node in nodes:
#         G.add_node(node['id'], is_router=node['is_router'])
#     for link in links:
#         G.add_edge(link['start'], link['end'])
    
#     # Get processing nodes (non-router nodes)
#     processor_nodes = [node['id'] for node in nodes if not node['is_router']]
    
#     # Helper functions to determine the type of a processing node
#     def get_proc_type(node_id):
#         # Fog nodes start with "F"
#         if node_id.startswith('F'):
#             return "fog"
#         # Edge processing nodes in this platform (e.g., "P31", "P32", etc.) are assumed to be short IDs.
#         elif node_id.startswith('P') and len(node_id) <= 3:
#             return "edge"
#         # Other "P" nodes are assumed to be cloud processing elements.
#         elif node_id.startswith('P'):
#             return "cloud"
#         else:
#             return None

#     def get_cloud_group(node_id):
#         # For cloud processing elements, use the digit at position 1 to determine cloud group.
#         # For example, "P1002" and "P1013" both belong to group "1" (cloud1),
#         # while "P1005" (cloud1) and "P3005" (cloud3) are in different groups.
#         return node_id[1] if node_id.startswith('P') and len(node_id) > 3 else None

#     def get_disallowed_nodes(source, target):
#         """
#         Return a set of router node ids that must not appear in the intermediate portion 
#         of a path from source to target.
#         """
#         disallowed = set()
#         s_type = get_proc_type(source)
#         t_type = get_proc_type(target)
        
#         # Cloud-to-cloud: if both are cloud and in the same group, disallow the RID routers.
#         if s_type == "cloud" and t_type == "cloud":
#             if get_cloud_group(source) == get_cloud_group(target):
#                 disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})
#         # Fog-to-fog: disallow both the cloud routers and the edge router.
#         if s_type == "fog" and t_type == "fog":
#             disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6", "RTSN1"})
#         # Edge-to-edge: disallow RTSN1.
#         if s_type == "edge" and t_type == "edge":
#             disallowed.update({"RTSN1"})
#         # For any connection involving an edge (except the allowed case), disallow RTSN1.
#         if s_type == "edge" or t_type == "edge":
#             if not ((source == "P31" and target == "F110") or (source == "F110" and target == "P31")):
#                 disallowed.add("RTSN1")
#         return disallowed

#     # Modified cost function: for each router in the path, if the router is one of {"RID1",...,"RID6"},
#     # add 10 to the cost; otherwise, add 1.
#     def path_cost(graph, path):
#         cost = 0
#         # Start from index 1 to avoid including the source node in cost computation.
#         for i in range(1, len(path)):
#             if graph.nodes[path[i]]['is_router']:
#                 if path[i] in {"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"}:
#                     cost += 10
#                 else:
#                     cost += 1
#         return cost
    
#     # Function to compute k-shortest paths using networkx's shortest_simple_paths on a given graph
#     def k_shortest_paths(graph, source, target, k):
#         return list(islice(nx.shortest_simple_paths(graph, source, target), k))
    
#     # Compute diverse k-shortest paths with their cost for given source and target on a given graph
#     def diverse_k_shortest_paths(graph, source, target, k):
#         paths = k_shortest_paths(graph, source, target, k)
#         return [(path, path_cost(graph, path)) for path in paths]

#     # Dictionaries to store the paths
#     paths_dict = {}
#     merged_paths_dict = {}
#     path_id = 1

#     # Calculate the k-shortest paths between all pairs of processing nodes with constraints.
#     for i in range(len(processor_nodes)):
#         for j in range(i + 1, len(processor_nodes)):
#             source = processor_nodes[i]
#             target = processor_nodes[j]
#             # Get the disallowed intermediate routers for this pair.
#             disallowed = get_disallowed_nodes(source, target)
#             # Create a restricted copy of the graph by removing disallowed nodes (but keep endpoints)
#             restricted_G = G.copy()
#             for node in disallowed:
#                 if node in restricted_G and node not in {source, target}:
#                     restricted_G.remove_node(node)
#             try:
#                 paths = diverse_k_shortest_paths(restricted_G, source, target, k)
#             except nx.NetworkXNoPath:
#                 paths = []  # No path found under constraints
            
#             # Build a sub-dictionary for this pair with individual sub-path ids.
#             sub_paths_dict = {}
#             for sub_path_id, (path, cost) in enumerate(paths):
#                 sub_paths_dict[sub_path_id] = {'path': path, 'cost': cost}
#                 # Merge path_id and sub_path_id into a single merged_id string (e.g., "10" for path_id=1 and sub_path_id=0)
#                 merged_id = f"{path_id}{sub_path_id}"
#                 merged_paths_dict[merged_id] = {'path': path, 'cost': cost}
#             paths_dict[path_id] = sub_paths_dict
#             path_id += 1

#     # Adding self-loops for each processing node (cost is 1)
#     for node in processor_nodes:
#         sub_paths_dict = {0: {'path': [node, node], 'cost': 1}}
#         paths_dict[path_id] = sub_paths_dict
#         merged_id = f"{path_id}0"
#         merged_paths_dict[merged_id] = {'path': [node, node], 'cost': 1}
#         path_id += 1

#     return merged_paths_dict
##################################################################################################################################

###################################################################################################################################
    """
    Compute merged diverse k-shortest paths between processing nodes in a three-tier platform,
    applying constraints on intermediate routers based on the endpoint types.
    
    The following constraints are applied:
      • For a cloud-to-cloud connection (e.g., P1002 to P1013) that are in the same cloud, 
        intermediate nodes with IDs in {"RID1","RID2","RID3","RID4","RID5","RID6"} are disallowed.
      • For a fog-to-fog connection (e.g., F101 to F102), disallow both {"RID1",...,"RID6"} and "RTSN1".
      • For an edge-to-edge connection (e.g., P31 to P32), disallow "RTSN1".
      • For any connection involving an edge, disallow "RTSN1" except in the specific allowed case
        (edge-to-fog when the edge is P31 and the fog is F110).
      • In all other cases, no additional router restrictions are applied.
    
    In addition, the path cost is computed such that for each occurrence of any of the routers 
    "RID1" through "RID6", the cost is increased by 10; other router nodes add a cost of 1.
    
    Parameters:
        json_data (dict): JSON data containing a "platform" key with "nodes" and "links".
        k (int): The number of k-shortest paths to compute between any two processing nodes.
        
    Returns:
        dict: A dictionary (merged_paths_dict) mapping merged identifiers to a dictionary containing:
              - 'path': a list of node ids representing the path.
              - 'cost': an integer cost computed based on the path and router penalties.
    """
def compute_paths_cloud_costs_2(json_data, k=4):
    """
    Compute merged diverse k-shortest paths between processing nodes in a three-tier platform,
    applying constraints on intermediate routers based on the endpoint types.
    """
    nodes = json_data['platform']['nodes']
    links = json_data['platform']['links']

    # Build the network graph
    G = nx.Graph()
    for node in nodes:
        G.add_node(node['id'], is_router=node['is_router'])
    for link in links:
        G.add_edge(link['start'], link['end'])

    # Get processing (non-router) nodes
    processor_nodes = [node['id'] for node in nodes if not node['is_router']]

    def get_proc_type(node_id):
        if node_id.startswith('F'):
            return "fog"
        elif node_id.startswith('E'):
            return "edge"
        elif node_id.startswith('P'):
            return "cloud"
        return None

    def get_cloud_group(node_id):
        return node_id[1] if node_id.startswith('P') and len(node_id) > 3 else None

    def get_disallowed_nodes(source, target):
        disallowed = set()
        s_type = get_proc_type(source)
        t_type = get_proc_type(target)

        # Same-cloud cloud-to-cloud: restrict RIDx routers
        if (s_type == "cloud" and t_type == "cloud") or (t_type == "cloud" and s_type == "cloud"):
            if get_cloud_group(source) == get_cloud_group(target):
                disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

        # Fog-to-fog: restrict RIDx and RTSN1
        if (s_type == "fog" and t_type == "fog") or (t_type == "fog" and s_type == "fog"):
            disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

        # Edge-to-edge: disallow RTSN1
        if (s_type == "edge" and t_type == "edge") or (t_type == "edge" and s_type == "edge"):
            disallowed.add("RTSN1")

        # Edge-to-fog: restrict inter-domain routers.
        if (s_type == "edge" and t_type == "fog") or (t_type == "fog" and s_type == "edge"):
            disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

        return disallowed

    def path_cost(graph, path):
        cost = 0
        for i in range(1, len(path)):
            if graph.nodes[path[i]]['is_router']:
                if path[i] in {"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"}:
                    cost += 10
                else:
                    cost += 1
        return cost

    def k_shortest_paths(graph, source, target, k):
        return list(islice(nx.shortest_simple_paths(graph, source, target), k))

    def diverse_k_shortest_paths(graph, source, target, k):
        paths = k_shortest_paths(graph, source, target, k)
        return [(path, path_cost(graph, path)) for path in paths]

    paths_dict = {}
    merged_paths_dict = {}
    path_id = 1

    for i in range(len(processor_nodes)):
        for j in range(i + 1, len(processor_nodes)):
            source = processor_nodes[i]
            target = processor_nodes[j]
            disallowed = get_disallowed_nodes(source, target)

            restricted_G = G.copy()
            for node in disallowed:
                if node in restricted_G and node not in {source, target}:
                    restricted_G.remove_node(node)

            try:
                paths = diverse_k_shortest_paths(restricted_G, source, target, k)
            except nx.NetworkXNoPath:
                paths = []

            sub_paths_dict = {}
            for sub_path_id, (path, cost) in enumerate(paths):
                sub_paths_dict[sub_path_id] = {'path': path, 'cost': cost}
                merged_id = f"{path_id}{sub_path_id}"
                merged_paths_dict[merged_id] = {'path': path, 'cost': cost}
            paths_dict[path_id] = sub_paths_dict
            path_id += 1

    # Self-loops
    for node in processor_nodes:
        sub_paths_dict = {0: {'path': [node, node], 'cost': 1}}
        paths_dict[path_id] = sub_paths_dict
        merged_id = f"{path_id}0"
        merged_paths_dict[merged_id] = {'path': [node, node], 'cost': 1}
        path_id += 1

    return merged_paths_dict

###################################################################################################################################


###################################################################################################################################
def get_paths_with_rid_routers(merged_paths_w_costs):
    """
    Extracts path IDs from the merged_paths_w_costs dictionary where the path includes
    any of the routers: RID1, RID2, RID3, RID4, RID5, RID6.
    
    Parameters:
        merged_paths_w_costs (dict): Dictionary of paths with their costs from compute_paths_cloud_costs().
        
    Returns:
        list: A list of merged path IDs (keys) where the path includes one of the RID routers.
    """
    rid_routers = {"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"}
    matching_ids = [
        path_id
        for path_id, data in merged_paths_w_costs.items()
        if any(node in rid_routers for node in data['path'])
    ]
    return matching_ids
####################################################################################################################################


