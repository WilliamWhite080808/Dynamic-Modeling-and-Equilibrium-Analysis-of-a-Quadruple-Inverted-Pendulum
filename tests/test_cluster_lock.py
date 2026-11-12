import json,os,time
from concurrent.futures import ThreadPoolExecutor
from triple_pendulum.repository import directory_lock


def test_shared_directory_lock_serializes_independent_writers(tmp_path):
    counter=tmp_path/'counter.json';counter.write_text('0')
    def write():
        for _ in range(20):
            with directory_lock(tmp_path,timeout=20):
                value=json.loads(counter.read_text());counter.write_text(json.dumps(value+1))
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:write(),range(8)))
    assert json.loads(counter.read_text())==160
    assert not (tmp_path/'.write.lockdir').exists()


def test_stale_cluster_lock_is_preserved_and_replaced(tmp_path):
    directory=tmp_path/'.write.lockdir';directory.mkdir();(directory/'owner.json').write_text(json.dumps(dict(token='dead-owner')))
    before=time.time()-1000;os.utime(directory,(before,before))
    with directory_lock(tmp_path,timeout=2,stale_seconds=300):
        assert json.loads((directory/'owner.json').read_text())['token']!='dead-owner'
    assert not directory.exists()
    assert len(list(tmp_path.glob('.write.lockdir.stale-*')))==1
