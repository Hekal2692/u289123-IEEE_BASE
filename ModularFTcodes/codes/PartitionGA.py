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


import GAAux as gax
import config as cfg

import logging
log = logging.getLogger()

def reconstruct_schedule_with_precedenceX_updated(processor_ids, task_allocation, node_list, processing_times, message_list, message_path_index, all_path_indexes_with_costs, message_priority_ordering):
    # Create a deep copy of the message_list to avoid modifying the original data
    message_list_copy = deepcopy(message_list)

    schedule = {}
    task_completion_times = {task_id: 0 for task_id in node_list}  

    # schedule = {}  # Dictionary to store the new schedule
    # task_completion_times = [0] * len(node_list)  # List to store task completion times
    message_dict = defaultdict(list)  # Dictionary to store messages by receiver

    # Create a dictionary to map message ID to priority
    message_priority_dict = {message_id: priority for priority, message_id in enumerate(message_priority_ordering)}

    # Create a mapping from task ID to processor
    task_to_processor = {task_id: processor for task_id, processor in zip(node_list, task_allocation)}

    # Replace sender and receiver in message list with the corresponding processor
    updated_message_list = []  # Container for mapping the messages between the processors
    for message in message_list_copy:
        updated_message = {
            'id': message['id'],
            'sender': task_to_processor[message['sender']],
            'receiver': task_to_processor[message['receiver']],
            'size': message['size']
        }
        updated_message_list.append(updated_message)
    
    # Initialize the results list
    message_to_path_mapping = []

    # Initialize a dictionary to track the usage of path_ids
    path_usage = {path_id: 0 for path_id in message_path_index}

    # print('message_path_index in reconstruction' ,message_path_index)

    # Loop through each message and find the corresponding path
    for i, message in enumerate(updated_message_list):
        sender = message['sender']
        receiver = message['receiver']
        # Iterate through the message_path_index to find a matching path
        for path_id in message_path_index:
            # print(path_id)
            path_info = all_path_indexes_with_costs[path_id]

            path = path_info['path']
            
            # Check if the sender and receiver match the path's start and end
            if (path[0] == sender and path[-1] == receiver) or (path[-1] == sender and path[0] == receiver):
                # Check if this path has been used as many times as it appears in message_path_index
                if path_usage[path_id] < message_path_index.count(path_id):
                    message_to_path_mapping.append({'message_id': message['id'], 'path_id': path_id})
                    path_usage[path_id] += 1
                    break
    
    for idx, message in enumerate(message_list_copy):
        # Find the corresponding path_id from message_to_path_mapping
        message_mapping = next((m for m in message_to_path_mapping if m['message_id'] == message['id']), None)
        
        if message_mapping:
            path_id = message_mapping['path_id']
        else:
            path_id = '290'  # Set path_id to 290 if no mapping is found

        # Decode the path and cost using the path_id
        path = all_path_indexes_with_costs[path_id]["path"]
        path_cost = all_path_indexes_with_costs[path_id]["cost"]

        # Adjust the size of the message with the cost of the path
        message["size"] += path_cost

        # Append a tuple containing the sender, message size, message priority, path_id, and message_id to the receiver's list in the message_dict
        message_dict[message["receiver"]].append((message["sender"], message["size"], message_priority_dict[message["id"]], path_id, message["id"]))

        
    # Sort each receiver's list in message_dict by message priority
    for receiver, messages in message_dict.items():
        message_dict[receiver] = sorted(messages, key=lambda x: x[2])

    # print("The message_dict is ", message_dict)
    
    # current_time_per_processor = [0] * num_processors  # List to track current time for each processor
    current_time_per_processor = {pid: 0 for pid in processor_ids}

    
    completed_tasks = set()  # Set of completed tasks
    ready_tasks = set(range(len(node_list)))  # Set of tasks ready to be processed
    while ready_tasks:
        task = ready_tasks.pop()

        task_id = node_list[task]

        processor = task_allocation[task]
        # print("The processor inside the reconstruction is ", processor)
        # print(type(processor))  
        
        predecessors = message_dict[task_id]
        

        if all(p in completed_tasks for p, _, _, _, _ in predecessors):
            if predecessors:
                # Calculate the latest time when all predecessor tasks are completed including message sizes
                latest_predecessor_completion = max(
                    task_completion_times[sender] + size for sender, size, _, _, _ in predecessors
                )
                # Compare it with the current processor time and take the maximum
                start_time = max(current_time_per_processor[processor], latest_predecessor_completion)
            else:
                # If there are no predecessors, start at the current processor time
                start_time = current_time_per_processor[processor]    # error here 23.04.25

            # Calculate the total size of all messages from predecessors
            total_message_size = sum(size for _, size, _, _, _ in predecessors)

            # Calculate the end_time considering processing time and total message sizes
            end_time = start_time + processing_times[task_id]

            # Record the path information used by the predecessors
            path_info = [(sender, path_id, message_id) for sender, _, _, path_id, message_id in predecessors]
            schedule[task_id] = (processor, start_time, end_time, path_info)
            task_completion_times[task_id] = end_time


            # Update the current time of the processor to the end time of this task
            current_time_per_processor[processor] = end_time
            completed_tasks.add(task_id)
        else:
            ready_tasks.add(task)
            
    #print(message_path_index)
    
    return schedule




