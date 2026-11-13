import zipfile
from triple_pendulum.build_editions import zip_edition

def test_archive_reuses_verified_members_and_keeps_only_portable_preload(tmp_path):
    folder=tmp_path/'网页版';folder.mkdir();(folder/'keep.txt').write_bytes(b'unchanged'*900)
    (folder/'change.txt').write_bytes(b'before');target=tmp_path/'网页版.zip';zip_edition(folder,target)
    (folder/'change.txt').write_bytes(b'after');(folder/'.cache/motions').mkdir(parents=True)
    (folder/'.cache/motions/a.json.gz').write_bytes(b'cached-control');(folder/'.cache/trajectory-index.json').write_text('{}')
    (folder/'.cache/instance.json').write_text('private runtime state')
    zip_edition(folder,target)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.read('网页版/keep.txt')==b'unchanged'*900
        assert archive.read('网页版/change.txt')==b'after'
        assert archive.read('网页版/.cache/motions/a.json.gz')==b'cached-control'
        assert '网页版/.cache/instance.json' not in archive.namelist()
