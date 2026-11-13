"""Export a certified immutable bank as independent, bidirectional plugins."""
from pathlib import Path
import hashlib,json
from . import transitions,motion_plugins
from .motion_text import dumps as toml,motion_bytes

ROOT=Path(__file__).resolve().parent.parent

def export(destination,compact=False):
    destination=Path(destination);motions=destination/'motions';models=destination/'models';motions.mkdir(parents=True,exist_ok=True);models.mkdir(exist_ok=True)
    rows=transitions.statuses();ready={k:r for k,r in rows.items() if r['status']=='ready'};pairs=[];signatures={};counts={};omitted=0
    # Read immutable admitted bytes once: background calculation may continue.
    for key,row in sorted(ready.items()):
        n,a,b=row['order'],row['source'],row['target']
        reverse=ready.get(transitions.key(n,b,a))
        if reverse is None:omitted+=1;continue
        if a>b:continue
        directions=[]
        for r in (row,reverse):
            raw=(transitions.ROOT/r['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('源文件摘要不符')
            plan=json.loads(raw)
            if plan.get('segments') or plan.get('route_waypoints'):raise ValueError('不导出中间稳态拼接路径')
            data=motion_plugins.pack(plan);data['origin_sha256']=r['sha256'];directions.append(data)
            signatures.setdefault(n,[]).append(f'{r["source"]}-{r["target"]}:{data["runtime_sha256"]}')
        pairs.append(dict(n=n,ends=[a,b],ab=directions[0],ba=directions[1]))
        counts[n]=counts.get(n,0)+2
    sequence={}
    legacy=transitions.catalog()
    for n,entries in signatures.items():
        if counts[n]==2**n*(2**n-1) and legacy['cruise_ready'].get(n):sequence[str(n)]=hashlib.sha256('\n'.join(sorted(entries)).encode()).hexdigest()
    params={k:v for k,v in ready[next(iter(ready))]['parameters'].items() if k!='n'}
    model=dict(v=1,parameters=params,units='SI; absolute angles measured from vertical up',force_rate=500,actuators='cart only; passive viscous joints',sequence_signatures=sequence)
    (models/'standard.toml').write_text(toml(model),encoding='utf8')
    expected_files=set()
    for pair in pairs:
        doc=dict(v=1,basis='state-hermite-v1',model_sha256=motion_plugins.model_digest(model),**pair)
        if compact:
            from .motion_codec import compact_bytes
            raw=compact_bytes(doc)
        else:raw=motion_bytes(doc)
        path=motions/f'{pair["n"]}_{pair["ends"][0]}_{pair["ends"][1]}.toml';expected_files.add(path.name)
        if path.exists() and path.read_bytes()==raw:continue
        motion_plugins.MotionStore.validate(None,raw,model);path.write_bytes(raw)
    for path in motions.glob('*.toml'):
        if path.name not in expected_files:path.unlink()
    return dict(orders=counts,pairs=len(pairs),directions=sum(counts.values()),unpaired_directions_not_published=omitted,sequence_ready=sorted(map(int,sequence)))
