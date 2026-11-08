#!/usr/bin/env python3
"""Local product engine, called exclusively over the native application private pipe."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from discovery import synchronize
from localization import engine_message, join, language, project_text, tr, use_language

ROOT = Path(__file__).resolve().parent
VERSION = '1.1'
FALLBACK_PORTS = range(61910, 61930)


def run(argv, cwd=None, timeout=10, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, errors='replace', timeout=timeout)


def docker_tool():
    return shutil.which('docker') or next((p for p in (
        '/opt/homebrew/bin/docker', '/usr/local/bin/docker',
        '/Applications/Docker.app/Contents/Resources/bin/docker') if Path(p).is_file()), 'docker')


def redact(text):
    replacement = r'\1'+tr('[已隐藏]')
    text = re.sub(r'(?i)([?&](?:token|key|secret|password|access_token)=)[^\s&"\']+', replacement, text)
    text = re.sub(r'(?i)(authorization[=: ]+(?:bearer )?)[^\s"\']+', replacement, text)
    text = re.sub(r'(?i)((?:api[_-]?key|secret|password|token)\s*[=:]\s*)[^\s,;]+', replacement, text)
    return text


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def http_check(url, auth=False):
    try:
        with HTTP.open(url, timeout=1.5) as response:
            code, cookie = response.status, response.headers.get('Set-Cookie')
    except urllib.error.HTTPError as response:
        code, cookie = response.code, response.headers.get('Set-Cookie')
        response.close()
    except (OSError, urllib.error.URLError, ValueError):
        return False
    if auth:
        return code in (302, 303, 307, 308) and bool(cookie)
    return 200 <= code < 500


def port_option(p):
    """Return a Vite argument index or an explicitly declared port environment key."""
    if (p['kind'] != 'process' or len(p.get('ports', [])) != 1 or not p.get('url')
            or 'reserved_ports' in p or any(p.get(key) for key in ('entry', 'open_app'))):
        return None
    command = p['command']
    if len(command) < 2:
        return None
    script = Path(command[1])
    if (script.parts[-4:] == ('node_modules', 'vite', 'bin', 'vite.js')
            and '--strictPort' in command and command.count('--port') == 1):
        index = command.index('--port') + 1
        if index < len(command) and command[index] == str(p['ports'][0]):
            return index
    key = p.get('port_strategy', {}).get('environment')
    if isinstance(key, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
        return key
    return None


def at_port(p, port):
    url = urllib.parse.urlsplit(p['url'])
    return p | dict(ports=[port], url=url._replace(netloc=f'{url.hostname}:{port}').geturl())


def port_available(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


class DisplayError(ValueError):
    """A rendered product diagnostic; do not translate its user-supplied text."""


class Manager:
    def __init__(self, config_path=ROOT / 'products.json', runtime=None):
        self.config_path = Path(config_path)
        self.runtime = Path(runtime or ROOT / '.runtime')
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.runtime.chmod(0o700)
        self.jobs = {}
        self.processes = {}
        self.startup_leases = {}
        self.external_jobs = set()
        self.gate = threading.RLock()
        self.cache = None
        self.cache_time = 0
        self.cache_language = None
        self.scan_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.started = time.time()
        self.load()

    @contextmanager
    def startup_lock(self):
        with (self.runtime / 'startups.lock').open('a+b') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def refresh_startups(self):
        """Caller holds the manager gate and cross-process startup lock."""
        for id in self.external_jobs:
            self.jobs.pop(id, None)
            if 'child' not in self.processes.get(id, {}):
                self.processes.pop(id, None)
        self.external_jobs.clear()
        directory = self.runtime / 'startups'
        for path in directory.glob('*.json'):
            id = path.stem
            if id not in self.products or id in self.startup_leases:
                continue
            with path.open('r+b') as file:
                active = False
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    active = True
                try:
                    job = json.load(file)
                except (ValueError, OSError):
                    continue
                if not isinstance(job, dict) or job.get('state') not in ('starting', 'done', 'failed', 'stopped'):
                    continue
                if job['state'] == 'starting' and not active:
                    job.update(state='failed', message='上次启动任务已结束，请查看实际服务状态或启动日志。')
                self.jobs[id] = job
                self.external_jobs.add(id)
                record = job.get('process')
                if (isinstance(record, dict) and isinstance(record.get('pid'), int)
                        and isinstance(record.get('fingerprint'), str) and isinstance(record.get('birth'), str)):
                    current = self.processes.get(id, {})
                    if all(current.get(key) == record[key] for key in ('pid', 'fingerprint', 'birth')):
                        record = current | record
                    self.processes[id] = record.copy()
                else:
                    self.processes.pop(id, None)

    def reserve_startup(self, id):
        directory = self.runtime / 'startups'
        directory.mkdir(mode=0o700, exist_ok=True)
        file = (directory / (id + '.json')).open('a+b')
        try:
            os.fchmod(file.fileno(), 0o600)
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.startup_leases[id] = file
            self.external_jobs.discard(id)
            self.processes.pop(id, None)
            self.write_startup(id)
        except BaseException:
            self.startup_leases.pop(id, None)
            file.close()
            raise

    def write_startup(self, id):
        file = self.startup_leases.get(id)
        if file is not None:
            self.write_startup_file(file, id)
        else:
            path = self.runtime / 'startups' / (id + '.json')
            if path.exists():
                with path.open('r+b') as file:
                    self.write_startup_file(file, id)

    def write_startup_file(self, file, id):
        file.seek(0)
        file.truncate()
        file.write(json.dumps(self.jobs[id], ensure_ascii=False).encode())
        file.flush()

    def startup_cancelled(self, id):
        """Caller holds both locks. A reopened controller may have stopped this startup."""
        file = self.startup_leases.get(id)
        if file is not None:
            file.seek(0)
            record = json.load(file)
            if record.get('state') == 'stopped':
                self.jobs[id] = record
        return self.jobs[id].get('state') == 'stopped'

    @contextmanager
    def sync_guard(self):
        if not self.sync_lock.acquire(blocking=False):
            raise ValueError('已有检测正在进行，请稍候')
        try:
            with (self.runtime / 'sync.lock').open('a+b') as lock:
                os.fchmod(lock.fileno(), 0o600)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('上一次检测仍在完成，请稍后再检测') from None
                yield
        finally:
            self.sync_lock.release()

    def load(self):
        data = json.loads(self.config_path.read_text())
        self.validate(data)
        with self.gate:
            self.config = data
            self.products = {p['id']: p for p in data['products']}
            self.cache_time = 0

    def approval(self, p):
        keys = ('root', 'kind', 'command', 'cwd', 'compose', 'app', 'plist', 'label',
                'probes', 'port_strategy', 'open_app', 'discovery')
        value = {k: p[k] for k in keys if k in p}
        # Generated discovery snapshots contain unrelated display fields. Only bind source identity.
        meta = p.get('discovery', {})
        value['discovery'] = {k: meta[k] for k in ('source', 'fingerprint') if k in meta}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        try:
            trusted = json.loads((self.runtime / 'approvals.json').read_text()).get(p['id']) == digest
        except (OSError, ValueError, AttributeError):
            trusted = False
        if p['kind'] == 'process':
            preview = shlex.join(p['command'])
        elif p['kind'] == 'docker':
            preview = shlex.join([docker_tool(), 'compose', '-f', p['compose'], 'up', '-d', '--no-build', '--pull', 'never'])
        elif p['kind'] == 'launchd':
            preview = 'launchctl bootstrap / kickstart: ' + p['plist']
        else:
            preview = shlex.join(['/usr/bin/open', p.get('app', p['root'])])
        return dict(needs_approval=not trusted, approval_fingerprint=digest, command_preview=redact(preview))

    def approve(self, p, fingerprint):
        current = self.approval(p)['approval_fingerprint']
        if fingerprint != current:
            raise ValueError('启动配置已变化，请重新查看并确认启动命令。')
        path = self.runtime / 'approvals.json'
        try:
            approvals = json.loads(path.read_text())
        except (OSError, ValueError):
            approvals = {}
        if not isinstance(approvals, dict):
            approvals = {}
        approvals[p['id']] = current
        fd, name = tempfile.mkstemp(dir=self.runtime, suffix='.pending')
        try:
            with os.fdopen(fd, 'w') as file:
                json.dump(approvals, file)
            Path(name).replace(path)
        finally:
            Path(name).unlink(missing_ok=True)

    def set_scan_roots(self, roots):
        if (not isinstance(roots, list) or len(roots) > 16
                or not all(isinstance(x, str) and Path(x).is_absolute() and Path(x).is_dir() for x in roots)):
            raise ValueError('请选择可访问的本机文件夹，最多 16 个。')
        with self.sync_guard():
            data = json.loads(self.config_path.read_text())
            data['scan_roots'] = list(dict.fromkeys(str(Path(x).resolve()) for x in roots))
            self.validate(data)
            self.write_config(data)
            self.load()
        return dict(message=tr('已保存扫描位置；点击检测同步发现产品。'))

    def validate(self, data):
        if not isinstance(data.get('products'), list):
            raise ValueError('products 必须为数组')
        ids = [p.get('id') for p in data['products']]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not re.fullmatch(r'[a-z0-9-]+', i) for i in ids):
            raise ValueError('产品 id 必须唯一，且仅含小写字母、数字和短横线')
        for p in data['products']:
            if not isinstance(p,dict) or any(not isinstance(p.get(key),str) for key in ('name','description','category','icon','color','root','kind')):
                raise ValueError('产品基本字段不完整')
            kind=p['kind']
            if kind not in ('process','launchd','app','docker','incomplete'):raise ValueError('不支持的启动方式')
            if kind=='process' and (not isinstance(p.get('command'),list) or not p['command'] or not all(isinstance(s,str) for s in p['command'])):
                raise ValueError('启动命令必须是非空字符串数组')
            if kind=='launchd' and (not isinstance(p.get('label'),str) or not isinstance(p.get('plist'),str)):
                raise ValueError('缺少系统后台任务信息')
            if kind=='docker' and not isinstance(p.get('compose'),str):raise ValueError('缺少 Compose 入口')
            if kind=='app' and not isinstance(p.get('app'),str):raise ValueError('缺少应用入口')
            if not isinstance(p.get('required',[]),list) or not all(isinstance(s,str) for s in p.get('required',[])):
                raise ValueError('依赖清单必须是路径数组')
            if not isinstance(p.get('match',[]),list) or not all(isinstance(group,list) and all(isinstance(s,str) for s in group) for group in p.get('match',[])):
                raise ValueError('进程归属规则格式无效')
            for port in p.get('ports', []) + p.get('reserved_ports', []):
                if not isinstance(port, int) or not 1 <= port <= 65535:
                    raise ValueError('无效端口')
            if p.get('url'):
                self.validate_url(p['url'], p)
            strategy = p.get('port_strategy', {})
            if (not isinstance(strategy, dict) or (strategy and
                    (set(strategy) != {'environment'} or not isinstance(strategy['environment'], str)
                     or not re.fullmatch(r'[A-Z][A-Z0-9_]*', strategy['environment'])))):
                raise ValueError('端口策略须声明有效的环境变量名')
            probes = p.get('probes', [])
            if (not isinstance(probes, list) or not all(isinstance(x, dict)
                    and isinstance(x.get('label'), str) and isinstance(x.get('command'), list)
                    and x['command'] and all(isinstance(v, str) for v in x['command']) for x in probes)):
                raise ValueError('依赖检查命令格式无效')

    def sync(self, undo=False):
        with self.sync_guard():
            with self.gate, self.startup_lock():
                self.refresh_startups()
            before=self.config_path.read_bytes()
            digest=hashlib.sha256(before).hexdigest()
            history=self.runtime/'last-sync.json'
            if undo:
                if not history.exists():raise ValueError('没有可撤销的同步')
                last=json.loads(history.read_text())
                if digest!=last['after_hash']:raise ValueError('清单在同步后已发生其他修改，未自动覆盖；可从备份目录恢复。')
                backup=Path(last['backup'])
                if backup.parent!=self.runtime/'backups':raise ValueError('备份位置无效')
                restored=json.loads(backup.read_text());self.validate(restored)
                self.write_config(restored)
                self.load();history.unlink(missing_ok=True)
                return dict(ok=True,undone=True,message=tr('已恢复同步前的服务清单；产品文件和运行进程未改动。'))
            initial=json.loads(before)
            snap=self.snapshot()
            def active(p):
                return (any(self.matches(p,pid,snap) for pid in snap['commands'])
                        or p['kind']=='docker' and self.docker_identity(p,snap)
                        or self.jobs.get(p['id'],{}).get('state')=='starting')
            def live_ports(p):
                if port_option(p) is not None:
                    return []
                return [port for port,pids in snap['listeners'].items()
                        if any(self.matches(p,pid,snap) for pid in pids)
                        and http_check('http://127.0.0.1:%d/'%port)]
            updated,report=synchronize(initial,ROOT,is_active=active,live_ports=live_ports)
            # Reject ambiguous/invalid discovery records individually, keeping other valid results.
            valid=[]
            old_by_id={p['id']:p for p in initial['products']}
            for p in updated['products']:
                try:self.validate(dict(products=[p]));valid.append(p)
                except (ValueError,TypeError,KeyError):
                    report['warnings'].append(tr('{name} 的新配置无法安全识别，已跳过自动更新。',name=p.get('name',tr('未知服务'))))
                    if p.get('id') in old_by_id:valid.append(old_by_id[p['id']])
            updated['products']=valid;self.validate(updated)
            valid_ids={p['id'] for p in valid}
            report['added']=[p for p in report['added'] if p['id'] in valid_ids]
            report['total']=len(valid)
            if self.config_path.read_bytes()!=before:raise ValueError('检测期间清单被其他操作修改，本次未覆盖；请再检测一次。')
            backup_dir=self.runtime/'backups';backup_dir.mkdir(mode=0o700,exist_ok=True)
            backup=backup_dir/('products-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.json')
            backup.write_bytes(before);backup.chmod(0o600)
            self.write_config(updated)
            after_hash=hashlib.sha256(self.config_path.read_bytes()).hexdigest()
            saved=dict(report=report,backup=str(backup),after_hash=after_hash)
            history.write_text(json.dumps(saved,ensure_ascii=False));history.chmod(0o600)
            for old in sorted(backup_dir.glob('products-*.json'))[:-10]:old.unlink()
            self.load()
            return dict(ok=True,report=report,can_undo=True)

    def write_config(self, data):
        fd, name = tempfile.mkstemp(prefix=self.config_path.name+'.', suffix='.pending', dir=self.config_path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w') as file:
                file.write(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.config_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def validate_url(url, p):
        u = urllib.parse.urlsplit(url)
        if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost')
                or u.port not in p.get('ports', []) or u.username or u.password):
            raise ValueError('打开地址必须是该产品登记的本机端口')
        return url

    def snapshot(self):
        commands, parents, listeners, cwds = {}, {}, {}, {}
        result = run(['/bin/ps', '-axo', 'pid=,ppid=,command='])
        if result.returncode:
            raise RuntimeError('无法读取本机进程，不能可靠判断服务状态')
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                commands[int(parts[0])] = parts[2]
                parents[int(parts[0])] = int(parts[1])
        result = run(['/usr/sbin/lsof', '-nP', '-iTCP', '-sTCP:LISTEN', '-Fpn'], timeout=10)
        pid = None
        for line in result.stdout.splitlines():
            if line.startswith('p') and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith('n') and pid:
                match = re.search(r':(\d+)$', line)
                if match:
                    listeners.setdefault(int(match[1]), set()).add(pid)
        # Working-directory checks disambiguate apps using generic next-server/node commands.
        cwd_pids = set()
        for p in self.products.values():
            if p.get('cwd_match'):
                for pids in listeners.values():
                    cwd_pids.update(pid for pid in pids if any(all(part in commands.get(pid,'') for part in group) for group in p.get('match',[])))
        if cwd_pids:
            result = run(['/usr/sbin/lsof', '-a', '-p', ','.join(map(str, cwd_pids)), '-d', 'cwd', '-Fpn'])
            for line in result.stdout.splitlines():
                if line.startswith('p') and line[1:].isdigit():
                    pid = int(line[1:])
                elif line.startswith('n'):
                    cwds[pid] = line[1:]
        docker = False
        if any(p['kind'] == 'docker' for p in self.products.values()):
            try:
                docker = run([docker_tool(), 'info', '--format', '{{.ServerVersion}}'], timeout=2).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        agents = {}
        for p in self.products.values():
            if p['kind'] != 'launchd':
                continue
            result=run(['/bin/launchctl','print','gui/%s/%s'%(os.getuid(),p['label'])],timeout=3)
            if not result.returncode:
                code=re.search(r'last exit code = (\d+)',result.stdout)
                agents[p['id']]={'spawn_failed':'job state = spawn failed' in result.stdout,
                                 'exit_code':int(code.group(1)) if code else None}
        return dict(commands=commands, parents=parents, listeners=listeners, cwds=cwds, docker=docker, agents=agents)

    def matches(self, p, pid, snap):
        command = snap['commands'].get(pid, '')
        alternatives = p.get('match', [])
        ours = any(all(part in command for part in group) for group in alternatives)
        if p.get('cwd_match'):
            ours = ours and snap['cwds'].get(pid) == p['cwd_match']
        return ours

    def docker_identity(self, p, snap):
        if not snap['docker']:
            return False
        try:
            result = run([docker_tool(), 'compose', '-f', p['compose'], 'ps', '--format', 'json'], cwd=p['root'], timeout=5)
            if result.returncode:
                return False
            text = result.stdout.strip()
            entries = json.loads(text) if text.startswith('[') else [json.loads(line) for line in text.splitlines() if line]
            if isinstance(entries, dict):
                entries = [entries]
            publishers = {int(x.get('PublishedPort', 0)) for item in entries for x in (item.get('Publishers') or []) if item.get('State') == 'running'}
            return all(port in publishers for port in p.get('ports', []))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False

    def inspect(self, p, snap, include_job=True):
        with self.gate:
            job = dict(self.jobs.get(p['id'], {}))
        if 'message' in job:
            job['message'] = engine_message(job['message'])
        note = project_text(p, 'note')
        configured_ports = p.get('reserved_ports', p.get('ports', []))
        option = port_option(p) if include_job else None
        preferred = p['ports'][0] if option is not None else None
        if preferred is not None:
            planned = job.get('ports', []) if job.get('state') == 'starting' else []
            if planned:
                p = at_port(p, planned[0])
            else:
                for port in [preferred, *FALLBACK_PORTS]:
                    if any(self.matches(p, pid, snap) for pid in snap['listeners'].get(port, [])):
                        p = at_port(p, port)
                        break
        missing = [path for path in p.get('required', []) if not Path(path).exists()]
        probe_checks=[]
        # Project commands are only executed during a reviewed startup, never by polling.
        probe_failed=any(not check['ok'] for check in probe_checks)
        ports = p.get('ports', [])
        pids = sorted(pid for pid in snap['commands'] if self.matches(p, pid, snap))
        owned_ports = {port for port in ports if any(self.matches(p, pid, snap) for pid in snap['listeners'].get(port, []))}
        docker_ours = p['kind'] == 'docker' and self.docker_identity(p, snap)
        agent=snap.get('agents',{}).get(p['id'],{})
        alive = (bool(pids) and (not ports or len(owned_ports) == len(ports))) or docker_ours
        conflict_ports = []
        if not docker_ours:
            for port in p.get('reserved_ports', ports):
                if snap['listeners'].get(port) and not any(self.matches(p, pid, snap) for pid in snap['listeners'][port]):
                    conflict_ports.append(port)
        healthy = False
        if alive:
            healthy = not p.get('url') or http_check(p['url'])
            status = 'running' if healthy else 'degraded'
            label = ('应用已打开' if p['kind'] == 'app' and not ports else '运行中') if healthy else '进程在运行，页面未就绪'
            reason = tr('进程归属与本机访问检查通过' if ports and healthy else ('已检测到应用进程' if p['kind'] == 'app' else '已检测到网关进程'))
            if not healthy:
                reason = tr('已确认产品进程，但 HTTP 检查暂未通过；请稍后刷新或查看日志。')
        elif conflict_ports:
            status, label = 'conflict', '端口被占用'
            reason = tr('端口 {ports} 正由其他服务使用。', ports=join(map(str, conflict_ports)))
            if option is not None and not pids and not missing and not probe_failed:
                status, label = 'ready', '可换端口唤醒'
                reason += tr('唤醒时会自动使用空闲端口。')
        elif pids and p['kind'] == 'process':
            status, label = 'degraded', '进程在运行，端口未就绪'
            reason = tr('已检测到该产品进程，正在等待登记端口就绪；可刷新状态或查看启动日志。')
        elif missing or probe_failed or p['kind'] == 'incomplete':
            status, label = 'incomplete', '部署待完善'
            reason = (tr('未通过依赖检查：{checks}', checks=join(c['label'] for c in probe_checks if not c['ok']))
                      if probe_failed else note or tr('缺少启动所需的文件或依赖。'))
        elif agent.get('spawn_failed'):
            status,label='failed','系统启动任务异常'
            reason=tr('现有系统后台任务未能启动（退出码 {code}）；请检查原任务的日志目录权限和启动配置。',
                      code=agent.get('exit_code',tr('未知')))
        else:
            status, label = 'ready', '可唤醒'
            reason = tr('启动入口与本地依赖文件已存在；启动后检查实际就绪状态。')
            if p['kind'] == 'docker' and not snap['docker']:
                status, label = 'blocked', 'Docker 未启动'
                reason = tr('可先唤醒 Docker，再检查已有镜像并启动；尚未验证容器部署是否完整。')
        if include_job and job.get('state') == 'starting':
            status, label, reason = 'starting', '正在唤醒', job.get('message') or tr('正在等待服务就绪…')
        elif include_job and job.get('state') == 'failed' and not alive:
            status, label, reason = 'failed', '启动未完成', job.get('message') or tr('请查看启动日志')
        checks = [{'label':Path(path).name,'path':path,'ok':Path(path).exists()} for path in p.get('required', [])]+probe_checks
        port_note = None
        shared = {port: [other['name'] for other in self.products.values()
                         if other['id'] != p['id'] and port in other.get('reserved_ports', other.get('ports', []))]
                  for port in configured_ports}
        overlaps = [f'{port} ({join(names)})' for port, names in shared.items() if names]
        if preferred is not None and ports != [preferred]:
            port_note = tr('当前使用 {active}，默认端口为 {preferred}。打开按钮会跟随当前地址。', active=ports[0], preferred=preferred)
        elif overlaps:
            port_note = tr('共用配置端口 {ports}。', ports=join(overlaps))
            if option is not None:
                port_note += tr('唤醒时自动避让占用及固定配置。')
        return {k:p[k] for k in ('id','name','icon','color','root','kind')} | dict(
            description=project_text(p, 'description'), category=project_text(p, 'category'),
            status=status, label=tr(label), reason=reason, ports=ports, url=p.get('url'), pids=pids,
            deployed=not missing and not probe_failed and p['kind'] != 'incomplete', checks=checks, note=note, port_note=port_note,
            can_start=status in ('ready','blocked','failed') and not pids and (not conflict_ports or option is not None),
            can_open=alive and healthy,
            can_stop=self.can_stop(p, snap), job=job, conflict_ports=conflict_ports,
            docker_ready=snap['docker'] if p['kind']=='docker' else None) | self.approval(p)

    def can_stop(self, p, snap):
        record = self.processes.get(p['id'])
        if not record:
            return False
        return bool(record['pid'] in snap['commands'] and self.matches(p, record['pid'], snap)
                    and self.fingerprint(snap['commands'][record['pid']]) == record['fingerprint']
                    and record.get('birth') and self.process_birth(record['pid']) == record['birth'])

    @staticmethod
    def process_birth(pid):
        try:
            result = run(['/bin/ps', '-p', str(pid), '-o', 'lstart='], timeout=3)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def fingerprint(command):
        return hashlib.sha256(command.encode()).hexdigest()

    def scan(self, force=False):
        with self.scan_lock:
            if not force and self.cache is not None and self.cache_language == language() and time.monotonic()-self.cache_time < 3:
                return self.cache
            with self.gate, self.startup_lock():
                self.refresh_startups()
            snap = self.snapshot()
            products = list(self.products.values())
            items = [self.inspect(p, snap) for p in products]
            previewed, configured, occupied = set(), {}, {}
            with self.gate:
                for p, item in zip(products, items):
                    for port in set(p.get('reserved_ports', p.get('ports', []))):
                        configured.setdefault(port, []).append(p['name'])
                    for port in item['conflict_ports']:
                        occupied.setdefault(port, []).append(p['name'])
                    option = port_option(p)
                    if option is None or not item['can_start'] or item['pids'] or not item['deployed']:
                        continue
                    try:
                        plan = self.plan_start(p, snap, option, additional_reserved=previewed)
                    except ValueError as error:
                        item['port_note'] = tr(str(error))
                        continue
                    port = plan['ports'][0]
                    previewed.add(port)
                    if port != p['ports'][0]:
                        item['next_port'] = port
                        item['port_note'] = tr('下次唤醒预计使用 {port}，启动前会再次确认端口是否空闲。', port=port)
            issues = [dict(port=port, products=configured.get(port, []), blocked=occupied.get(port, []))
                      for port in sorted(configured.keys() | occupied.keys())
                      if len(configured.get(port, [])) > 1 or port in occupied]
            result = dict(products=items, checked_at=time.time(), version=VERSION,
                          port_issues=issues, uptime=int(time.time()-self.started), host=socket.gethostname().split('.')[0],
                          config=str(self.config_path), interval=8, scan_roots=self.config.get('scan_roots',[]))
            self.cache, self.cache_time, self.cache_language = result, time.monotonic(), language()
            return result

    def entry_url(self, p):
        entry = p.get('entry')
        if not entry:
            return self.validate_url(p['url'], p)
        path = Path(entry['file'])
        if not path.exists():
            raise RuntimeError('服务已运行，登录入口尚未生成；请稍后重试打开。')
        if entry['kind'] == 'json':
            url = json.loads(path.read_text())[entry['key']]
        elif entry['kind'] == 'lines':
            url = path.read_text().splitlines()[entry.get('index', 0)].strip()
        else:
            # Only inspect the tail; never expose private service logs through the API.
            with path.open('rb') as f:
                f.seek(max(0, path.stat().st_size-262144))
                text = f.read().decode('utf-8', 'replace')
            base = re.escape(p['url'].rstrip('/') + '/')
            candidates = re.findall(base+r'\?token=[A-Za-z0-9_\-]+', text)
            if not candidates:
                raise RuntimeError('服务已运行，未找到当前登录入口；请查看原产品启动日志。')
            url = candidates[-1]
        self.validate_url(url, p)
        if not http_check(url, auth=True):
            raise RuntimeError('服务已运行，但登录入口尚未就绪或已过期；请稍后重试。')
        return url

    def open_product(self, p):
        app = p.get('open_app') or (p.get('app') if p['kind']=='app' else None)
        argv = ['/usr/bin/open', app] if app else ['/usr/bin/open', self.entry_url(p)]
        if run(argv).returncode:
            raise RuntimeError('服务已就绪，但系统未能打开入口。')

    def launchd(self, p, log):
        target = 'gui/%s/%s' % (os.getuid(), p['label'])
        if run(['/bin/launchctl', 'print', target]).returncode:
            result = run(['/bin/launchctl','bootstrap','gui/%s'%os.getuid(),p['plist']])
            if result.returncode:
                log.write(redact(result.stderr).encode())
                raise RuntimeError('系统后台任务尚未注册，加载失败；请查看启动日志。')
        # No -k: an already running product must never be restarted by a wake click.
        result = run(['/bin/launchctl','kickstart',target])
        if result.returncode:
            log.write(redact(result.stderr).encode())
            raise RuntimeError('系统未能唤醒后台任务；可查看原产品的 LaunchAgent。')

    def launch_docker(self, p, log):
        self.message(p['id'], '正在唤醒 Docker 并检查已有镜像…')
        if run([docker_tool(),'info','--format','{{.ServerVersion}}'],timeout=3).returncode:
            run(['/usr/bin/open','/Applications/Docker.app'])
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            try:
                if run([docker_tool(),'info','--format','{{.ServerVersion}}'],timeout=3).returncode==0:
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Docker 尚未就绪；请完成 Docker 应用内的首次配置后重试。')
        # Do not build, update images, or pull remote content when simply waking a deployment.
        result=run([docker_tool(),'compose','-f',p['compose'],'up','-d','--no-build','--pull','never'],cwd=p['root'],timeout=120)
        log.write(redact(result.stdout+'\n'+result.stderr).encode())
        if result.returncode:
            raise RuntimeError('容器启动未完成；可能缺少已有镜像或存在端口冲突。请查看启动日志。')

    def message(self, id, text):
        with self.gate, self.startup_lock():
            if not self.startup_cancelled(id):
                self.jobs[id]['message']=text
                self.write_startup(id)
            self.cache_time=0

    def worker(self, p, auto_open, env_port=False, locale='en'):
        id=p['id']
        try:
            logfile=self.runtime/(id+'.log')
            if logfile.exists() and logfile.stat().st_size>4*1024*1024:
                logfile.replace(logfile.with_suffix('.previous.log'))
            with logfile.open('ab',buffering=0) as log:
                logfile.chmod(0o600)
                with use_language(locale):
                    log.write(('\n[%s] %s\n'%(time.strftime('%Y-%m-%d %H:%M:%S'),tr('启动 {name}',name=p['name']))).encode())
                for probe in p.get('probes', []):
                    if run(probe['command'], cwd=p['root'], timeout=5).returncode:
                        raise RuntimeError('未通过依赖检查：' + probe['label'])
                if p['kind']=='launchd':
                    self.launchd(p,log)
                elif p['kind']=='docker':
                    self.launch_docker(p,log)
                elif p['kind']=='app':
                    if run(['/usr/bin/open',p['app']]).returncode:
                        raise RuntimeError('系统未能打开已登记的应用。')
                else:
                    env=os.environ.copy()
                    env['PATH']=str(Path.home()/'.local/bin')+':/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
                    if isinstance(env_port, str):
                        env[env_port] = str(p['ports'][0])
                    child=subprocess.Popen(p['command'],cwd=p.get('cwd',p['root']),env=env,
                                           stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                    threading.Thread(target=child.wait,daemon=True).start()
                self.message(id,'启动请求已发送，正在检查进程归属与服务响应…')
                wait_started=time.monotonic()
                deadline=wait_started+120
                while time.monotonic()<deadline:
                    with self.gate, self.startup_lock():
                        if self.startup_cancelled(id):
                            return
                    snap=self.snapshot()
                    if (p['kind']=='process' and id not in self.processes and child.poll() is None
                            and self.matches(p,child.pid,snap)):
                        command=snap['commands'][child.pid]
                        birth = self.process_birth(child.pid)
                        if birth:
                            record = dict(pid=child.pid, fingerprint=self.fingerprint(command), birth=birth)
                            with self.gate, self.startup_lock():
                                if self.startup_cancelled(id):
                                    return
                                self.processes[id] = record | dict(child=child)
                                self.jobs[id]['process'] = record
                                self.write_startup(id)
                    item=self.inspect(p,snap,include_job=False)
                    if item['can_open'] and item['status']!='degraded':
                        break
                    if item['conflict_ports']:
                        raise RuntimeError(item['reason'])
                    if p['kind']=='launchd' and time.monotonic()-wait_started>3 and snap.get('agents',{}).get(id,{}).get('spawn_failed'):
                        raise RuntimeError(item['reason'])
                    if p['kind']=='process' and child.poll() is not None and child.returncode!=0:
                        raise RuntimeError('启动进程已退出；请查看该产品的启动日志。')
                    time.sleep(1)
                else:
                    raise RuntimeError('等待服务就绪超时；后台可能仍在启动，请刷新检查。')
                if auto_open:
                    with self.gate, self.startup_lock():
                        if self.startup_cancelled(id):
                            return
                    self.message(id,'服务已就绪，正在打开产品…')
                    # Authenticated entry files may be written just after the listener becomes ready.
                    open_deadline=time.monotonic()+8
                    while True:
                        try:
                            self.open_product(p)
                            break
                        except RuntimeError:
                            if time.monotonic()>open_deadline:
                                raise
                            time.sleep(.5)
            with self.gate, self.startup_lock():
                if not self.startup_cancelled(id):
                    self.jobs[id].update(state='done',message='服务已就绪'+('，已打开产品' if auto_open else ''),ended=time.time())
        except Exception as error:
            # Never send subprocess argv, private URLs or raw stack traces to the browser.
            msg=str(error) if isinstance(error,RuntimeError) else '操作未完成；请检查产品依赖与本机权限。'
            with self.gate, self.startup_lock():
                if not self.startup_cancelled(id):
                    self.jobs[id].update(state='failed',message=redact(msg),ended=time.time())
        finally:
            with self.gate, self.startup_lock():
                try:
                    self.write_startup(id)
                finally:
                    lease = self.startup_leases.pop(id, None)
                    if lease is not None:
                        lease.close()
                    self.cache_time=0

    def plan_start(self, p, snap, option, additional_reserved=(), suggested=None):
        requested = p.get('reserved_ports', p.get('ports', []))
        reserved = set(additional_reserved)
        for other_id, job in self.jobs.items():
            if other_id != p['id'] and job['state'] in ('starting', 'checking'):
                other = self.products.get(other_id, {})
                reserved.update(job.get('ports', other.get('reserved_ports', other.get('ports', []))))
        if option is None:
            if reserved.intersection(requested):
                raise ValueError('另一个产品正在使用同一端口启动，请等待后再试')
            return p
        preferred = requested[0]
        others = [other for other in self.products.values() if other['id'] != p['id']]
        fixed = any(preferred in other.get('reserved_ports', other.get('ports', []))
                    and port_option(other) is None for other in others)
        occupied = reserved | snap['listeners'].keys()
        if not fixed and preferred not in occupied and port_available(preferred):
            return p
        registered = {port for other in others for port in other.get('reserved_ports', other.get('ports', []))}
        candidates = list(FALLBACK_PORTS)
        if suggested in FALLBACK_PORTS:
            candidates.remove(suggested)
            candidates.insert(0, suggested)
        for port in candidates:
            if port not in occupied and port not in registered and port_available(port):
                routed = at_port(p, port)
                if isinstance(option, int):
                    command = p['command'].copy()
                    command[option] = str(port)
                    routed['command'] = command
                return routed
        raise ValueError('没有可用的备用端口，请释放端口后重试。')

    def action(self, id, action, auto_open=True, approval=None):
        if id=='settings' and action=='config':
            run(['/usr/bin/open','-a','TextEdit',str(self.config_path)])
            return dict(ok=True,message=tr('已打开本地产品清单；保存后点击重新检测。'))
        if id not in self.products:
            raise ValueError('未知产品')
        p=self.products[id]
        if action=='reveal':
            run(['/usr/bin/open','-R',p['root']])
            return dict(ok=True,message=tr('已在 Finder 显示产品位置'))
        if action=='log':
            path=self.runtime/(id+'.log')
            if not path.exists():
                raise ValueError('尚无本工作台产生的启动日志')
            run(['/usr/bin/open','-a','TextEdit',str(path)])
            return dict(ok=True,message=tr('已打开本机日志'))
        if action not in ('start','open','stop'):
            raise ValueError('不支持的操作')
        # Serialize preflight + reservation for all starts, including products sharing a port.
        with self.gate, self.startup_lock():
            self.refresh_startups()
            snap=self.snapshot()
            item=self.inspect(p,snap)
            option=port_option(p)
            if action=='stop':
                if not self.can_stop(p,snap):
                    raise ValueError('仅能停止由唤醒启动、且进程身份核验通过的服务')
                record=self.processes[id]
                os.kill(record['pid'],signal.SIGTERM)
                self.processes.pop(id,None)
                self.jobs.setdefault(id, {}).update(state='stopped', message='已停止服务', ended=time.time())
                self.jobs[id].pop('process', None)
                self.write_startup(id)
                self.cache_time=0
                return dict(ok=True,message=tr('已发送停止请求；将继续检测实际状态'))
            if item['status']=='starting':
                return dict(ok=True,queued=True,message=tr('该产品正在唤醒，无需重复点击'))
            if item['can_open']:
                if action=='open' or auto_open:
                    if self.approval(p)['needs_approval']:
                        if approval is None:
                            raise ValueError('首次打开此产品，请先在详情中审查并确认入口。')
                        self.approve(p, approval)
                    self.open_product(at_port(p,item['ports'][0]) if option is not None else p)
                return dict(ok=True,message=tr('已打开产品' if action=='open' or auto_open else '服务已在运行'))
            if action=='open':
                raise ValueError('服务尚未就绪，请先唤醒')
            if not item['can_start'] or not item['deployed']:
                raise DisplayError(item['reason'])
            if option is not None and item['pids']:
                raise ValueError('已检测到该产品的进程，请先检查现有实例是否就绪。')
            suggested=next((item.get('next_port') for item in (self.cache or {}).get('products',[])
                            if item['id']==id),None)
            planned=self.plan_start(p,snap,option,suggested=suggested)
            if self.approval(p)['needs_approval']:
                if approval is None:
                    raise ValueError('首次启动或启动配置变化，请先在详情中审查并确认命令。')
                self.approve(p, approval)
            switched=planned.get('ports') != p.get('ports')
            message=f"已选择空闲端口 {planned['ports'][0]}，正在唤醒…" if switched else '正在准备本地启动环境…'
            self.jobs[id]=dict(state='starting',message=message,started=time.time(),
                               ports=planned.get('reserved_ports',planned.get('ports',[])))
            self.reserve_startup(id)
            self.cache_time=0
            try:
                threading.Thread(target=self.worker,args=(planned,auto_open,option if isinstance(option,str) else None),
                                 kwargs={'locale':language()},daemon=False).start()
            except BaseException:
                self.jobs[id].update(state='failed',message='无法开始本次启动，请重试。')
                self.write_startup(id)
                self.startup_leases.pop(id).close()
                raise
            return dict(ok=True,queued=True,message=engine_message(message) if switched else
                        tr('正在唤醒，就绪后自动打开' if auto_open else '正在唤醒，就绪后更新状态'))
