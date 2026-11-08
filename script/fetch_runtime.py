#!/usr/bin/env python3
"""Fetch a pinned public runtime, verify before safe extraction; no app/user data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def license_paths(value):
    paths=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('license_path','license_paths'):
                paths.update([item] if isinstance(item,str) else item)
            else:paths.update(license_paths(item))
    elif isinstance(value,list):
        for item in value:paths.update(license_paths(item))
    return paths


def download(spec,cache,suffix):
    archive=cache/(spec['sha256']+suffix)
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest()==spec['sha256']:
        return archive
    pending=archive.with_suffix('.pending')
    subprocess.run(['/usr/bin/curl','--fail','--location','--silent','--show-error',
                    '--continue-at','-','--connect-timeout','15','--max-time','600',
                    spec['url'],'--output',str(pending)],check=True)
    if hashlib.sha256(pending.read_bytes()).hexdigest()!=spec['sha256']:
        pending.unlink(missing_ok=True)
        raise ValueError('Runtime SHA-256 mismatch')
    pending.replace(archive)
    return archive


def copy_licenses(archive,target,lock,cache):
    zstd=shutil.which('zstd')
    if not zstd:raise ValueError('Build prerequisite missing: zstd (for example: brew install zstd)')
    with tempfile.TemporaryDirectory(dir=cache) as stage:
        unpacked=Path(stage)/'full.tar'
        with unpacked.open('wb') as output:
            subprocess.run([zstd,'--decompress','--stdout',str(archive)],stdout=output,check=True)
        with tarfile.open(unpacked,'r:') as tar:
            metadata=json.load(tar.extractfile('python/PYTHON.json'))
            paths=license_paths(metadata)
            paths.update(m.name.removeprefix('python/') for m in tar.getmembers()
                         if m.isfile() and m.name.startswith('python/licenses/'))
            if not paths:raise ValueError('Full runtime metadata contains no license paths')
            licenses=Path(stage)/'licenses'
            licenses.mkdir()
            for path in sorted(paths):
                relative=Path(path)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe license path')
                member=tar.getmember('python/'+path)
                if not member.isfile() or member.size>4*1024*1024:raise ValueError('Invalid license file')
                output=licenses/relative
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_bytes(tar.extractfile(member).read())
            (licenses/'license-index.json').write_text(json.dumps(dict(
                provider=lock['provider'],release=lock['release'],archive_sha256=lock['licenses_archive']['sha256'],
                format_version=2,files=sorted(paths)),indent=2)+'\n')
        if (target/'upstream-licenses').exists():shutil.rmtree(target/'upstream-licenses')
        shutil.move(str(licenses),target/'upstream-licenses')


def extract(archive, destination):
    with tarfile.open(archive, 'r:gz') as tar:
        for item in tar.getmembers():
            path = Path(item.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'python':
                raise ValueError('Unsafe runtime archive member')
            if item.isdev() or item.isfifo() or item.islnk():
                raise ValueError('Unsupported runtime archive member')
            if item.issym():
                resolved = os.path.normpath(str(path.parent / item.linkname))
                if Path(item.linkname).is_absolute() or not resolved.startswith('python/'):
                    raise ValueError('Unsafe runtime link')
        tar.extractall(destination)


def main():
    lock = json.loads((ROOT / 'runtime.lock.json').read_text())
    cache = ROOT / '.build-native' / 'runtime-cache'
    cache.mkdir(parents=True, exist_ok=True)
    archive = download(lock,cache,'.tar.gz')
    target = cache / lock['sha256']
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=cache) as stage:
            extract(archive, stage)
            shutil.move(str(Path(stage) / 'python'), target)
    index=target/'upstream-licenses/license-index.json'
    if (not index.exists() or json.loads(index.read_text()).get('archive_sha256')!=lock['licenses_archive']['sha256']
            or json.loads(index.read_text()).get('format_version')!=2):
        full=download(lock['licenses_archive'],cache,'.tar.zst')
        copy_licenses(full,target,lock,cache)
    print(target)


if __name__ == '__main__':
    main()
