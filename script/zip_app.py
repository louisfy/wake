#!/usr/bin/env python3
"""Portable UTF-8 app ZIP, preserving executable bits and internal symlinks only."""
from pathlib import Path
import os
import stat
import sys
import zipfile


def pack(bundle,destination):
    bundle=Path(bundle).resolve()
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(bundle.rglob('*')):
            if p.is_dir() and not p.is_symlink():continue
            name=bundle.name+'/'+str(p.relative_to(bundle))
            info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
            info.create_system=3
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=p.lstat().st_mode<<16
            if p.is_symlink():
                if not p.resolve().is_relative_to(bundle):raise ValueError('External bundle symlink rejected')
                data=os.readlink(p).encode()
            else:data=p.read_bytes()
            archive.writestr(info,data)


if __name__=='__main__':pack(*sys.argv[1:])
