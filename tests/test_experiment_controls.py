import json,subprocess
from triple_pendulum import transitions,repository
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.control import analyze

def test_seek_rate_and_automatic_cycle_use_the_real_worker(tmp_path):
    plant=Plant(Parameters(n=4));plan=transitions.lookup(plant,'DDDD','UUUU')
    fixture=tmp_path/'controls.json';fixture.write_text(json.dumps(dict(design=analyze(plant,target=repository.angles('UUUU')),plan=plan)),encoding='utf8')
    result=subprocess.run(['node','tests/check-experiment-controls.mjs',str(fixture)],capture_output=True,text=True,encoding='utf8')
    assert result.returncode==0,result.stdout+result.stderr