# def NEW_GA_V2(processor_ids, processing_times, message_list, all_path_indexes_with_costs, job_data , time_budget=None):
    
#     # Partition‐GA uses its own fitness & individual to avoid collision with System GA
#     if "PartFitness" not in creator.__dict__:
#         creator.create("PartFitness", base.Fitness, weights=(cfg.PartitionWeight,))
#     if "PartIndividual" not in creator.__dict__:
#         creator.create("PartIndividual", list, fitness=creator.PartFitness)


#     toolbox = base.Toolbox()

#     num_tasks = len(processing_times)
#     num_message = len(message_list)
#     predefined_processors = processor_ids
#     message_list_ids = [message['id'] for message in message_list]
#     valid_task_ids = list(job_data.keys())

#     def init_task_order():
#         return random.sample(valid_task_ids, len(valid_task_ids))

#     def processor_allocation(n_task, predefined_values):
#         return [random.choice(predefined_values) for _ in range(n_task)]

#     def message_priority_ordering(n_messages, defined_values):
#         return random.sample(defined_values, n_messages)

#     def init_message_path_index(n_messages):
#         return [random.choice([0, 1, 2, 3]) for _ in range(n_messages)]


#     def create_individual():
#         individual = []
#         individual.extend(toolbox.task_order())
#         individual.extend(toolbox.processor_allocation())
#         if num_message > 0:
#             individual.extend(toolbox.message_priority_ordering())
#             individual.extend(toolbox.message_path_index())
#         return individual

#     toolbox.register("task_order", init_task_order)
#     toolbox.register("processor_allocation", processor_allocation, n_task=num_tasks, predefined_values=predefined_processors)
#     if num_message > 0:
#         toolbox.register("message_priority_ordering", message_priority_ordering, n_messages=num_message, defined_values=message_list_ids)
#         toolbox.register("message_path_index", init_message_path_index, n_messages=num_message)
    
#     # toolbox.register("individual", tools.initIterate, creator.Individual, create_individual)
#     toolbox.register("individual", tools.initIterate, creator.PartIndividual, create_individual)

#     toolbox.register("population", tools.initRepeat, list, toolbox.individual)



#     def evaluate(individual , time_budget):
#         task_order = gax.repair_task_order(individual[:num_tasks], valid_task_ids)
#         # raw_processor_allocation = individual[num_tasks:2 * num_tasks]
#         # processor_allocation = gax.enforce_can_run_on_constraints(task_order, raw_processor_allocation, processor_ids, job_data)
        
