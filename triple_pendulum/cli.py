import argparse
import csv
import json
from pathlib import Path
import numpy as np
from .model import Parameters
from .simulation import simulate

def main():
    p=argparse.ArgumentParser(description='Pendulum Lab reproducible scientific experiments')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('serve')
    run=sub.add_parser('run');run.add_argument('--order',type=int,default=3);run.add_argument('--duration',type=float,default=12)
    run.add_argument('--reference',action='store_true');run.add_argument('--sensor',default='full_state',choices=['full_state','angles_only','cart_and_tip','cart_only'])
    run.add_argument('--observer',default='kalman',choices=['kalman','ekf','luenberger']);run.add_argument('--noise',type=float,default=0)
    run.add_argument('--open-loop',action='store_true');run.add_argument('--output',default='results/experiment')
    bench=sub.add_parser('benchmark');bench.add_argument('--orders',default='1,2,3,4,5');bench.add_argument('--duration',type=float,default=5)
    args=p.parse_args()
    if args.command=='serve':
        from .server import main as serve;serve();return
    if args.command=='benchmark':
        result=[]
        for order in map(int,args.orders.split(',')):
            _,report=simulate(Parameters(n=order),duration=args.duration)
            result.append(report);print(json.dumps(report,ensure_ascii=False),flush=True)
        Path('results').mkdir(exist_ok=True);Path('results/benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf8');return
    arr,report=simulate(Parameters(n=args.order),args.duration,sensor=args.sensor,observer=args.observer,reference=args.reference,noise=args.noise,mode='off' if args.open_loop else 'lqr')
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    d=args.order+1;states=['x']+[f'theta{i+1}' for i in range(args.order)]+['vx']+[f'omega{i+1}' for i in range(args.order)]
    np.savetxt(str(out)+'.csv',arr,delimiter=',',header=','.join(['time']+states+['estimate_'+k for k in states]+['force','energy']),comments='')
    np.savez(str(out)+'.npz',data=arr,parameters=report['parameters'])
    Path(str(out)+'.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
