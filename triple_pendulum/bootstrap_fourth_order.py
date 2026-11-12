"""Revalidate existing fourth-order hanging references for the new transfer bank."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
import hashlib,json
from .model import Plant,Parameters
from . import precomputed,repository,transitions
from .remote_transitions import validate_and_admit

def main():
    plant=Plant(Parameters(n=4));directory=Path('results/fourth-order-bootstrap');directory.mkdir(exist_ok=True)
    tasks=[]
    for target in repository.patterns(4):
        if transitions.statuses()[transitions.key(4,'DDDD',target)]['status']=='ready':continue
        plan=precomputed.lookup(plant,precomputed.hanging(plant),repository.angles(target))
        if plan is None:continue
        plan=deepcopy(plan);plan.update(transition=dict(order=4,source='DDDD',target=target),force_rate=500.,strict_rest=True,parameters=plant.p.dict())
        encoded=json.dumps(plan).encode();path=directory/(target+'.json');path.write_bytes(encoded)
        row=dict(order=4,source='DDDD',target=target,sha256=hashlib.sha256(encoded).hexdigest(),origin_host='local-certified-hanging-bank')
        tasks.append((str(path),row))
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(validate_and_admit,path,row):row for path,row in tasks}
        for future in as_completed(futures):
            row=futures[future]
            try:print('BOOTSTRAP_READY',future.result(),flush=True)
            except Exception as error:print('REMOTE_SEARCH_REQUIRED',row['target'],str(error)[-250:],flush=True)

if __name__=='__main__':main()