#         raw_processor_allocation = individual[num_tasks:2 * num_tasks]
#         # processor_allocation, hard_violations = gax.enforce_can_run_on_constraints(
#         #     task_order, raw_processor_allocation, processor_ids, job_data, strict=True
#         # )
                
        
#         if num_message == 0:
#             schedule = {}
#             current_time_per_processor = {pid: 0 for pid in processor_ids}
#             for i, task_id in enumerate(task_order):
#                 proc = raw_processor_allocation[i]
#                 start = current_time_per_processor[proc]
#                 end = start + processing_times[task_id]
#                 schedule[task_id] = (proc, start, end, [])
#                 current_time_per_processor[proc] = end
#         else:
#             message_priority_ordering = individual[2 * num_tasks:2 * num_tasks + num_message]
#             message_path_index = individual[2 * num_tasks + num_message:]
#             updated_list = gax.ComputeMappingsAndPaths(message_list, task_order, raw_processor_allocation,
#                                                    message_priority_ordering, message_path_index)
#             selected_paths = gax.find_suitable_paths(updated_list, all_path_indexes_with_costs)
#             schedule = reconstruct_schedule_with_precedenceX_updated(
#                 processor_ids, raw_processor_allocation, task_order, processing_times,
#                 message_list, selected_paths, all_path_indexes_with_costs, message_priority_ordering)
            
#         makespan = gax.compute_makespan(schedule)
#         lateness = max(0, makespan - time_budget)

#         # Make can_run_on hard violations decisive so System GA re-allocates the partition
#         # BIG = 10**6  # strong penalty to outweigh any lateness trade-off
#         # fitness = lateness + BIG * hard_violations
        
#         fitness = lateness

#         # Optional visibility
#         # try:
#         #     import logging
#         #     log = logging.getLogger(__name__)
#         #     if hard_violations > 0:
#         #         log.info(f"[Partition GA] Hard can_run_on violations={hard_violations} "
#         #                 f" Penalizing with {BIG * hard_violations}.")
#         # except Exception:
#         #     pass

#         return (fitness,)

#     # toolbox.register("evaluate", evaluate)
#     toolbox.register("evaluate", lambda ind: evaluate(ind, time_budget))



#     def custom_mate(ind1, ind2):
#         tools.cxTwoPoint(ind1[:num_tasks], ind2[:num_tasks])
#         ind1[:num_tasks] = gax.repair_task_order(ind1[:num_tasks], valid_task_ids)
#         ind2[:num_tasks] = gax.repair_task_order(ind2[:num_tasks], valid_task_ids)
#         tools.cxOnePoint(ind1[num_tasks:], ind2[num_tasks:])
#         return ind1, ind2

#     def mutation_task_order(ind):
#         i, j = random.sample(range(num_tasks), 2)
#         ind[i], ind[j] = ind[j], ind[i]
#         ind[:num_tasks] = gax.repair_task_order(ind[:num_tasks], valid_task_ids)
#         return ind,

#     def mutation_processor_allocation(ind):
#         for i in range(num_tasks):
#             if random.random() < 0.1:
#                 ind[num_tasks + i] = random.choice(processor_ids)
#         return ind,

#     def mutation_message_priority_ordering(ind, start_idx, length, message_ids):
#         current = ind[start_idx:start_idx + length]
#         random.shuffle(current)
#         used = set()
#         for i in range(length):
#             if current[i] in used or current[i] not in message_ids:
#                 current[i] = random.choice([mid for mid in message_ids if mid not in used])
#             used.add(current[i])
#         ind[start_idx:start_idx + length] = current
#         return ind,

#     def mutation_message_path_index(ind, start_idx, length):
#         for i in range(start_idx, start_idx + length):
#             if random.random() < 0.1:
#                 ind[i] = random.choice([0, 1, 2, 3])
#         return ind,

#     toolbox.register("mate", custom_mate)
#     toolbox.register("mutate_task_order", mutation_task_order)
#     toolbox.register("mutate_processor_allocation", mutation_processor_allocation)
#     toolbox.register("select", tools.selTournament, tournsize=3)

#     pop = toolbox.population(n=cfg.PartitionPopulationSize)
#     for ind in pop:
#         ind.fitness.values = toolbox.evaluate(ind)


#     NGEN = cfg.PartitionGenerations
#     fitness_evolution = []
#     lateness_evolution = []      # NEW
#     makespan_evolution = []      # NEW

#     for g in range(NGEN):
#         offspring = toolbox.select(pop, len(pop))
#         offspring = list(map(toolbox.clone, offspring))

#         for child1, child2 in zip(offspring[::2], offspring[1::2]):
#             if random.random() < cfg.PartitionCrossoverProb:
#                 toolbox.mate(child1, child2)
#                 if hasattr(child1.fitness, 'values'):
#                     del child1.fitness.values
#                 if hasattr(child2.fitness, 'values'):
#                     del child2.fitness.values

