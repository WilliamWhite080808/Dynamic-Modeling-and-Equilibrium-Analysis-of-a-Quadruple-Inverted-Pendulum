"""Readable, lossless TOML motion files; one matrix node per physical line."""
import json,tomllib

def scalar(value):
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,str):return json.dumps(value,ensure_ascii=False)
    if isinstance(value,(int,float)):return repr(value)
    raise TypeError(type(value))

def array(value):return '['+', '.join(array(x) if isinstance(x,list) else scalar(x) for x in value)+']'

def dumps(value):
    lines=[]
    def table(data,path='',header=False):
        if header:lines.extend(['','['+path+']'])
        for k,v in data.items():
            k=str(k)
            if v is None or isinstance(v,dict) or (isinstance(v,list) and v and isinstance(v[0],dict)):continue
            if isinstance(v,list) and len(v)>8:
                lines.append(k+' = [')
                if v and isinstance(v[0],list):lines.extend('  '+array(row)+',' for row in v)
                else:
                    for i in range(0,len(v),8):lines.append('  '+', '.join(scalar(x) for x in v[i:i+8])+',')
                lines.append(']')
            else:lines.append(k+' = '+(array(v) if isinstance(v,list) else scalar(v)))
        for k,v in data.items():
            k=str(k)
            child=path+'.'+k if path else k
            if isinstance(v,dict):table(v,child,True)
            elif isinstance(v,list) and v and isinstance(v[0],dict):
                for row in v:
                    lines.extend(['','[['+child+']]']);table(row,child)
    table(value)
    return '\n'.join(lines).lstrip()+'\n'

def motion_bytes(doc):
    value=dict(v=2,n=doc['n'],ends=doc['ends'],model=doc['model_sha256'])
    for name in ('ab','ba'):
        data=dict(doc[name]);T=data.pop('T');h=data.pop('h')
        direction=dict(T=T)
        if h!=T/(len(data['q'])-1):direction['h']=h
        direction.update(data)
        direction['hash']=direction.pop('runtime_sha256')
        if 'origin_sha256' in direction:direction['origin']=direction.pop('origin_sha256')
        value[name]=direction
    return ('# 被动自由摆；只有小车牵引。U 向上，D 向下；SI 单位，角度为弧度。\n'
            '# q 坐标 / v 速度 / a 加速度 / u 牵引力 / K 反馈增益；每行一个节点。\n'
            +dumps(value)).encode('utf8')

def loads(raw):
    if isinstance(raw,bytes):raw=raw.decode('utf-8-sig')
    return tomllib.loads(raw)

def read_motion(raw):
    text=raw.decode('utf-8-sig') if isinstance(raw,bytes) else raw
    if text.lstrip().startswith('{'):return json.loads(text)
    doc=loads(text)
    if doc.get('v')==5:
        from .motion_lossy import expand
        return expand(doc)
    if doc.get('v')==4:
        from .motion_recipe import expand
        return expand(doc)
    if doc.get('v')==3:
        from .motion_codec import expand
        return expand(doc)
    if doc.get('v')!=2:raise ValueError('不支持的文本轨迹版本')
    doc['basis']='state-hermite-v1';doc['model_sha256']=doc.pop('model')
    for name in ('ab','ba'):
        data=doc[name]
        if 'h' not in data:data['h']=data['T']/(len(data['q'])-1)
        data['runtime_sha256']=data.pop('hash')
        if 'origin' in data:data['origin_sha256']=data.pop('origin')
    return doc
