import gzip,hashlib,io,json,tarfile,tomllib
from triple_pendulum import artifact_archive as archive

def test_historical_tar_numeric_data_is_preserved_and_independent(tmp_path,monkeypatch):
    old=tmp_path/'results/old';old.mkdir(parents=True)
    raw=b'{"states":[[0,3.141592653589793]],"force":0.0}'
    with tarfile.open(old/'candidate.tar.gz','w:gz') as bundle:
        item=tarfile.TarInfo('case.json');item.size=len(raw);bundle.addfile(item,io.BytesIO(raw))
    monkeypatch.setattr(archive,'OBSOLETE',('old',))
    archive.collect(tmp_path);report=archive.finalize(tmp_path)
    doc=tomllib.loads((tmp_path/'results/history/index.toml').read_text('utf8'))
    row=next(r for r in doc['records'] if r['source'].endswith('!/case.json'))
    payload=(tmp_path/'results/history'/row['object']).read_bytes()
    if row['compression']=='gzip':payload=gzip.decompress(payload)
    assert payload==raw and row['sha256']==hashlib.sha256(raw).hexdigest()
    assert report['independent_of_working_files']

def test_failed_transfer_container_is_kept_as_exact_bytes(tmp_path,monkeypatch):
    old=tmp_path/'results/old';old.mkdir(parents=True)
    (old/'empty.tar.gz').write_bytes(b'');(old/'partial.tar.gz').write_bytes(b'incomplete transfer')
    monkeypatch.setattr(archive,'OBSOLETE',('old',));archive.collect(tmp_path);archive.finalize(tmp_path)
    doc=tomllib.loads((tmp_path/'results/history/index.toml').read_text('utf8'))
    assert {r['bytes'] for r in doc['records']}=={0,19}
