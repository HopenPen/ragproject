# Назначение файла: безопасный subprocess wrapper неизменённого solar checker.
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

EXPECTED_SHA256 = '3e30dfce04c67209a4aa9ca7bb0486a62d376c8650b33ec44d2c5c10c117c722'


def run_checker(checker, submission, pdf, timeout=120):
    checker = Path(checker)
    actual = hashlib.sha256(checker.read_bytes()).hexdigest()
    if actual != EXPECTED_SHA256:
        return {'status': 'blocked_external_configuration', 'reason': 'Original checker hash mismatch', 'sha256': actual}
    try:
        result = subprocess.run([sys.executable, str(checker), str(submission), str(pdf)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'}, shell=False)
        return {'status': 'executed', 'exit_code': result.returncode, 'stdout': result.stdout,
                'stderr': result.stderr, 'sha256': actual, 'scope': 'partial solar technical checks; not scientific acceptance'}
    except subprocess.TimeoutExpired:
        return {'status': 'failed', 'reason': 'checker_timeout', 'sha256': actual}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('checker', type=Path); parser.add_argument('submission', type=Path); parser.add_argument('pdf', type=Path)
    args = parser.parse_args()
    result = run_checker(args.checker, args.submission, args.pdf)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(result.get('exit_code', 2))
