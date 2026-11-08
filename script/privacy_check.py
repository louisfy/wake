#!/usr/bin/env python3
"""Local pattern and publication-boundary checks. Never print matched values."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile
from public_files import public_files

RULES = {
    'absolute-user-home': re.compile(b'/' + rb'Users/[^/\s]+/'),
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'provider-token': re.compile(rb'sk-[A-Za-z0-9_-]{32,}'),
    'url-password': re.compile(rb'https?://[^\s/@:]+:[^\s/@]+@'),
}


def check_bytes(name,data):
    for rule,pattern in RULES.items():
        if pattern.search(data):raise ValueError(name+': '+rule)
    if name.endswith('/products.seed.json') or name=='Resources/products.seed.json':
        config=json.loads(data)
        if config.get('products')!=[] or config.get('scan_roots')!=[]:
            raise ValueError(name+': non-empty personal seed')
    if name.endswith('/migration.json') and json.loads(data)!={}:
        raise ValueError(name+': non-empty legacy migration')


def check_source(root):
    paths=public_files(root)
    allowed={str(p.relative_to(root)) for p in paths}
    if (root/'.git').exists():
        tracked=subprocess.run(['git','-C',str(root),'ls-files','-z'],capture_output=True,check=True).stdout
        unexpected={p.decode() for p in tracked.split(b'\0') if p}-allowed
        if unexpected:raise ValueError('Tracked file outside publication boundary: '+sorted(unexpected)[0])
    for p in paths:check_bytes(str(p.relative_to(root)),p.read_bytes())
    return len(paths)


def check_archive(path):
    with zipfile.ZipFile(path) as archive:
        count=0
        for item in archive.infolist():
            name=item.filename
            parts=PurePosixPath(name).parts
            if (not parts or PurePosixPath(name).is_absolute() or '..' in parts
                    or '__MACOSX' in parts or any(p.startswith('._') for p in parts)):
                raise ValueError('Unsafe or metadata archive member')
            if any(p in ('products.json','Health.json','Wake.log','approvals.json','.env','Signing','Runtime') for p in parts):
                raise ValueError(name+': runtime/private data')
            if not item.is_dir():
                check_bytes(name,archive.read(item));count+=1
        return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',action='store_true')
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    try:
        if args.source:print('Source publication checks passed:',check_source(Path(__file__).resolve().parents[1]),'files')
        if args.archive:print('Archive publication checks passed:',check_archive(args.archive),'files')
        if not args.source and not args.archive:parser.error('Choose --source or --archive')
    except (ValueError,OSError,zipfile.BadZipFile) as error:
        print('Publication check failed:',error,file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
