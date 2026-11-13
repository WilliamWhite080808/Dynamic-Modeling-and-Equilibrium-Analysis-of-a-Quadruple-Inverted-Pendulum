"""Audit every exported direction against its admitted, immutable source bytes."""
from pathlib import Path
import collections, hashlib, json, sys, time
from triple_pendulum.motion_text import read_motion, loads
from triple_pendulum.motion_plugins import unpack, runtime, digest
from triple_pendulum.model import Parameters
from triple_pendulum import transitions

def main():
    web, desktop = map(Path, sys.argv[1:3])
    model = loads((web/'models/standard.toml').read_bytes())
    counts, items = collections.Counter(), []
    ready = transitions.statuses()
    for file in sorted((web/'motions').glob('*.toml')):
        raw = file.read_bytes()
        assert raw == (desktop/'motions'/file.name).read_bytes(), file
        doc = read_motion(raw)
        n, (a, b) = doc['n'], doc['ends']
        params = Parameters(n=n, **model['parameters']).dict()
        for direction, source, target in (('ab', a, b), ('ba', b, a)):
            data = doc[direction]
            plan = unpack(data, n, source, target, params)
            row = ready[transitions.key(n, source, target)]
            original = transitions.ROOT/row['file']
            original_bytes = original.read_bytes()
            original_plan = json.loads(original_bytes)
            assert hashlib.sha256(original_bytes).hexdigest() == data['origin_sha256'], original
            assert runtime(plan) == runtime(original_plan), original
            assert row['status'] == 'ready' and row['sha256'] == data['origin_sha256']
            if n == 5:
                worker = data.get('worker', {})
                assert worker.get('individual') and worker.get('rail_contacts') == 0 and worker.get('live_planner_requests') == 0, original
            assert not original_plan.get('segments') and not original_plan.get('route_waypoints')
            counts[n] += 1
            items.append(f'{n}-{source}-{target}:{digest(runtime(plan))}')
    report = dict(passed=True, pairs=len(items)//2, directions=len(items), orders=dict(counts),
                  exact_source_control_equality=True, independent_ab_ba_origins=True,
                  fifth_worker_proofs=True, sha256=hashlib.sha256('\n'.join(sorted(items)).encode()).hexdigest(),
                  checked_at=time.time())
    target = Path('results/editions-acceptance/all-paths.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
