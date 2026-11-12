import asyncio
from pathlib import Path
import pytest
from fastapi import HTTPException
from triple_pendulum import server

class Upload:
    def __init__(self,parts,mime='video/webm'):self.parts=parts;self.headers={'content-type':mime}
    async def stream(self):
        for part in self.parts:yield part

def test_core_recording_is_saved_and_downloadable(tmp_path,monkeypatch):
    root=tmp_path/'recordings';monkeypatch.setattr(server,'RECORDINGS',root)
    data=b'\x1aE\xdf\xa3recorded-canvas'
    result=asyncio.run(server.store_recording(Upload([data[:4],data[4:]],'video/webm;codecs=vp8')))
    assert (root/result['id']).read_bytes()==data and result['bytes']==len(data)
    response=server.recording_file(result['id']);assert Path(response.path).read_bytes()==data and response.media_type=='video/webm'
    with pytest.raises(HTTPException):server.recording_file('../index.html')

def test_recording_rejects_bad_uploads_and_cleans_partial_files(tmp_path,monkeypatch):
    root=tmp_path/'recordings';monkeypatch.setattr(server,'RECORDINGS',root);monkeypatch.setattr(server,'MAX_RECORDING_BYTES',4)
    for upload,code in [(Upload([b'12345']),413),(Upload([]),400),(Upload([b'x'],'text/html'),415)]:
        with pytest.raises(HTTPException) as error:asyncio.run(server.store_recording(upload))
        assert error.value.status_code==code
    assert not list(root.glob('*'))