#         for mutant in offspring:
#             if random.random() < cfg.PartitionMutationProb:
#                 toolbox.mutate_task_order(mutant)
#                 toolbox.mutate_processor_allocation(mutant)
#                 if num_message > 0:
#                     mutation_message_priority_ordering(mutant, 2 * num_tasks, num_message, message_list_ids)
#                     mutation_message_path_index(mutant, 2 * num_tasks + num_message, num_message)
#                 if hasattr(mutant.fitness, 'values'):
#                     del mutant.fitness.values

#         for ind in offspring:
#             if not ind.fitness.valid:
#                 ind.fitness.values = toolbox.evaluate(ind)

#         # --- Elitist (μ+λ) replacement: keep the best len(pop) from parents+offspring ---
#         pop[:] = tools.selBest(pop + offspring, len(pop))

#         # keep your existing fitness tracking
#         fitness_evolution.append(min(ind.fitness.values[0] for ind in pop))

#         # --- NEW: decode best-of-generation to get makespan & lateness (same logic you use at the end)
#         best = tools.selBest(pop, 1)[0]
#         task_order_b = gax.repair_task_order(best[:num_tasks], valid_task_ids)
#         raw_alloc_b  = best[num_tasks:2 * num_tasks]
#         # alloc_b, hard_violations   = gax.enforce_can_run_on_constraints(task_order_b, raw_alloc_b, processor_ids, job_data, strict=True)

#         if num_message > 0:
#             mpo_b = best[2 * num_tasks:2 * num_tasks + num_message]
#             mpi_b = best[2 * num_tasks + num_message:]
#             upd_b = gax.ComputeMappingsAndPaths(message_list, task_order_b, raw_alloc_b, mpo_b, mpi_b)
#             sel_b = gax.find_suitable_paths(upd_b, all_path_indexes_with_costs)
#             sched_b = reconstruct_schedule_with_precedenceX_updated(
#                 processor_ids, raw_alloc_b, task_order_b, processing_times,
#                 message_list, sel_b, all_path_indexes_with_costs, mpo_b
#             )
#         else:
#             sched_b = {}
#             current_time_per_processor = {pid: 0 for pid in processor_ids}
#             for i, tid in enumerate(task_order_b):
#                 p = raw_alloc_b[i]
#                 s = current_time_per_processor[p]
#                 e = s + processing_times[tid]
#                 sched_b[tid] = (p, s, e, [])
#                 current_time_per_processor[p] = e

#         ms_b = gax.compute_makespan(sched_b)
#         lat_b = max(0, ms_b - (time_budget if time_budget is not None else ms_b))
#         makespan_evolution.append(float(ms_b))
#         lateness_evolution.append(float(lat_b))

#     part_history = {
#         "fitness_evolution": fitness_evolution,
#         "lateness_evolution": lateness_evolution,
#         "makespan_evolution": makespan_evolution,
#         "generations": int(NGEN)
#     }
#     return sched_b, part_history

        
        
    
    
