"""Build versioned source distribution with no local credentials or runtime data."""
from pathlib import Path
import hashlib
import io
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
if not re.fullmatch(r'\d+\.\d+\.\d+', VERSION):
    raise SystemExit('Invalid VERSION')

FILES = [
    'rain_probe.py', 'sc3_setup.py', 'requirements.txt', 'setup.cmd',
    'configure-sc3.cmd', 'test-notification.cmd', 'monitor.cmd',
    'check-install.cmd', 'test_probe.py', 'VERSION', 'CHANGELOG.md',
]
OUT = ROOT / 'dist'
OUT.mkdir(exist_ok=True)
prefix = f'rain-alert-v{VERSION}'

program = io.BytesIO()
with zipfile.ZipFile(program, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in FILES:
        data = (ROOT / name).read_bytes()
        if re.search(rb'sctp\d+t[A-Za-z0-9_-]{15,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data):
            raise SystemExit('Credential-like value found in ' + name)
        archive.writestr('rain-alert/' + name, data)

manual = (ROOT / 'docs' / 'quickstart.pdf').read_bytes()
package = OUT / f'{prefix}-source-kit.zip'
with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(prefix + '/01_程序文件_先解压.zip', program.getvalue())
    archive.writestr(prefix + '/02_一页使用步骤.pdf', manual)
(OUT / f'{prefix}-quickstart.pdf').write_bytes(manual)
assets = [package, OUT / f'{prefix}-quickstart.pdf']
(OUT / 'SHA256SUMS.txt').write_text(''.join(
    hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in assets), encoding='utf-8')
print(json.dumps({'version': VERSION, 'source_files': len(FILES), 'assets': [p.name for p in assets] + ['SHA256SUMS.txt']}))
