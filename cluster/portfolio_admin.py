"""Cluster-only migration/resumption of one four-core job per unresolved case."""
from pathlib import Path
import argparse,json,re,subprocess,time,sys
ROOT=Path('/data/wangqm/hmy/pendulum5_20261112')
QSTAT='/opt/tsce4/torque6/bin/qstat';QSUB='/opt/tsce4/torque6/bin/qsub';QDEL='/opt/tsce4/torque6/bin/qdel'
METHODS=['explicit-hs','inverse-hs','residual-continuation','rk4-shooting']

def atomic(path,value):
    temp=path.with_suffix('.new');temp.write_text(json.dumps(value,indent=2));temp.replace(path)

def job_state(ident):
    p=subprocess.run([QSTAT,'-f',ident],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
    if p.returncode:
        if 'Unknown Job Id' in p.stderr:return 'absent',''
        raise RuntimeError(p.stderr)
    state=re.search(r'job_state = (\w)',p.stdout)
    if not state:raise RuntimeError('Unreadable job state')
    return state.group(1),p.stdout

def seconds(value):
    if value=='INFINITY':return float('inf')
    parts=list(map(int,value.split(':')))
    if len(parts)==4:days,hours,minutes,secs=parts
    else:days=0;hours,minutes,secs=parts
    return days*86400+hours*3600+minutes*60+secs

def allocate(output,count):
    slots=[];capacities=[]
    for line in output.splitlines():
        p=line.split()
        if len(p)!=6 or not re.fullmatch(r'cu\d+',p[0]):continue
        if int(p[0][2:])<14 or seconds(p[5])<6*3600:continue
        capacity=min(int(p[1])//4,int(p[2])//16384)
        capacities.append((capacity,p[0]))
    for capacity,node in sorted(capacities,reverse=True):slots.extend([node]*capacity)
    if len(slots)<count:raise RuntimeError('Maui has only '+str(len(slots))+' feasible four-core slots for '+str(count)+' cases')
    return slots[:count]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('migrate','repack','resume','status'));args=parser.parse_args()
    assert Path.cwd().resolve()==ROOT and ROOT.parent==Path('/data/wangqm/hmy')
    sys.path.insert(0,str(ROOT))
    from triple_pendulum import transitions
    transitions.initialize()
    path=ROOT/'job.json';meta=json.loads(path.read_text());active=json.loads((ROOT/'portfolio/active.json').read_text())
    assert len(active['cases'])<=25 and active['methods']==METHODS and active['core_limit']==100
    if args.action in ('migrate','repack'):
        if args.action=='migrate':assert meta.get('mode') not in ('four-method-portfolio','portfolio-preparing'),'Migration already started; use resume/status'
        else:assert meta.get('mode')=='four-method-portfolio','Only repack the current portfolio'
        # Before stopping anything, ensure fresh Maui capacity including the
        # resources currently used by our jobs can hold the new campaign.
        free=subprocess.check_output(['/opt/tsce4/maui/bin/showbf','-S'],universal_newlines=True)
        allocate(free,len(active['cases']))
        atomic(ROOT/('job-before-portfolio-'+str(int(time.time()))+'.json'),meta)
        old=list(meta['jobs']);meta['mode']='portfolio-preparing';atomic(path,meta)
        for row in old:
            state,detail=job_state(row['job_id'])
            if state not in ('absent','C'):
                assert 'wangqm@' in detail and str(ROOT) in detail and 'pend5-' in detail,'Not an authorized project job'
                subprocess.run([QDEL,row['job_id']],check=True)
        deadline=time.time()+90
        while True:
            live=[r['job_id'] for r in old if job_state(r['job_id'])[0] not in ('absent','C')]
            if not live:break
            if time.time()>deadline:raise RuntimeError('Old jobs not stopped: '+str(live))
            time.sleep(2)
        meta.update(mode='four-method-portfolio',portfolio_run=active['run'],methods=METHODS,core_limit=100,
                    legacy_jobs=old,jobs=[],job_ids=[],workers_total=0,workers_per_job=4)
        meta.pop('shards',None);atomic(path,meta)
    else:assert meta.get('mode')=='four-method-portfolio','Not a portfolio campaign'
    rows=transitions.statuses();jobs=list(meta['jobs']);by_case={};live_cores=0;states={}
    for row in jobs:
        state,_=job_state(row['job_id']);states[row['case']]=state
        row['workers']=row.get('requested_workers',4) if state not in ('absent','C') else 0
        live_cores+=row['workers']
        for case_key in row.get('cases',[row['case']]):by_case[case_key]=(row,state)
    assert live_cores<=100
    pending=[]
    for i,case in enumerate(active['cases']):
        row=rows[case['key']]
        if row['status']=='ready':continue
        if by_case.get(case['key'],(None,'absent'))[1] not in ('absent','C'):continue
        pending.append((i,case))
    meta['workers_total']=live_cores;atomic(path,meta)
    if args.action=='status':
        print(json.dumps(dict(mode=meta['mode'],workers=live_cores,pending_to_submit=[c['key'] for _,c in pending],states=states)))
        return
    assert live_cores+4*len(pending)<=100,'Cannot exceed user authorized 100 cores'
    free=subprocess.check_output(['/opt/tsce4/maui/bin/showbf','-S'],universal_newlines=True)
    nodes=allocate(free,len(pending));atomic(ROOT/'portfolio'/active['run']/'latest-launch-plan.json',dict(at=time.time(),nodes=nodes,cases=[c for _,c in pending],core_limit=100))
    grouped={}
    for item,node in zip(pending,nodes):grouped.setdefault(node,[]).append(item)
    for group_no,(node,items) in enumerate(grouped.items()):
        indices=[i for i,_ in items];case_keys=[c['key'] for _,c in items];cpus=4*len(items)
        ident=subprocess.check_output([QSUB,'-N','pend5-four-g'+str(group_no),'-l','nodes='+node+':ppn='+str(cpus)+',mem='+str(16*len(items))+'gb,walltime=06:00:00',
            '-o',str(ROOT/'portfolio'/active['run']/'logs'/('pbs-group-'+str(int(time.time()))+'-'+str(group_no)+'.log')),'-d',str(ROOT),
            '-v','PORTFOLIO_RUN='+active['run']+',PORTFOLIO_GROUP='+str(group_no)+',PORTFOLIO_CASES='+':'.join(map(str,indices))+',TMPDIR='+str(ROOT/'tmp'),str(ROOT/'fifth-order-portfolio.pbs')],universal_newlines=True).strip()
        assert ident.endswith('.mu01'),ident
        row=dict(case='group-'+ident,cases=case_keys,case_indices=indices,job_id=ident,workers=cpus,requested_workers=cpus,methods=METHODS,requested_node=node,submitted_at=time.time())
        jobs.append(row);meta['jobs']=jobs;meta['job_ids']=[r['job_id'] for r in meta['jobs']]
        meta.pop('workers_per_job',None);meta['workers_per_case']=4
        meta['workers_total']=sum(r['workers'] for r in meta['jobs']);assert meta['workers_total']<=100
        atomic(path,meta);print(json.dumps(row),flush=True)

if __name__=='__main__':main()
