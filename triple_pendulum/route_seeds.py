"""Build graph-based initial guesses; these are never admitted as solutions."""
from copy import deepcopy
import heapq,json
from pathlib import Path
import numpy as np
from . import transitions
from .model import Plant,Parameters
from .precompute_transitions import concatenate

def shortest_route(rows,source,target):
    graph={}
    for row in rows:
        if row['status']=='ready':graph.setdefault(row['source'],[]).append((row['duration'],row['target']))
    queue=[(0.,[source])];visited=set()
    while queue:
        cost,path=heapq.heappop(queue);node=path[-1]
        if node==target:return path
        if node in visited:continue
        visited.add(node)
        for weight,nxt in graph.get(node,[]):
            if nxt in visited or (nxt=='D'*len(source) and nxt!=target):continue
            heapq.heappush(queue,(cost+weight,path+[nxt]))
    return None

def route_candidates(rows,source,target,limit=10,max_edges=3):
    graph={}
    for row in rows:
        if row['status']=='ready':graph.setdefault(row['source'],[]).append((row['duration'],row['target']))
    queue=[(0.,[source])];found=[]
    while queue and len(found)<limit:
        cost,path=heapq.heappop(queue);node=path[-1]
        if node==target:found.append(path);continue
        if len(path)>max_edges:continue
        for duration,nxt in graph.get(node,[]):
            if nxt in path or (nxt=='D'*len(source) and nxt!=target):continue
            heapq.heappush(queue,(cost+duration,path+[nxt]))
    return found

def build_seed(plant,path):
    result=None
    for source,target in zip(path,path[1:]):
        suffix=deepcopy(transitions.lookup(plant,source,target))
        if suffix is None:raise ValueError('Route lost a certified edge')
        if result is None:result=suffix;continue
        states=np.asarray(suffix['states']);delta=np.asarray(result['states'][-1])[:plant.d]-states[0,:plant.d]
        states[:,:plant.d]+=delta
        suffix.update(states=states.tolist(),derivatives=plant.batch(states.copy(),np.asarray(suffix['forces']).copy()).tolist())
        result=concatenate(plant,result,suffix,compute_gains=False)
    result.update(gains=[],seed_kind='verified_route_initial_guess',seed_waypoints=path,success=False)
    return result

def main():
    plant=Plant(Parameters(n=4));rows=transitions.catalog(4)['entries'];out=Path('results/fourth-order-route-seeds');out.mkdir(exist_ok=True)
    summary=[]
    for row in rows:
        if row['status']=='ready':continue
        path=shortest_route(rows,row['source'],row['target'])
        if path is None:continue
        seed=build_seed(plant,path);name=transitions.key(4,row['source'],row['target'])+'.json'
        (out/name).write_text(json.dumps(seed),encoding='utf8');summary.append(dict(file=name,duration=seed['duration'],path=path))
    (out/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print('SEEDS',len(summary),flush=True)

if __name__=='__main__':main()
