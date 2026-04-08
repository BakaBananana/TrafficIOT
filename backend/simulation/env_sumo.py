import libsumo as traci
# import traci
import sumolib
import torch
import subprocess
import numpy as np

class SumoGraphEnv:
    def __init__(self, sumo_cfg_path, net_file_path, gui=False):
        self.sumo_cfg_path = sumo_cfg_path
        self.net = sumolib.net.readNet(net_file_path)
        
        sumo_binary = "sumo-gui" if gui else "sumo"
        self.sumo_cmd = [sumo_binary, "-c", self.sumo_cfg_path]
        
        traci.start(self.sumo_cmd)
        self.tls_ids = traci.trafficlight.getIDList()
        self.num_nodes = len(self.tls_ids)
        self.tls_to_idx = {tls: i for i, tls in enumerate(self.tls_ids)}
        
        self.adjacency_matrix = self._build_adjacency_matrix()
        
        self.switching_penalty = 15.0
        self.min_green_time = 10       
        
        traci.close()
        print(f"Environment initialized. Found {self.num_nodes} controllable intersections.")

    def _build_adjacency_matrix(self):
        W = torch.zeros((self.num_nodes, self.num_nodes))
        
        for tls_i in self.tls_ids:
            idx_i = self.tls_to_idx[tls_i]
            start_node = self.net.getNode(tls_i)
            
            # BFS Queue: stores tuples of (current_edge, accumulated_distance)
            queue = []
            for edge in start_node.getOutgoing():
                # We only care about passenger roads
                if edge.allows("passenger"):
                    queue.append((edge, edge.getLength()))
            visited_edges = set()
            while queue:
                current_edge, current_dist = queue.pop(0)
                if current_edge.getID() in visited_edges:
                    continue
                visited_edges.add(current_edge.getID())
                dest_node = current_edge.getToNode()
                
                # --- SCENARIO A: We found the next Traffic Light! ---
                if dest_node.getType() == "traffic_light":
                    tls_j = dest_node.getID()
                    if tls_j in self.tls_to_idx:
                        idx_j = self.tls_to_idx[tls_j]
                        # Calculate weight using the TOTAL accumulated distance
                        weight = 100.0 / (current_dist + 1.0) 
                        
                        # If there are multiple routes to the same light, keep the shortest/strongest one
                        if W[idx_i, idx_j] == 0 or weight > W[idx_i, idx_j]:
                            W[idx_i, idx_j] = weight
                            
                    # Stop searching down this specific path; we hit our logical destination
                    continue 
                
                # --- SCENARIO B: Unsignalized intersection. Keep driving! ---
                for next_edge in dest_node.getOutgoing():
                    if next_edge.allows("passenger") and next_edge.getID() not in visited_edges:
                        # Add the next road segment to the queue and add to the total distance
                        queue.append((next_edge, current_dist + next_edge.getLength()))
                        
        # GAT Self-Loops: Intersections must monitor their own queues!
        for i in range(self.num_nodes):
            W[i, i] = 100.0  
            
        return W
    
    def reset(self, seed=42, num_vehicles=2500, spawn=3540): 
        try:
            traci.close()
        except Exception:
            pass 
            
        if seed is not None:
            print(f"Generating demand... Seed: {seed} | Vehicles: {num_vehicles} | spawn: {spawn}")
            subprocess.run(["python", "generate_demand.py", str(seed), str(num_vehicles), str(spawn)], capture_output=True)
            
        current_cmd = self.sumo_cmd.copy()
        if seed is not None:
            current_cmd.extend(["--seed", str(seed)])
            
        traci.start(current_cmd)
        return self.get_state(elapsed_time=1.0)

    def get_state(self, elapsed_time=1.0):
        pcu_weights = {
            "motorcycle_ind": 0.5, "car_ind": 1.0,   
            "auto_ind": 1.0, "bus_ind": 3.0
        }
        
        state_vectors = []
        for i, tls in enumerate(self.tls_ids):
            total_pcu_queue = 0.0
            max_wait_time = 0.0
            
            controlled_links = traci.trafficlight.getControlledLinks(tls)
            incoming_lanes = set([link[0][0] for link in controlled_links if link])
            
            for lane in incoming_lanes:
                vehicles = traci.lane.getLastStepVehicleIDs(lane)
                for veh in vehicles:
                    try:
                        if traci.vehicle.getSpeed(veh) < 0.1:
                            v_type = traci.vehicle.getTypeID(veh)
                            wait_time = traci.vehicle.getAccumulatedWaitingTime(veh)
                            total_pcu_queue += pcu_weights.get(v_type, 1.0)
                            
                            if wait_time > max_wait_time:
                                max_wait_time = wait_time
                    except traci.exceptions.TraCIException:
                        continue 
            
            current_phase = traci.trafficlight.getPhase(tls)
            logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
            num_phases = len(logic.phases)
            
            # Dynamic Normalization (Scales perfectly regardless of phase count)
            scaled_queue = total_pcu_queue / 50.0  
            scaled_wait = max_wait_time / 100.0    
            scaled_phase = current_phase / float(num_phases)     
            
            if isinstance(elapsed_time, (list, tuple, torch.Tensor, np.ndarray)):
                time_val = float(elapsed_time[i] if i < len(elapsed_time) else elapsed_time[0])
            else:
                time_val = float(elapsed_time)
            scaled_time = min(time_val / 15.0, 1.0)
            
            state_vectors.append([scaled_queue, scaled_wait, scaled_phase, scaled_time])
        
        for tls in self.tls_ids:
            traci.trafficlight.setPhaseDuration(tls, 100000)
            
        return torch.tensor(state_vectors, dtype=torch.float32)
    
    def _get_next_phases(self, tls, current_phase):
        logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
        num_phases = len(logic.phases)
        
        # 1. Find upcoming yellow phase
        yellow_phase = (current_phase + 1) % num_phases
        for offset in range(1, num_phases):
            cand = (current_phase + offset) % num_phases
            if 'y' in logic.phases[cand].state.lower():
                yellow_phase = cand
                break
                
        # 2. Find green phase after that yellow phase
        green_phase = (yellow_phase + 1) % num_phases
        for offset in range(1, num_phases):
            cand = (yellow_phase + offset) % num_phases
            if 'g' in logic.phases[cand].state.lower():
                green_phase = cand
                break
                
        return yellow_phase, green_phase

    def step(self, actions):
        action_changed = False
        original_phases = {} # We must store the exact phase before we trigger the yellow
        next_green_phases = {}
        
        # 1. TRIGGER THE YELLOW LIGHTS
        for i, tls in enumerate(self.tls_ids):
            action = actions[i].item() 
            if action == 1: 
                action_changed = True
                current_phase = traci.trafficlight.getPhase(tls)
                original_phases[tls] = current_phase 
                
                # logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                # num_phases = len(logic.phases)

                yellow_phase, green_phase = self._get_next_phases(tls, current_phase)
                next_green_phases[tls] = green_phase
                
                # Advance 1 step into the Yellow phase
                # next_phase = (current_phase + 1) % num_phases
                traci.trafficlight.setPhase(tls, yellow_phase)

                traci.trafficlight.setPhaseDuration(tls, 100000)
                
        # 2. SIMULATE THE YELLOW CLEARANCE (3 Seconds)
        if action_changed:
            for _ in range(3): 
                traci.simulationStep()
                if traci.simulation.getMinExpectedNumber() == 0: break
                    
            # 3. TRANSITION TO THE NEXT GREEN LIGHT
            for tls, orig_phase in original_phases.items():
                # logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                # num_phases = len(logic.phases)
                
                # THE FIX: Advance 2 steps total (Old Green -> Yellow -> New Green)
                # new_green_phase = (orig_phase + 2) % num_phases
                # traci.trafficlight.setPhase(tls, new_green_phase)

                traci.trafficlight.setPhase(tls, next_green_phases[tls])
                traci.trafficlight.setPhaseDuration(tls, 100000)
                
        # 4. ENFORCE THE MINIMUM GREEN TIME (10 Seconds)
        steps_to_simulate = self.min_green_time if action_changed else 1
        for _ in range(steps_to_simulate):
            traci.simulationStep()
            if traci.simulation.getMinExpectedNumber() == 0: break
            
        time_passed = 3.0 + self.min_green_time if action_changed else 1.0
        
        # 5. Observe reality
        next_state = self.get_state(elapsed_time=time_passed)
        
        # 6. Calculate Rewards
        rewards = []
        omega = 0.5 
        
        for i in range(self.num_nodes):
            # We must use the unscaled raw values from SUMO to calculate the penalty
            queue_len = next_state[i][0].item() * 50.0  
            max_wait = next_state[i][1].item() * 100.0  
            
            reward = -(queue_len + (omega * max_wait))
            
            if actions[i].item() == 1:
                reward -= self.switching_penalty
                
            rewards.append(reward)
        
        active_vehicles = traci.simulation.getMinExpectedNumber()
        done = (active_vehicles == 0)
            
        return next_state, torch.tensor(rewards, dtype=torch.float32), done, action_changed

    def close(self):
        traci.close()