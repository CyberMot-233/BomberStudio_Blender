"""Run Source integration in isolated Blender profiles. Does not save user prefs."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from run_matrix import ROOT, TMP, RUNTIMES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=TMP / ('source-tests-' + time.strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--versions', nargs='*')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def run(entry):
        version, exe = entry
        out = args.output / version
        out.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                   BLENDER_USER_CONFIG=str(out / 'config'), BLENDER_USER_SCRIPTS=str(out / 'scripts'),
                   BLENDER_USER_EXTENSIONS=str(out / 'extensions'), TEMP=str(TMP), TMP=str(TMP))
        if version == '2.79b':
            env['OCIO'] = '2.79/datafiles/colormanagement/config.ocio'
        row = {'version': version, 'log': str(out / 'test.log')}
        try:
            started = time.time()
            with (out / 'test.log').open('w', encoding='utf8') as log:
                result = subprocess.run([
                    str(exe), '-b', '--factory-startup', '--threads', '2', '--python-exit-code', '1',
                    '--python', str(ROOT / 'tests/source_integration.py'), '--', str(ROOT), str(out)],
                    stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(exe.parent), timeout=180,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            row['returncode'] = result.returncode
            path = out / 'source-results.json'
            if path.is_file() and path.stat().st_mtime >= started:
                row['result'] = json.loads(path.read_text(encoding='utf8'))
            row['passed'] = result.returncode == 0 and row.get('result', {}).get('failed', 1) == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            row.update(passed=False, error=str(exc))
        if not row['passed'] and (out / 'test.log').exists():
            row['error_tail'] = (out / 'test.log').read_text(encoding='utf8', errors='replace')[-5000:]
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    entries = [e for e in RUNTIMES if not args.versions or e[0] in args.versions]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run, entries))
    (args.output / 'matrix-results.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf8')
    return 0 if rows and all(row['passed'] for row in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
