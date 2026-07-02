| Symptom                                                               | Action                                                                                                               |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Receiver violation flat (>0) and budgets not changing (integer stall) | Lower `deadband_ratio` by 0.005; raise `donor_frac` to 0.98; raise `α_receiver` to 0.40 (keep `α_r*cap_up ≤ 0.15`). |
| Donors barely classified (few donors)                                 | Lower `min_margin_ratio` to 0.012–0.015; keep `k_sigma=0.8`.                                                        |
| Convergence too slow but stable                                       | Raise `α_donor` to 0.95 **or** `cap_up` to 0.35–0.40 (but keep `α_r*cap_up ≤ 0.15`).                                |
| Jitter near target (tiny oscillations)                                | Raise `deadband_ratio` slightly (up to `min_margin_ratio`) or lower `α_receiver` to 0.30.                           |
| Overshoot returns                                                     | Lower `cap_up` one step or `α_receiver` one step; your anti-windup clamps will also protect.                        |
| One receiver dominates, others starve                                 | Lower `severity_beta` to 1.2–1.4 or raise `min_receiver_quota` to 0.25.                                             |

----------------------------------
Points based on wednesday (27.08.2025)
----------------------------------
    - Are parents better than offspring?
        - what was happeneing was that children can replace parents even if not better (it is called classic generational replacement)
            toolbox.register("select", tools.selTournament, tournsize=3)
            pop[:] = offspring
            
            Two issues with this one:
                first: tournamnet isn't the best selction function when it comes to multi-objective GAs
                Second: replacing the parents even if they are better might affect the GAs convergence

            Fix: Use NSGA-II selction and widen the selection pool to be from both parents and the offsprings

            toolbox.register("select", tools.selTournamentDCD)  # Dominance–Crowding Distance (pick the one with better Pareto rank, neither dominates, pick the larger crowding distance) , instead of selTournament
                                                                
            pop[:] = tools.selNSGA2(pop, len(pop)) # orders the same individuals and annotates them with the metadata DCD will use.
                                                    # why do we do this? DCD needs two pieces of metadata on each individual ==> Pareto rank, and Crowding distance
                                                    # After the first pop, none of this data exists yet
                                                    # If we call DCD before that, Comparisons where neither individual dominates and without having the croding distance will mean that
                                                    # distances are effectively equal/unknown, so DCD has no basis to prefer one and will break the tie randomly 
                                                    # In this step we actuall don't select 

            (Selecting the best for next generation)        
            pop[:] = tools.selNSGA2(pop + offspring, len(pop)) ==> The pool now is diverse 
                                                                # 
            best = min(pop, key=lambda ind: ind.fitness.values)  (Violations dominate lateness)

            NSGA-II ==> it doesn't output an overall lateness, but a vector per individual (ViolationSum , Lateness)
            Selection is done through Parento dominance + crowding
            ---------
            Dominance
            ---------
                - A dominates B if:
                    1- A is no worse than B on every objective
                    2- A is better in at least one objective 
                    a1 =< b1 and a2 =< b2 and at least one is < 
            --------
            Crowding
            --------
            - NSGA-II tries to keep solutions diverse, this is done through a scalar called (crowding distance). 
            - A bigger distance means that the point is in sparser region making it valuable to keep it.
            di​+ = fk​(i+1) - fk​(i−1) / fkmax - fkmin
            fk​(i+1) = the next neighbor’s value in objective 𝑘.
            fk​(i−1) = the previous neighbor’s value in objective 𝑘
            fkmax , fkmin max and min of objective k in this front

    - The plots of partition violations Vs generations and TBs vs MS don't coincide (discrepency)
        - (Fixed) Logging issue 

-------------------------------------
Based on the results from Friday runs 
-------------------------------------
    - Issues:
        - Huge margin between TB and MS

            - Logging issue ==> logged the wrong violation value (The updated TB instead of the current one)
            - now using the per-partition violations coming from the evaluate functiopn (ind.partition_violations = part_viol.copy())

            
        - Overshoot when receivers got extra budget
            - No bound

        - TBs detriorates after being converged 
        
