"""Atomic local state and durable GitHub reservation checkpoints."""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'state/auto20.json'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def checkpoint(state):
    """A failed push aborts BEFORE a publishing mutation. Never force/rebase state."""
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise RuntimeError('Live posting requires the serialized main-branch GitHub workflow')
    write_json(STATE, state)
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True)
    git('config', 'user.name', 'github-actions[bot]')
    git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('add', 'state/auto20.json')
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode:
        git('commit', '-m', 'Persist publishing reservation/receipt [skip ci]')
    for attempt in range(3):
        try:
            git('push', 'origin', 'HEAD:main')
            return
        except subprocess.CalledProcessError as exc:
            # Never print raw transport output: URLs can contain credentials.
            detail=(exc.stderr or '').lower()
            reason=('remote_advanced' if 'non-fast-forward' in detail or 'fetch first' in detail
                    else 'permission_denied' if 'permission' in detail or '403' in detail
                    else 'transport_or_server_error')
            print('STATE PUSH FAILED', reason, 'attempt', attempt+1, flush=True)
            if reason!='transport_or_server_error' or attempt==2:
                raise
            time.sleep(2*(attempt+1))
