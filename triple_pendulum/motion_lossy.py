"""Bounded-lossy full-node references with fresh physical/Worker acceptance.

q/v/u use explicit absolute quantization steps. A fixed passive predictor plus
integer residuals and reversible differencing reduce storage. Acceleration and
TVLQR are regenerated; original IEEE754 references are not claimed unchanged.
"""
import base64,json,lzma,struct,textwrap
import numpy as np
from .model import Plant,Parameters
from .planner import tracking_gains
from .motion_text import dumps

CODEC='mixed-quant-v1'
FILTERS=[dict(id=lzma.FILTER_LZMA2,dict_size=1<<20,preset=6)]
GRIDS=((1e-8,1e-7,1e-5),(1e-7,1e-6,1e-4),(1e-6,1e-5,.001),(5e-6,5e-5,.005),(1e-5,1e-4,.01),(5e-5,5e-4,.02))


def pack_stream(raw):return base64.b85encode(lzma.compress(raw,format=lzma.FORMAT_RAW,filters=FILTERS)).decode('ascii')


def unpack_stream(body):
    body=''.join(body.split())
    if len(body)>1_000_000:raise ValueError('Oversized lossy reference')
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_RAW,filters=FILTERS)
    raw=decoder.decompress(base64.b85decode(body),max_length=2_000_001)
    if len(raw)>2_000_000 or not decoder.eof or decoder.unused_data:raise ValueError('Invalid lossy stream')
    return raw


def shuffled_bits(bits):
    return np.asarray(bits,dtype='<u8').ravel(order='F').view(np.uint8).reshape(-1,8).T.copy().tobytes()


def unshuffled_bits(raw,count,width):
    return np.frombuffer(raw,np.uint8).reshape(8,-1).T.copy().reshape(-1).view('<u8').reshape(width,count).T.copy()


def encode_additive(plan,level=2,order=2):
    from . import _native
    plant=Plant(Parameters(**plan['parameters']));states=np.asarray(plan['states']);count,m=states.shape;d=m//2;qe,ve,ue=GRIDS[level];scales=np.r_[np.full(d,qe),np.full(d,ve)]
    integers=np.rint(states/scales).astype('<i8');quantized=np.ascontiguousarray(integers*scales);quantized[0]=plan['initial']
    ui=np.rint(np.asarray(plan['forces'])/ue).astype('<i8');forces=ui*ue
    bits=quantized.view('<u8');prediction=(_native.state_corrections(quantized,forces,plan['dt'],*plant.args)^bits).view('<f8')
    residual=integers-np.rint(prediction/scales).astype('<i8');residual[0]=0
    values=np.column_stack((ui,residual));delta=values.copy()
    for _ in range(order):delta[1:]-=delta[:-1]
    zigzag=((delta<<1)^(delta>>63)).astype('<u8');raw=struct.pack('<HBB',count,level,order)+shuffled_bits(zigzag)
    return dict(T=plan['duration'],h=plan['dt'],kind='a',data=pack_stream(raw))


def restore_additive(data,n,source,target):
    from . import _native
    plant=Plant(Parameters(n=n));d=n+1;m=2*d;raw=unpack_stream(data['data']);count,level,order=struct.unpack('<HBB',raw[:4])
    if not 2<=count<=20000 or not 0<=level<len(GRIDS) or not 0<=order<=8 or len(raw)!=4+count*(m+1)*8:raise ValueError('Invalid additive reference')
    bits=unshuffled_bits(raw[4:],count,m+1);values=((bits>>1).astype('<i8')^-((bits&1).astype('<i8')))
    for _ in range(order):values=np.cumsum(values,axis=0,dtype=np.int64)
    qe,ve,ue=GRIDS[level];scales=np.r_[np.full(d,qe),np.full(d,ve)];forces=values[:,0]*ue
    states=np.zeros((count,m));states[0,1:d]=[0. if c=='U' else np.pi for c in source];h=float(data['h']);T=float(data['T'])
    if not 0<T<=120 or abs(h*(count-1)-T)>1e-7:raise ValueError('Invalid additive clock')
    pair=np.zeros((2,m));upair=np.zeros(2)
    for k in range(1,count):
        pair[0]=states[k-1];upair[:]=forces[k-1:k+1];prediction=_native.state_corrections(pair,upair,h,*plant.args)[1].view('<f8')
        states[k]=(np.rint(prediction/scales)+values[k,1:])*scales
    if not np.isfinite(states).all():raise ValueError('Nonfinite additive reference')
    goal=[0. if c=='U' else float(np.pi) for c in target]
    plan=dict(duration=T,dt=h,initial=states[0].tolist(),target_angles=goal,states=states.tolist(),forces=forces.tolist())
    acc=plant.batch(states,forces)[:,d:];plan['derivatives']=np.column_stack((states[:,d:],acc)).tolist();plan['gains']=tracking_gains(plant,plan)
    plan.update(parameters=plant.p.dict(),transition=dict(order=n,source=source,target=target),pattern=target,force_rate=500.,strict_rest=True,success=True,source='有限有损定精度参考 · 重新验收')
    return plan