def NEW_GA_V2(processor_ids, processing_times, message_list, all_path_indexes_with_costs, job_data , time_budget=None):
    
    # Partition‐GA (multi-objective): minimize (makespan, lateness)
    if "PartFitness2D" not in creator.__dict__:
        creator.create("PartFitness2D", base.Fitness, weights=(cfg.PartitionMakespanWeight, cfg.PartitionLatenessWeight))
    if "PartIndividual2D" not in creator.__dict__:
        creator.create("PartIndividual2D", list, fitness=creator.PartFitness2D)

    toolbox = base.Toolbox()

    num_tasks = len(processing_times)
    num_message = len(message_list)
    predefined_processors = processor_ids
    message_list_ids = [message['id'] for message in message_list]
    valid_task_ids = list(job_data.keys())
    path_choice_count = int(getattr(cfg, "PathChoiceCount", 4))
    path_choices = list(range(max(1, path_choice_count)))

    def init_task_order():
        return random.sample(valid_task_ids, len(valid_task_ids))

    def processor_allocation(n_task, predefined_values):
        return [random.choice(predefined_values) for _ in range(n_task)]

    def message_priority_ordering(n_messages, defined_values):
        return random.sample(defined_values, n_messages)

    def init_message_path_index(n_messages):
        return [random.choice(path_choices) for _ in range(n_messages)]

    def _repair_processor_allocation(task_order, raw_allocation):
        return gax.enforce_can_run_on_constraints(
            task_order, raw_allocation, processor_ids, job_data, strict=True
        )

    def create_individual():
        individual = []
        task_order = toolbox.task_order()
        raw_allocation = toolbox.processor_allocation()
        processor_allocation, _hard_violations = _repair_processor_allocation(task_order, raw_allocation)
        individual.extend(task_order)
        individual.extend(processor_allocation)
        if num_message > 0:
            individual.extend(toolbox.message_priority_ordering())
            individual.extend(toolbox.message_path_index())
        return individual

    toolbox.register("task_order", init_task_order)
    toolbox.register("processor_allocation", processor_allocation, n_task=num_tasks, predefined_values=predefined_processors)
    if num_message > 0:
        toolbox.register("message_priority_ordering", message_priority_ordering, n_messages=num_message, defined_values=message_list_ids)
        toolbox.register("message_path_index", init_message_path_index, n_messages=num_message)
    
    # toolbox.register("individual", tools.initIterate, creator.Individual, create_individual)
    toolbox.register("individual", tools.initIterate, creator.PartIndividual2D, create_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    def evaluate(individual , time_budget):
        task_order = gax.repair_task_order(individual[:num_tasks], valid_task_ids)
        raw_processor_allocation = individual[num_tasks:2 * num_tasks]
        processor_allocation, hard_violations = _repair_processor_allocation(task_order, raw_processor_allocation)
        
        if num_message == 0:
            schedule = {}
            current_time_per_processor = {pid: 0 for pid in processor_ids}
            for i, task_id in enumerate(task_order):
                proc = processor_allocation[i]
                start = current_time_per_processor[proc]
                end = start + processing_times[task_id]
                schedule[task_id] = (proc, start, end, [])
                current_time_per_processor[proc] = end
        else:
            message_priority_ordering = individual[2 * num_tasks:2 * num_tasks + num_message]
            message_path_index = individual[2 * num_tasks + num_message:]
            updated_list = gax.ComputeMappingsAndPaths(message_list, task_order, processor_allocation,
                                                   message_priority_ordering, message_path_index)
            selected_paths = gax.find_suitable_paths(updated_list, all_path_indexes_with_costs)
            schedule = reconstruct_schedule_with_precedenceX_updated(
                processor_ids, processor_allocation, task_order, processing_times,
                message_list, selected_paths, all_path_indexes_with_costs, message_priority_ordering)
            
        makespan = gax.compute_makespan(schedule)
        lateness = max(0, makespan - time_budget) if time_budget is not None else 0
        hard_penalty = 1000000 * int(hard_violations)

        # Multi-objective fitness: (makespan, lateness), both minimized.
        # Impossible can_run_on mappings stay schedulable but are made decisively unattractive.
        return (makespan + hard_penalty, lateness + hard_penalty)

    # toolbox.register("evaluate", evaluate)
    toolbox.register("evaluate", lambda ind: evaluate(ind, time_budget))

    def custom_mate(ind1, ind2):
        tools.cxTwoPoint(ind1[:num_tasks], ind2[:num_tasks])
        ind1[:num_tasks] = gax.repair_task_order(ind1[:num_tasks], valid_task_ids)
        ind2[:num_tasks] = gax.repair_task_order(ind2[:num_tasks], valid_task_ids)
        tools.cxOnePoint(ind1[num_tasks:], ind2[num_tasks:])
        return ind1, ind2

    def mutation_task_order(ind):
        i, j = random.sample(range(num_tasks), 2)
        ind[i], ind[j] = ind[j], ind[i]
        ind[:num_tasks] = gax.repair_task_order(ind[:num_tasks], valid_task_ids)
        return ind,

    def mutation_processor_allocation(ind):
        for i in range(num_tasks):
            if random.random() < 0.1:
                ind[num_tasks + i] = random.choice(processor_ids)
        return ind,

    def mutation_message_priority_ordering(ind, start_idx, length, message_ids):
        current = ind[start_idx:start_idx + length]
        random.shuffle(current)
        used = set()
        for i in range(length):
            if current[i] in used or current[i] not in message_ids:
                current[i] = random.choice([mid for mid in message_ids if mid not in used])
            used.add(current[i])
        ind[start_idx:start_idx + length] = current
        return ind,

    def mutation_message_path_index(ind, start_idx, length):
        for i in range(start_idx, start_idx + length):
            if random.random() < 0.1:
                ind[i] = random.choice(path_choices)
        return ind,

    toolbox.register("mate", custom_mate)
    toolbox.register("mutate_task_order", mutation_task_order)
    toolbox.register("mutate_processor_allocation", mutation_processor_allocation)
    toolbox.register("select", tools.selTournament, tournsize=3)

    pop = toolbox.population(n=cfg.PartitionPopulationSize)
    for ind in pop:
        ind.fitness.values = toolbox.evaluate(ind)

    NGEN = cfg.PartitionGenerations
    fitness_evolution = []
    lateness_evolution = []      # NEW
    makespan_evolution = []      # NEW
    hard_violation_evolution = []

    for g in range(NGEN):
        offspring = toolbox.select(pop, len(pop))
        offspring = list(map(toolbox.clone, offspring))

        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < cfg.PartitionCrossoverProb:
                toolbox.mate(child1, child2)
                if hasattr(child1.fitness, 'values'):
                    del child1.fitness.values
                if hasattr(child2.fitness, 'values'):
                    del child2.fitness.values

        for mutant in offspring:
            if random.random() < cfg.PartitionMutationProb:
                toolbox.mutate_task_order(mutant)
                toolbox.mutate_processor_allocation(mutant)
                if num_message > 0:
                    mutation_message_priority_ordering(mutant, 2 * num_tasks, num_message, message_list_ids)
                    mutation_message_path_index(mutant, 2 * num_tasks + num_message, num_message)
                if hasattr(mutant.fitness, 'values'):
                    del mutant.fitness.values

        for ind in offspring:
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind)

        # --- Elitist (μ+λ) replacement for multi-objective (NSGA-II) ---
        pop[:] = tools.selNSGA2(pop + offspring, len(pop))

        # keep your existing fitness tracking (best makespan across pop)
        fitness_evolution.append(min(ind.fitness.values[0] for ind in pop))

        # --- decode best-of-generation (representative) to get makespan & lateness
        # pick lexicographically best on (makespan, lateness)
        best = min(pop, key=lambda ind: ind.fitness.values)
        task_order_b = gax.repair_task_order(best[:num_tasks], valid_task_ids)
        raw_alloc_b  = best[num_tasks:2 * num_tasks]
        alloc_b, hard_violations_b = _repair_processor_allocation(task_order_b, raw_alloc_b)

        if num_message > 0:
            mpo_b = best[2 * num_tasks:2 * num_tasks + num_message]
            mpi_b = best[2 * num_tasks + num_message:]
            upd_b = gax.ComputeMappingsAndPaths(message_list, task_order_b, alloc_b, mpo_b, mpi_b)
            sel_b = gax.find_suitable_paths(upd_b, all_path_indexes_with_costs)
            sched_b = reconstruct_schedule_with_precedenceX_updated(
                processor_ids, alloc_b, task_order_b, processing_times,
                message_list, sel_b, all_path_indexes_with_costs, mpo_b
            )
        else:
            sched_b = {}
            current_time_per_processor = {pid: 0 for pid in processor_ids}
            for i, tid in enumerate(task_order_b):
                p = alloc_b[i]
                s = current_time_per_processor[p]
                e = s + processing_times[tid]
                sched_b[tid] = (p, s, e, [])
                current_time_per_processor[p] = e

        ms_b = gax.compute_makespan(sched_b)
        lat_b = max(0, ms_b - (time_budget if time_budget is not None else ms_b))
        makespan_evolution.append(float(ms_b))
        lateness_evolution.append(float(lat_b))
        hard_violation_evolution.append(int(hard_violations_b))

    part_history = {
        "fitness_evolution": fitness_evolution,
        "lateness_evolution": lateness_evolution,
        "makespan_evolution": makespan_evolution,
        "hard_violation_evolution": hard_violation_evolution,
        "generations": int(NGEN)
    }
    return sched_b, part_history
    
    
    
