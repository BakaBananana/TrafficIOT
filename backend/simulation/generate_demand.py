import sumolib
import random
import sys
from collections import deque

def is_edge_reachable(net, start_id, end_id):
    start = net.getEdge(start_id)
    end = net.getEdge(end_id)

    visited = set()
    queue = deque([start])

    while queue:
        edge = queue.popleft()

        if edge.getID() == end_id:
            return True

        visited.add(edge.getID())

        # SUMO-valid successors (Edge objects)
        for nxt in edge.getOutgoing():      
            if nxt.getID() not in visited:
                queue.append(nxt)

    return False

def generate_route_file(net_file, output_file, num_vehicles=4000, spawn=3540):
    print(f"Reading network from {net_file}...")
    net = sumolib.net.readNet(net_file)

    # Edges that allow passenger and >20m
    valid_edges = [e for e in net.getEdges() if e.allows("passenger") and e.getLength() > 20]

    if not valid_edges:
        print("No usable edges found!")
        sys.exit(1)

    boundary_in = []
    boundary_out = []
    internal_edges = []

    for e in valid_edges:
        incom = [i for i in e.getFromNode().getIncoming() if i.allows("passenger")]
        outgo = [o for o in e.getToNode().getOutgoing() if o.allows("passenger")]

        if len(incom) == 0:
            boundary_in.append(e.getID())
        if len(outgo) == 0:
            boundary_out.append(e.getID())

    # Fallbacks
    if not boundary_in:
        boundary_in = [e.getID() for e in valid_edges]
    if not boundary_out:
        boundary_out = [e.getID() for e in valid_edges]

    internal_edges = [
        e.getID() for e in valid_edges
        if e.getID() not in boundary_in and e.getID() not in boundary_out
    ]
    if not internal_edges:
        internal_edges = [e.getID() for e in valid_edges]

    vtypes = """
    <vType id="motorcycle_ind" vClass="motorcycle" latAlignment="arbitrary" minGapLat="0.1" maxSpeed="15.0" length="2.0" width="0.8" accel="2.5" decel="4.5"/>
    <vType id="car_ind" vClass="passenger" latAlignment="arbitrary" minGapLat="0.3" maxSpeed="15.0" length="4.5" width="1.8" accel="2.0" decel="4.0"/>
    <vType id="auto_ind" vClass="taxi" latAlignment="arbitrary" minGapLat="0.2" maxSpeed="12.0" length="2.8" width="1.4" guiShape="rickshaw" accel="1.5" decel="3.5"/>
    <vType id="bus_ind" vClass="bus" latAlignment="center" minGapLat="0.5" maxSpeed="10.0" length="10.0" width="2.5" accel="1.0" decel="3.0"/>
    """

    distribution = [
        (0.45, "motorcycle_ind", 0.5),
        (0.70, "car_ind", 0.7),
        (0.90, "auto_ind", 0.4),
        (1.00, "bus_ind", 1.0),
    ]

    trips = []
    
    # --- THE UPGRADE: Caching dictionary ---
    reachability_cache = {}
    # ---------------------------------------

    print(f"Generating {num_vehicles} valid trips…")

    for _ in range(num_vehicles):
        while True:
            # Pick type
            r = random.random()
            for p, vtype, th_prob in distribution:
                if r <= p:
                    chosen_type = vtype
                    through = th_prob
                    break

            # Decide OD category
            # if random.random() < through:
            #     start_edge = random.choice(boundary_in)
            #     end_edge = random.choice(boundary_out)
            # else:
            #     start_edge = random.choice(internal_edges)
            #     end_edge = random.choice(internal_edges)
            if random.random() < .85:
                start_edge = random.choice(boundary_in)
            else:
                start_edge = random.choice(internal_edges)
            
            end_edge = random.choice(boundary_out)

            if start_edge == end_edge:
                continue

            # --- THE UPGRADE: Check cache before running BFS ---
            pair = (start_edge, end_edge)
            if pair not in reachability_cache:
                # If we haven't seen this pair before, run the BFS and save the result
                reachability_cache[pair] = is_edge_reachable(net, start_edge, end_edge)

            # Use the cached result
            if not reachability_cache[pair]:
                continue  # try again
            # ---------------------------------------------------

            break  # found a valid pair

        depart_time = random.uniform(0, spawn)
        trips.append({
            "type": chosen_type,
            "depart": depart_time,
            "from": start_edge,
            "to": end_edge
        })

    # Sort by depart time
    trips.sort(key=lambda t: t["depart"])

    # Write the sorted list to the XML file
    with open(output_file, "w") as routes:
        routes.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        routes.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">\n')
        routes.write(vtypes)

        for vid, trip in enumerate(trips):
            routes.write(f'    <trip id="{vid}" type="{trip["type"]}" depart="{trip["depart"]:.2f}" from="{trip["from"]}" to="{trip["to"]}" departPos="random_free" departSpeed="max"/>\n')

        routes.write('</routes>\n')
    print(f"Done! Saved to {output_file} (Sorted by departure time)")

if __name__ == "__main__":
    episode_seed = 42
    episode_spawn = 40
    num_veh = 2500

    if len(sys.argv) > 1:
        episode_seed = int(sys.argv[1])
    if len(sys.argv) > 2:
        num_veh = int(sys.argv[2])
    if len(sys.argv) > 3:
        episode_spawn = int(sys.argv[3])

    random.seed(episode_seed)

    generate_route_file(
        "patna_stc.net.xml",
        "patna_stc.rou.xml",
        num_vehicles=num_veh,
        spawn=episode_spawn
    )