def motion_bytes(n,ends,model,directions,origin=None):
    value=dict(v=5,n=n,ends=ends,model=model,codec=CODEC)
    value.update(directions);lines=[]
    for line in dumps(value).splitlines():
        if line.startswith('data = '):
            body=json.loads(line.partition(' = ')[2]);lines.extend(['data = """',*textwrap.wrap(body,96),'"""'])
        else:lines.append(line)
    return ('\n'.join(lines)+'\n').encode('utf8')


def acceptance_token(plan,proof,worker):
    from .motion_plugins import digest,runtime
    if not proof['final_stable'] or worker['rail_contacts'] or worker['live_planner_requests']:raise ValueError('Unaccepted lossy candidate')
    item=worker['individual'][0]
    values=[proof[k] for k in ('final_angle_deg','max_cart','max_force','max_force_rate','settled_at','max_tracking_error')]
    values += [item[k] for k in ('clock','angle_deg','max_cart','max_force','max_force_rate')]
    raw=struct.pack('<11f',*values)+bytes.fromhex(digest(runtime(plan)))+struct.pack('<HH',worker['rail_contacts'],worker['live_planner_requests'])
    return base64.b85encode(raw).decode('ascii')


def expand(doc):
    from .motion_plugins import pack,digest,runtime
    if doc.get('v')!=5 or doc.get('codec')!=CODEC or type(doc.get('n')) is not int or not 1<=doc['n']<=20:raise ValueError('Invalid lossy plugin')
    n=doc['n'];ends=doc['ends']
    if len(ends)!=2 or ends[0]==ends[1] or any(len(s)!=n or set(s)-set('UD') for s in ends):raise ValueError('Invalid lossy endpoints')
    result=dict(v=2,n=n,ends=ends,model_sha256=doc['model'],basis='state-hermite-v1',lossy=True)
    for key,source,target in [('ab',ends[0],ends[1]),('ba',ends[1],ends[0])]:
        data=doc[key];raw=base64.b85decode(data['check'])
        if len(raw)!=80:raise ValueError('Missing new lossy acceptance')
        values=struct.unpack('<11f',raw[:44]);plan=reconstruct(data,n,source,target)
        if digest(runtime(plan))!=raw[44:76].hex():raise ValueError('Lossy reference runtime mismatch')
        proof=dict(zip(('final_angle_deg','max_cart','max_force','max_force_rate','settled_at','max_tracking_error'),values[:6]),final_stable=True)
        item=dict(order=n,source=source,target=target,chain=False,**dict(zip(('clock','angle_deg','max_cart','max_force','max_force_rate'),values[6:])))
        contacts,requests=struct.unpack('<HH',raw[76:]);worker=dict(individual=[item],continuous=[],rail_contacts=contacts,live_planner_requests=requests)
        plan.update(verification=proof,worker_verification=worker);result[key]=dict(pack(plan),lossy=True)
    return result


def reconstruct(data,n,source,target):
    if data.get('kind')!='a':raise ValueError('Unsupported bounded-lossy reference')
    return restore_additive(data,n,source,target)
