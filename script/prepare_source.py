#!/usr/bin/env python3
"""Export only audited source; does not initialize Git, commit, or contact GitHub."""
import hashlib
import json
from pathlib import Path
import zipfile
from privacy_check import check_source,check_archive
from public_files import public_files

root=Path(__file__).resolve().parents[1]
check_source(root)
target=root/'dist/Wake-1.0-source.zip'
target.parent.mkdir(exist_ok=True)
manifest={}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in public_files(root):
        name=str(p.relative_to(root))
        data=p.read_bytes()
        manifest[name]=hashlib.sha256(data).hexdigest()
        info=zipfile.ZipInfo('Wake-source/'+name,date_time=(2020,1,1,0,0,0))
        info.external_attr=(0o100755 if p.suffix in ('.sh','.command') else 0o100644)<<16
        info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,data)
check_archive(target)
(target.parent/'source-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
binary=target.with_name('Wake-1.0-macos-arm64.zip')
(target.parent/'SHA256SUMS.txt').write_text(''.join(
    hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (target,binary) if p.is_file()))
print('Prepared audited source archive:',target.name)
