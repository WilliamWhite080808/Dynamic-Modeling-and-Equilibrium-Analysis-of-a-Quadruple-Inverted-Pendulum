"""Experimental lossless predictive codec: predictions plus exact XOR corrections.

No reference node, force, acceleration or feedback coefficient is discarded.
The fixed native kernel and numerical runtime are part of the codec recipe.
"""
import base64,copy,hashlib,json,lzma,textwrap
from pathlib import Path
import numpy as np
from .motion_text import dumps
from .model import Plant,Parameters
from .planner import tracking_gains

RECIPE='hs12-fdlibm-tvlqr-nehalem-v2'
FIELDS=('q','v','a','u','K')


def kernel():
    from . import _native
    return _native


def kernel_hash():return hashlib.sha256(Path(kernel().__file__).read_bytes()).hexdigest()


def packed(bits):
    raw=np.asarray(bits,dtype='<u8').ravel(order='F').view(np.uint8).reshape(-1,8).T.copy().tobytes()
    return base64.b64encode(lzma.compress(raw,preset=6)).decode('ascii')


def unpacked(body,count,width):
    size=count*width*8;body=''.join(body.split())
    if len(body)>size*2+2048:raise ValueError('Oversized recipe correction')
    dec=lzma.LZMADecompressor(memlimit=64*1024*1024);raw=dec.decompress(base64.b64decode(body,validate=True),max_length=size+1)
    if len(raw)!=size or not dec.eof or dec.unused_data:raise ValueError('Invalid recipe correction size')
    flat=np.frombuffer(raw,np.uint8).reshape(8,-1).T.copy().reshape(-1).view('<u8')
    return flat.reshape(width,count).T.copy()


def baseline(plant,states,forces,h,target):
    acc=plant.batch(states,forces)[:,plant.d:]
    gains=tracking_gains(plant,dict(states=states.tolist(),forces=forces.tolist(),dt=h,target_angles=target))
    return np.column_stack((acc,gains))


def compact_bytes(doc):
    n=doc['n'];plant=Plant(Parameters(n=n));d=plant.d
    value=dict(v=4,n=n,ends=doc['ends'],model=doc['model_sha256'],recipe=RECIPE,kernel=kernel_hash())
    for name,target_code in (('ab',doc['ends'][1]),('ba',doc['ends'][0])):
        data=copy.deepcopy(doc[name]);count=len(data['q']);integers=[];offset=0
        for key,width in zip(FIELDS,(d,d,d,1,2*d)):
            original=data[key]
            flat=original if key=='u' else [original[r][c] for c in range(width) for r in range(count)]
            integers.extend(offset+i for i,v in enumerate(flat) if type(v) is int);offset+=len(flat)
        states=np.ascontiguousarray(np.column_stack((data.pop('q'),data.pop('v'))),dtype='<f8');forces=np.asarray(data.pop('u'),dtype='<f8')
        original=np.column_stack((data.pop('a'),data.pop('K'))).astype('<f8')
        target=[0. if c=='U' else float(np.pi) for c in target_code]
        predicted=baseline(plant,states,forces,data['h'],target)
        corrections=original.view('<u8')^predicted.view('<u8')
        state_bits=kernel().state_corrections(states,forces,data['h'],*plant.args)
        force_bits=forces.view('<u8').copy();force_bits[1:]^=force_bits[:-1]
        direction=dict(T=data.pop('T'),h=data.pop('h'),nodes=count)
        direction.update(data);direction['hash']=direction.pop('runtime_sha256')
        if 'origin_sha256' in direction:direction['origin']=direction.pop('origin_sha256')
        if integers:direction['integers']=integers
        direction['state_hash']=hashlib.sha256(states.tobytes()).hexdigest()
        direction['baseline_hash']=hashlib.sha256(predicted.tobytes()).hexdigest()
        direction.update(forces=packed(force_bits),states=packed(state_bits),corrections=packed(corrections))
        value[name]=direction
    lines=[]
    for line in dumps(value).splitlines():
        if line.partition(' = ')[0] in ('forces','states','corrections'):
            body=json.loads(line.partition(' = ')[2]);lines.extend([line.partition(' = ')[0]+' = """',*textwrap.wrap(body,96),'"""'])
        else:lines.append(line)
    return ('# Exact IEEE754 reference: fixed predictor + lossless XOR correction; passive rods.\n'+'\n'.join(lines)+'\n').encode('utf8')


def expand(doc):
    if doc.get('v')!=4 or doc.get('recipe')!=RECIPE or doc.get('kernel')!=kernel_hash():raise ValueError('Recipe kernel does not match this package')
    n=doc['n']
    if type(n) is not int or not 1<=n<=20:raise ValueError('Invalid order')
    plant=Plant(Parameters(n=n));d=plant.d
    value=dict(v=2,n=n,ends=doc['ends'],model_sha256=doc['model'],basis='state-hermite-v1')
    for name,target_code in (('ab',doc['ends'][1]),('ba',doc['ends'][0])):
        data=copy.deepcopy(doc[name]);count=data.pop('nodes')
        if type(count) is not int or not 2<=count<=20000:raise ValueError('Invalid node count')
        fb=unpacked(data.pop('forces'),count,1).ravel();forces=np.bitwise_xor.accumulate(fb).view('<f8')
        state_bits=unpacked(data.pop('states'),count,2*d)
        states=kernel().restore_states(state_bits,forces,data['h'],*plant.args)
        if hashlib.sha256(states.tobytes()).hexdigest()!=data.pop('state_hash'):raise ValueError('Recipe state reconstruction checksum mismatch')
        target=[0. if c=='U' else float(np.pi) for c in target_code]
        predicted=baseline(plant,states,forces,data['h'],target)
        if hashlib.sha256(predicted.tobytes()).hexdigest()!=data.pop('baseline_hash'):raise ValueError('Recipe numerical runtime mismatch')
        bits=unpacked(data.pop('corrections'),count,3*d)^predicted.view('<u8');derived=bits.view('<f8')
        data.update(q=states[:,:d].tolist(),v=states[:,d:].tolist(),a=derived[:,:d].tolist(),u=forces.tolist(),K=derived[:,d:].tolist())
        integers=set(data.pop('integers',[]));offset=0
        for key,width in zip(FIELDS,(d,d,d,1,2*d)):
            for c in range(width):
                for r in range(count):
                    if offset+c*count+r in integers:
                        if key=='u':data[key][r]=int(data[key][r])
                        else:data[key][r][c]=int(data[key][r][c])
            offset+=count*width
        data['runtime_sha256']=data.pop('hash')
        if 'origin' in data:data['origin_sha256']=data.pop('origin')
        value[name]=data
    return value
