import subprocess

def test_live_signal_sampling_and_peak_preservation():
    result=subprocess.run(['node','tests/check-telemetry.mjs'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
