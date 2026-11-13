"""Experimental compact text: readable headers and lossless IEEE-754 coefficients.

The reference remains state-hermite-v1. XOR and byte shuffling are reversible
storage transforms; no interpolation, coefficient fitting or rounding is added.
"""
import base64,copy,json,textwrap,zlib
import numpy as np
from .motion_text import dumps

FIELDS=('q','v','a','u','K')
CODEC='f64-xor-shuffle-zlib-base64'

def compact_bytes(doc):
    value=dict(v=3,n=doc['n'],ends=doc['ends'],model=doc['model_sha256'])
    d=doc['n']+1
    for name in ('ab','ba'):
        data=copy.deepcopy(doc[name]);count=len(data['q']);parts=[];integers=[];offset=0
        for key,width in zip(FIELDS,(d,d,d,1,2*d)):
            original=data.pop(key);array=np.asarray(original,dtype='<f8')
            expected=(count,) if key=='u' else (count,width)
            if array.shape!=expected or not np.isfinite(array).all():raise ValueError('Invalid coefficient shape')
            flat=array.ravel(order='F');parts.append(flat)
            original_flat=[original[r] for r in range(count)] if key=='u' else [original[r][c] for c in range(width) for r in range(count)]
            integers.extend(offset+i for i,v in enumerate(original_flat) if isinstance(v,int) and not isinstance(v,bool))
            offset+=len(flat)
        bits=np.concatenate(parts).view('<u8');delta=bits.copy();delta[1:]^=bits[:-1]
        shuffled=delta.view(np.uint8).reshape(-1,8).T.copy().tobytes()
        direction=dict(T=data.pop('T'),nodes=count,codec=CODEC)
        h=data.pop('h')
        if h!=direction['T']/(count-1):direction['h']=h
        if integers:direction['integers']=integers
        direction.update(data);direction['hash']=direction.pop('runtime_sha256')
        if 'origin_sha256' in direction:direction['origin']=direction.pop('origin_sha256')
        direction['coefficients']=base64.b64encode(zlib.compress(shuffled,9)).decode('ascii')
        value[name]=direction
    lines=[]
    for line in dumps(value).splitlines():
        if line.startswith('coefficients = '):
            body=json.loads(line.partition(' = ')[2]);lines.extend(['coefficients = """',*textwrap.wrap(body,96),'"""'])
        else:lines.append(line)
    return ('# Compact, lossless state-Hermite coefficients. SI units; passive rods, cart force only.\n'+'\n'.join(lines)+'\n').encode('utf8')

def expand(doc):
    if doc.get('v')!=3 or not isinstance(doc.get('n'),int) or not 1<=doc['n']<=20:raise ValueError('Invalid compact motion header')
    value=dict(v=2,n=doc['n'],ends=doc['ends'],model_sha256=doc['model'],basis='state-hermite-v1');d=doc['n']+1
    for name in ('ab','ba'):
        data=copy.deepcopy(doc[name]);count=data.pop('nodes')
        if not isinstance(count,int) or not 2<=count<=20000 or data.pop('codec')!=CODEC:raise ValueError('Invalid compact coefficient codec')
        size=count*(5*d+1)*8;body=''.join(data.pop('coefficients').split())
        if len(body)>2*size+1024:raise ValueError('Oversized compact payload')
        packed=base64.b64decode(body,validate=True);decoder=zlib.decompressobj();raw=decoder.decompress(packed,size+1)
        if len(raw)!=size or not decoder.eof or decoder.unused_data:raise ValueError('Invalid compact payload size')
        delta=np.frombuffer(raw,dtype=np.uint8).reshape(8,-1).T.copy().reshape(-1).view('<u8')
        bits=np.bitwise_xor.accumulate(delta);numbers=bits.view('<f8')
        if not np.isfinite(numbers).all():raise ValueError('Nonfinite compact coefficient')
        integers=set(data.pop('integers',[]));offset=0
        if any(not isinstance(i,int) or not 0<=i<len(numbers) for i in integers):raise ValueError('Invalid integer positions')
        for key,width in zip(FIELDS,(d,d,d,1,2*d)):
            part=numbers[offset:offset+count*width].tolist()
            for i in range(len(part)):
                if offset+i in integers:part[i]=int(part[i])
            data[key]=part if key=='u' else [[part[c*count+r] for c in range(width)] for r in range(count)]
            offset+=count*width
        data['h']=data.get('h',data['T']/(count-1));data['runtime_sha256']=data.pop('hash')
        if 'origin' in data:data['origin_sha256']=data.pop('origin')
        value[name]=data
    return value
