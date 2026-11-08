"""Explicit publication boundary shared by audit and source export."""
from pathlib import Path

ROOT_FILES = {'Package.swift','runtime.lock.json','.gitignore','.gitattributes','README.md','README.en.md','README.zh-CN.md',
              'LICENSE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','SECURITY.md','PRIVACY.md','CHANGELOG.md','Preview.command'}
TREES = {'Core':{'.py'},'Sources':{'.swift'},'Tests':{'.py'},'script':{'.py','.sh'},
         'Resources':{'.json','.png'},'docs':{'.md'},'.github':{'.yml','.md'},
         'examples':{'.py','.json','.html','.md'}}
DOC_IMAGES = {'docs/media/hero.png','docs/media/workbench.png','docs/media/discovery.png',
              'docs/media/zh-CN/hero.png','docs/media/zh-CN/workbench.png'}
EXTRA_FILES = DOC_IMAGES | {
    'Core/messages.en.json',
    'Resources/zh-Hans.lproj/Localizable.strings','Resources/zh-Hans.lproj/InfoPlist.strings',
}
IGNORED = {'.git','.build','.build-native','.swiftpm','dist','.local-notes','.local','work','.DS_Store','AGENTS.md','.agents','.codex'}


def public_files(root):
    root=Path(root)
    result=[]
    for entry in root.iterdir():
        if entry.name in IGNORED:continue
        if entry.is_symlink():raise ValueError('Publication symlink rejected: '+entry.name)
        if entry.is_file() and entry.name in ROOT_FILES:result.append(entry)
        elif entry.is_dir() and entry.name in TREES:
            for p in entry.rglob('*'):
                if '__pycache__' in p.parts or p.name=='.DS_Store':continue
                if p.is_symlink():raise ValueError('Publication symlink rejected: '+str(p.relative_to(root)))
                if p.is_file():
                    if p.suffix not in TREES[entry.name] and p.relative_to(root).as_posix() not in EXTRA_FILES:
                        raise ValueError('Unexpected publication file: '+str(p.relative_to(root)))
                    result.append(p)
        else:raise ValueError('Unexpected publication path: '+entry.name)
    return sorted(result,key=lambda p:str(p.relative_to(root)))
