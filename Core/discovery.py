"""Read local deployment metadata without installing dependencies or running projects."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import time

IGNORED={'node_modules','.git','.venv','venv','vendor','dist','build','target','.next','__pycache__',
         'Codex','outputs','deliverables','交付','tests','test','fixtures','examples','docs','packages',
         'plugins','capability-plugins','skills','Skills','Caches','Cache','output','temp','models','input',
         'backups','Library','Applications','Pods','DerivedData'}
COMPOSE=('docker-compose.local.yml','compose.yaml','compose.yml','docker-compose.yml','docker-compose.yaml')
PORT_FILES=('server.js','server.mjs','server.ts','app.js','app.py','server.py','main.py','vite.config.ts','vite.config.js')
WEB_TARGETS={80,443,3000,3001,5000,5001,5173,5670,7860,8000,8080,8088,8188,8501,9380,11434}


def read(path, limit=262144):
    try:
        with Path(path).open('r',errors='replace') as f:
            return f.read(limit)
    except (OSError,UnicodeError):
        return ''


def document(path):
    try:
        value=json.loads(read(path))
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):
        return {}


def absent(path):
    """Permission failures are not deletion evidence."""
    try:
        os.stat(path)
        return False
    except (FileNotFoundError,NotADirectoryError):
        return True
    except OSError:
        return False


def canonical(path):
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def inside(path, root):
    a,b=canonical(path),canonical(root)
    return a==b or a.startswith(b+os.sep)


def fingerprint(files):
    h=hashlib.sha256()
    for p in sorted(map(str,files)):
        h.update(p.encode());h.update(read(p).encode())
    return h.hexdigest()


def ports_from_text(text):
    patterns=[r'(?:--port\s+|-p\s+|\bPORT=)(\d{2,5})\b',
              r'\b(?:PORT|port|server_port)\s*[:=]\s*(\d{2,5})\b',
              r'\.listen\(\s*(\d{2,5})\b',
              r'[A-Z_]*PORT["\']\s*,\s*["\'](\d{2,5})["\']',
              r'http://(?:127\.0\.0\.1|localhost):(\d{2,5})']
    for pattern in patterns:
        values=list(dict.fromkeys(int(v) for v in re.findall(pattern,text)))
        values=[v for v in values if 1<=v<=65535]
        if len(values)==1:
            return values
    return []


def display_name(root, package=None):
    if package:
        value=package.get('productName') or package.get('displayName')
        if isinstance(value,str) and value.strip():return value.strip()[:80]
    title=re.search(r'<title[^>]*>([^<]+)</title>',read(root/'index.html'),re.I)
    if title and title.group(1).strip().lower() not in ('vite + react','vite + react + ts','react app','vite app'):
        return title.group(1).strip()[:80]
    return root.name


def base(root, kind, marker, identity=None):
    return dict(id='auto-'+hashlib.sha256(canonical(root).encode()).hexdigest()[:12],
                name=root.name,description='本地发现的服务',category='自动发现',icon='cube',color='blue',
                root=str(root),kind=kind,ports=[],required=[str(marker)],
                discovery=dict(auto=True,source=str(marker),identity=identity or canonical(marker),
                               fingerprint=fingerprint([marker])))


def package_service(root, node):
    marker=root/'package.json';data=document(marker)
    scripts=data.get('scripts') or {}
    if not isinstance(scripts,dict):return None
    action=next((key for key in ('start','dev','serve') if isinstance(scripts.get(key),str)),None)
    if not action:return None
    script=scripts[action]
    # A build, dependency install, test runner, or documentation script alone is not a web deployment.
    if not re.search(r'\b(node|vite|next|nuxt|astro|serve|http-server|python(?:3(?:\.\d+)?)?|uvicorn|react-scripts|webpack|parcel)\b',script):
        return None
    p=base(root,'process',marker,'npm:'+str(data.get('name') or root.name))
    p.update(name=display_name(root,data),description='Node.js 本地服务 · '+action,
             match=[['node'],['next-server'],['vite']],cwd_match=str(root),
             required=[str(marker),str(root/'node_modules')])
    sources=[marker]
    literal=ports_from_text(script)
    source_ports=[]
    for name in PORT_FILES:
        f=root/name
        if f.is_file():
            sources.append(f)
            source_ports=ports_from_text(read(f))
            if source_ports:break
    ports=literal or source_ports
    if 'vite' in script:
        p['description']='本地网页预览 · Vite 开发服务'
        # A proxy target's localhost URL is not the Vite frontend's listening port.
        vite_config='\n'.join(read(root/name) for name in ('vite.config.ts','vite.config.js','vite.config.mts','vite.config.mjs'))
        own_port=re.search(r'\bserver\s*:\s*\{[^}]*?\bport\s*:\s*(\d{2,5})',vite_config,re.S)
        ports=literal or ([int(own_port.group(1))] if own_port else [5173])
        cli=root/'node_modules/vite/bin/vite.js'
        p['command']=[node,str(cli),'--host','127.0.0.1','--port',str(ports[0]),'--strictPort']
        p['required'].append(str(cli))
    elif re.search(r'\bnext\s+(?:dev|start)\b',script):
        ports=ports or [3000]
        cli=root/'node_modules/next/dist/bin/next'
        mode='dev' if re.search(r'\bnext\s+dev\b',script) else 'start'
        p['command']=[node,str(cli),mode,'--hostname','127.0.0.1','--port',str(ports[0])]
        p['required'].append(str(cli))
        if mode=='start':p['required'].append(str(root/'.next/BUILD_ID'))
    else:
        npm=shutil.which('npm')
        p['command']=[npm or '/usr/local/bin/npm','run',action]
        p['required'].append(npm or '/usr/local/bin/npm')
        if not ports:
            for name in ('README.md','README-本地部署.md','readme.md'):
                ports=ports_from_text(read(root/name))
                if ports:break
    if not ports:
        p.update(kind='incomplete',description='发现启动脚本 · 服务端口待确认',
                 note='检测到 package.json 的启动脚本，但无法可靠识别本机端口；已保留目录入口，未自动执行。')
    else:
        p.update(ports=ports,url='http://127.0.0.1:%d/'%ports[0])
    app_source='\n'.join(read(root/name) for name in ('src/App.tsx','src/App.jsx','src/App.js'))
    if re.search(r'Get started|Vite \+ React',app_source) and re.search(r'setCount|Count is|count is',app_source):
        p.update(kind='incomplete',description='默认开发脚手架 · 业务页面待完成',note='源文件仍包含 Vite / React 默认计数器页面，未作为完整产品自动启用。')
    p['discovery']['fingerprint']=fingerprint(sources)
    p['discovery']['sources']=list(map(str,sources))
    return p


def python_service(root):
    for name in ('app.py','server.py','main.py','start_server.py'):
        marker=root/name
        if not marker.is_file():continue
        text=read(marker);ports=ports_from_text(text)
        mode=None
        if re.search(r'import\s+streamlit|from\s+streamlit',text):mode='streamlit';ports=ports or [8501]
        elif re.search(r'import\s+gradio|from\s+gradio',text) and '.launch(' in text:mode='script';ports=ports or [7860]
        elif re.search(r'uvicorn\.run\(|HTTPServer\(|ThreadingHTTPServer\(|app\.run\(',text):mode='script'
        elif name=='main.py' and (root/'custom_nodes').is_dir() and (root/'models').is_dir():mode='comfyui';ports=ports or [8188]
        if not mode:continue
        python=root/'.venv/bin/python'
        if not python.exists() and (root/'venv/bin/python').exists():python=root/'venv/bin/python'
        p=base(root,'process',marker,'python:'+canonical(root))
        p.update(name=display_name(root),description='Python 本地服务',required=[str(marker),str(python)],
                 match=[[str(marker)],['python'],['streamlit']],cwd_match=str(root))
        if mode=='streamlit':
            p['command']=[str(python),'-m','streamlit','run',str(marker),'--server.address','127.0.0.1','--server.port',str(ports[0])]
        elif mode=='comfyui':
            p['command']=[str(python),str(marker),'--listen','127.0.0.1','--port',str(ports[0])]
        else:p['command']=[str(python),str(marker)]
        if ports:p.update(ports=ports,url='http://127.0.0.1:%d/'%ports[0])
        else:p.update(kind='incomplete',description='发现 Python 服务 · 端口待确认',note='检测到服务入口，尚未可靠识别网页端口；不会自动执行。')
        return p
    return None


def compose_service(root, marker):
    text=read(marker)
    if not re.search(r'^services\s*:',text,re.M):return None
    pairs=[]
    # Read published ports only, never export .env or Compose credential values.
    for match in re.finditer(r'["\']?(?:(?:127\.0\.0\.1|0\.0\.0\.0|localhost):)?(\d{2,5}):(\d{2,5})(?:/tcp)?["\']?',text):
        host,target=map(int,match.groups())
        if host<=65535 and target<=65535:pairs.append((host,target))
    web=[host for host,target in pairs if target in WEB_TARGETS]
    p=base(root,'docker',marker,'compose:'+canonical(root))
    p.update(name=root.parent.name if root.name in ('docker','deploy','deployment') else root.name,
             description='Docker Compose 本地服务',icon='layers',compose=str(marker),
             reserved_ports=list(dict.fromkeys(host for host,_ in pairs)))
    if web:
        # One browser entry is sufficient; all published ports are still reserved against collisions.
        p.update(ports=[web[0]],url='http://127.0.0.1:%d/'%web[0])
    else:
        p.update(kind='incomplete',description='发现 Compose · 网页入口待确认',
                 note='未可靠识别 Compose 的网页发布端口；不会把数据库、队列或不确定的端口当作网页打开。')
    return p


def script_service(root):
    names=[]
    try:
        names=[p for p in root.iterdir() if p.is_file() and p.suffix in ('.command','.sh')
               and re.search(r'^(?:打开|启动|start|run[-_])',p.name,re.I)
               and not re.search(r'install|卸载|安装|stop|停止|test|测试',p.name,re.I)]
    except OSError:return None
    if not names:return None
    script=sorted(names,key=lambda p:(p.suffix!='.command',len(p.name)))[0]
    text=read(script);ports=ports_from_text(text)
    if not ports:
        for name in ('README.md','README-本地部署.md','readme.md'):
            ports=ports_from_text(read(root/name))
            if ports:break
    if not ports and not re.search(r'uvicorn|http\.server|node\s+\S*server|flask\s+run|streamlit|\bgradio\b',text,re.I):
        return None
    p=base(root,'process',script,'script:'+script.name)
    p.update(name=root.name,description='本地启动入口 · '+script.name,
             command=['/bin/zsh',str(script)],match=[['node'],['python'],['uvicorn'],[str(script)]],
             cwd_match=str(root))
    if ports:p.update(ports=ports,url='http://127.0.0.1:%d/'%ports[0])
    else:p.update(kind='incomplete',description='发现启动入口 · 服务端口待确认',
                  note='已发现启动脚本，未可靠识别对应服务端口；保留卡片供检查，不自动执行。')
    return p


def explicit_service(root):
    marker=root/'.launchpad.json'
    if not marker.is_file():return None
    data=document(marker)
    if not isinstance(data,dict):return None
    p=base(root,data.get('kind','process'),marker,'manifest:'+str(data.get('id') or canonical(root)))
    allowed={'name','description','category','icon','color','kind','ports','url','command','required',
             'match','cwd','cwd_match','note','compose','reserved_ports','app','open_app','port_strategy'}
    for key in allowed:
        if key in data:p[key]=copy.deepcopy(data[key])
    for key in ('cwd','cwd_match','compose','app','open_app'):
        if key in p and not os.path.isabs(p[key]):p[key]=str(root/p[key])
    p['required']=[str(root/x) if not os.path.isabs(x) else x for x in p.get('required',[])]
    if not p.get('ports') and not p.get('app') and not p.get('open_app'):
        p.update(kind='incomplete',note='产品清单未声明可核验的服务端口或应用入口。')
    return p


def detect(root, node):
    if (root/'.launchpad.json').is_file():return explicit_service(root)
    for name in COMPOSE:
        if (root/name).is_file():return compose_service(root,root/name)
    if (root/'package.json').is_file():
        p=package_service(root,node)
        if p:return p
    return script_service(root) or python_service(root)


def rewrite_paths(value, old, new):
    if isinstance(value,str):return value.replace(old,new)
    if isinstance(value,list):return [rewrite_paths(x,old,new) for x in value]
    if isinstance(value,dict):return {k:rewrite_paths(v,old,new) for k,v in value.items()}
    return value


def update_curated(p, live_ports=None):
    """Preserve deliberate names/commands; reconcile only authoritative paths and ports."""
    p=copy.deepcopy(p);old_root=p['root'];sources=[];port=None
    if p['kind']=='launchd' and Path(p.get('plist','')).is_file():
        sources.append(p['plist'])
        try:
            data=plistlib.loads(Path(p['plist']).read_bytes())
            cwd=data.get('WorkingDirectory')
            # WorkingDirectory can deliberately be the user's home.
            # Only relocate a product when its actual deployment files exist at the new root.
            expected=[x for x in p.get('required',[]) if inside(x,old_root)]
            if (isinstance(cwd,str) and Path(cwd).is_dir() and cwd!=old_root and expected
                    and all(Path(rewrite_paths(x,old_root,cwd)).exists() for x in expected)
                    and any(isinstance(arg,str) and inside(arg,cwd) for arg in data.get('ProgramArguments',[]))):
                p=rewrite_paths(p,old_root,cwd)
            # Only inspect numeric port fields. Never copy a LaunchAgent's environment or secrets.
            for key,value in data.get('EnvironmentVariables',{}).items():
                if re.fullmatch(r'(?:[A-Z_]+_)?PORT',key) and str(value).isdigit() and 1<=int(value)<=65535:
                    port=int(value);break
        except (OSError,ValueError,plistlib.InvalidFileException):pass
    root=Path(p['root'])
    if p['kind']=='incomplete':
        candidates=[root]+[Path(x).parent for x in p.get('required',[]) if Path(x).name in COMPOSE and Path(x).is_file()]
        discovered=next((value for place in candidates for value in [detect(place,shutil.which('node') or '/usr/local/bin/node')] if value and value['kind']!='incomplete'),None)
        if discovered:
            keep={key:p[key] for key in ('id','name','category','icon','color')}
            # Keep an intentional assigned port/command when a previously incomplete Vite app becomes ready.
            assigned={key:p[key] for key in ('ports','url','command') if key in p} if p.get('command') else {}
            aliases=p.get('discovery',{}).get('aliases',[])
            if discovered['root']!=p['root']:aliases=aliases+[p['root']]
            p=discovered;p.update(keep);p.update(assigned)
            p['discovery']['auto']=False;p['discovery']['aliases']=aliases
            p['note']='已检测到新的服务启动入口；依赖与实际就绪状态会继续单独核验。'
    owner=p.get('discovery',{}).get('port_source')
    if owner:
        source=Path(owner['file'])
        sources.append(str(source))
        match=re.search(owner['pattern'],read(source))
        if match and match.group(1).isdigit() and 1<=int(match.group(1))<=65535:
            port=int(match.group(1))
    if live_ports and len(live_ports)==1:
        port=live_ports[0]
    if port and len(p.get('ports',[]))==1 and p['kind'] not in ('incomplete','docker','app'):
        previous=p['ports'][0]
        if previous!=port:
            p['ports']=[port]
            if p.get('url'):p['url']=re.sub(r':%d(?=/|$)'%previous,':'+str(port),p['url'])
            p['match']=[[str(port) if piece==str(previous) else piece for piece in group] for group in p.get('match',[])]
            # Only rewrite an explicit CLI port argument, never arbitrary numbers in source paths.
            command=p.get('command',[])
            for i in range(1,len(command)):
                if command[i-1] in ('--port','-p') and command[i]==str(previous):command[i]=str(port)
    if sources:
        p.setdefault('discovery',{})['fingerprint']=fingerprint(sources)
    return p


def synchronize(config, app_root, is_active=None, live_ports=None):
    start=time.monotonic();data=copy.deepcopy(config);existing=data.get('products',[])
    # An empty public seed must not silently expand into personal folders.
    scan_roots=data.get('scan_roots') or []
    node=data.get('node_path') or shutil.which('node') or '/usr/local/bin/node'
    warnings=[];candidates={};visited=0;unavailable=[]
    # Registered products and deployment aliases own their subtrees. Do not add their plugins,
    # examples, source checkouts or packaged copies as duplicate products.
    owned=[]
    for p in existing:
        owned.append(canonical(p['root']))
        owned.extend(canonical(x) for x in p.get('discovery',{}).get('aliases',[]))
    ignore_roots=[canonical(app_root)]+[canonical(x) for x in data.get('scan_ignore_roots',[])]
    max_depth=min(6,max(1,int(data.get('scan_depth',4))))
    for value in scan_roots:
        scan_root=Path(value).expanduser()
        if not scan_root.is_dir():
            unavailable.append(canonical(scan_root))
            warnings.append('扫描位置不可用，未据此删除清单：'+str(scan_root));continue
        def error(e):warnings.append('无法读取目录，已保留相关清单：'+str(e.filename))
        for base_path,dirs,files in os.walk(scan_root,onerror=error,followlinks=False):
            root=Path(base_path);visited+=1
            if visited>12000 or time.monotonic()-start>15:
                warnings.append('达到本次扫描上限，已有服务已保留；可缩小扫描范围后重试。');dirs[:]=[];break
            if any(inside(root,x) for x in ignore_roots):dirs[:]=[];continue
            owners=[x for x in owned if inside(root,x)]
            if owners:
                dirs[:]=[]
                # Auto-discovered services are reparsed; curated deployments use their owning adapters.
                old=next((p for p in existing if canonical(p['root'])==canonical(root)),None)
                if old and old.get('discovery',{}).get('auto'):
                    item=detect(root,node)
                    if item:candidates[canonical(root)]=item
                continue
            dirs[:]=[d for d in dirs if d not in IGNORED and not d.startswith('.')
                     and not d.endswith(('.app','.assets','_files'))]
            if len(root.relative_to(scan_root).parts)>=max_depth:dirs[:]=[]
            if not any(f in files for f in ('package.json','.launchpad.json','app.py','server.py','main.py','start_server.py',*COMPOSE)) and not any(f.endswith(('.command','.sh')) for f in files):continue
            item=detect(root,node)
            if item:
                if any(inside(owner,root) and canonical(owner)!=canonical(root) for owner in owned):
                    # Combined launch scripts around already registered products are shortcuts,
                    # not an additional service. Continue into the owned child directories.
                    continue
                candidates[canonical(root)]=item
                dirs[:]=[]
    # Existing auto services outside configured roots still update from their registered location.
    for p in existing:
        if p.get('discovery',{}).get('auto') and not absent(p['root']):
            item=detect(Path(p['root']),node)
            if item:candidates[canonical(p['root'])]=item
    added=[];updated=[];removed=[];kept=[];used=set()
    by_identity={}
    for path,item in candidates.items():by_identity.setdefault(item['discovery']['identity'],[]).append((path,item))
    for old in existing:
        id=old['id'];path=canonical(old['root']);meta=old.get('discovery',{})
        if meta.get('managed') is False:
            kept.append(old);used.add(path);continue
        active=bool(is_active and is_active(old))
        item=candidates.get(path)
        # A uniquely identified moved service keeps its stable card ID and user preferences.
        if item is None and absent(old['root']) and meta.get('identity'):
            possible=by_identity.get(meta['identity'],[])
            if len(possible)==1:item=possible[0][1];path=possible[0][0]
        if any(inside(old['root'],x) for x in unavailable):
            kept.append(old);used.add(path);continue
        if item and absent(old['root']) and not meta.get('auto'):
            moved=rewrite_paths(old,old['root'],item['root'])
            moved=update_curated(moved,live_ports(old) if live_ports else None)
            kept.append(moved);used.add(path)
            updated.append({'id':id,'name':moved['name'],'fields':['root','command','required']});continue
        marker_missing=meta.get('auto') and meta.get('source') and absent(meta['source']) and item is None
        if ((absent(old['root']) and item is None) or marker_missing) and not active:
            removed.append({'id':id,'name':old['name'],'reason':'部署目录或自动发现的启动入口已删除'});continue
        if absent(old['root']) and active:
            warnings.append(old['name']+' 的目录已移除，但服务仍在运行；卡片暂时保留。')
        if item and meta.get('auto'):
            item=copy.deepcopy(item);item['id']=id
            generated={k:copy.deepcopy(v) for k,v in item.items() if k!='discovery'}
            previous=meta.get('generated',{})
            # Respect fields the user edited directly since the last automatic generation.
            for key,value in old.items():
                if key in ('discovery','id'):continue
                if key in previous and value!=previous[key]:item[key]=copy.deepcopy(value)
            item['discovery']['generated']=generated
            used.add(path)
        else:
            item=update_curated(old,live_ports(old) if live_ports else None)
        fields=[key for key in set(old)|set(item) if key!='discovery' and old.get(key)!=item.get(key)]
        if fields:updated.append({'id':id,'name':item['name'],'fields':sorted(fields)})
        kept.append(item)
    for path,item in candidates.items():
        if path in used or any(canonical(p['root'])==path for p in kept):continue
        item=copy.deepcopy(item)
        item['discovery']['generated']={k:copy.deepcopy(v) for k,v in item.items() if k!='discovery'}
        kept.append(item);added.append({'id':item['id'],'name':item['name'],'root':item['root']})
    data['products']=kept
    report=dict(added=added,updated=updated,removed=removed,warnings=list(dict.fromkeys(warnings)),
                scanned_directories=visited,scan_roots=scan_roots,elapsed_ms=round((time.monotonic()-start)*1000),
                checked_at=time.time(),total=len(kept))
    return data,report
