import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


CORE = Path(__file__).resolve().parents[1] / 'Core'


class NativePipeTests(unittest.TestCase):
    def test_permission_failure_explains_how_to_restore_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root/'seed.json'
            seed.write_text(json.dumps(dict(products=[])))
            driver = (
                f'import sys;sys.path.insert(0,{str(CORE)!r});import engine,ipc\n'
                'def denied(self,*args,**kwargs): raise PermissionError("fixture")\n'
                'engine.Manager.scan=denied\nipc.main()\n'
            )
            result = subprocess.run(
                [sys.executable,'-I','-S','-B','-c',driver,'--data-dir',str(root/'data'),'--seed',str(seed)],
                input=''.join(json.dumps(dict(id=locale,method='products',language=locale))+'\n'
                              for locale in ('en','zh-Hans')),capture_output=True,text=True,timeout=8)
            replies = {reply['id']:reply for reply in map(json.loads,result.stdout.splitlines())}
            self.assertFalse(replies['en']['ok'])
            self.assertFalse(replies['zh-Hans']['ok'])
            self.assertIn('System Settings',replies['en']['error'])
            self.assertIn('文件夹访问权限',replies['zh-Hans']['error'])

    def test_switch_language_without_restarting_engine_or_editing_project_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = root/'projects'
            automatic = projects/'python-demo'
            explicit = projects/'manifest-demo'
            automatic.mkdir(parents=True)
            explicit.mkdir()
            (automatic/'server.py').write_text('from http.server import HTTPServer\nPORT=62991\nHTTPServer(("127.0.0.1",PORT),None)\n')
            (explicit/'.launchpad.json').write_text(json.dumps(dict(
                name='我的项目',description='Python 本地服务',note='我自己写的备注',
            )))
            seed = root/'seed.json'
            seed.write_text(json.dumps(dict(products=[],scan_roots=[str(projects),str(root/'missing')])))
            data = root/'data'
            with subprocess.Popen([sys.executable,'-I','-S','-B',str(CORE/'ipc.py'),
                                   '--data-dir',str(data),'--seed',str(seed)],
                                  stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as child:
                def request(method, locale=None, **params):
                    child.stdin.write(json.dumps(dict(id=method,method=method,language=locale,params=params))+'\n')
                    child.stdin.flush()
                    return json.loads(child.stdout.readline())

                try:
                    info = request('info')['result']
                    report = request('sync',mode='sync')['result']['report']
                    self.assertEqual(len(report['added']),2)
                    self.assertIn('Scan folder unavailable',report['warnings'][0])
                    stored = (data/'products.json').read_bytes()
                    en = {p['name']:p for p in request('products')['result']['products']}
                    zh = {p['name']:p for p in request('products','zh-Hans')['result']['products']}
                    fallback = {p['name']:p for p in request('products','unsupported')['result']['products']}
                    self.assertEqual(en['python-demo']['description'],'Local Python service')
                    self.assertEqual(zh['python-demo']['description'],'Python 本地服务')
                    self.assertEqual(en['python-demo']['label'],'Setup incomplete')
                    self.assertEqual(zh['python-demo']['label'],'部署待完善')
                    self.assertEqual(en['python-demo']['approval_fingerprint'],zh['python-demo']['approval_fingerprint'])
                    self.assertEqual(en['我的项目']['description'],'Python 本地服务')
                    self.assertEqual(en['我的项目']['reason'],'我自己写的备注')
                    self.assertEqual(fallback['python-demo']['label'],en['python-demo']['label'])
                    self.assertEqual(request('action','en',id='unknown',action='open')['error'],'Unknown project.')
                    self.assertEqual(request('action','zh-Hans',id='unknown',action='open')['error'],'未知产品')
                    self.assertEqual(request('info','zh-Hans')['result']['pid'],info['pid'])
                    self.assertEqual((data/'products.json').read_bytes(),stored)
                finally:
                    child.stdin.close()
                    child.wait(timeout=15)

    def test_quit_during_startup_and_reopen_without_starting_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root/'lifecycle_fixture.py'
            marker = root/'started.jsonl'
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0))
                port = probe.getsockname()[1]
            fixture.write_text(
                'import os\nfrom http.server import HTTPServer, BaseHTTPRequestHandler\n'
                f'with open({str(marker)!r}, "a") as f: f.write(str(os.getpid())+"\\n")\n'
                'class Handler(BaseHTTPRequestHandler):\n'
                ' def do_GET(self): self.send_response(200); self.end_headers()\n'
                ' def log_message(self,*args): pass\n'
                f'HTTPServer(("127.0.0.1",{port}),Handler).serve_forever()\n'
            )
            url = f'http://127.0.0.1:{port}/'
            product = dict(id='lifecycle',name='Lifecycle',description='fixture',category='test',
                           icon='cube',color='blue',kind='process',root=str(root),ports=[port],url=url,
                           command=[sys.executable,'-B',str(fixture)],match=[[str(fixture)]],required=[str(fixture)])
            seed = root/'seed.json'
            seed.write_text(json.dumps(dict(products=[product],scan_roots=[str(root)])))
            data = root/'data'
            resume = root/'resume-launch'
            driver = (
                f'import sys,time;from pathlib import Path;sys.path.insert(0,{str(CORE)!r});import engine,ipc\n'
                f'resume=Path({str(resume)!r})\n'
                'original=engine.Manager.worker\n'
                'def delayed(self,*args,**kwargs):\n'
                ' deadline=time.monotonic()+15\n'
                ' while not resume.exists() and time.monotonic()<deadline: time.sleep(.02)\n'
                ' return original(self,*args,**kwargs)\n'
                'engine.Manager.worker=delayed\nipc.main()\n'
            )
            def start_controller():
                return subprocess.Popen([sys.executable,'-I','-S','-B','-c',driver,
                                         '--data-dir',str(data),'--seed',str(seed)],
                                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            def request(child,method,**params):
                child.stdin.write(json.dumps(dict(id=method,method=method,params=params))+'\n')
                child.stdin.flush()
                response = json.loads(child.stdout.readline())
                self.assertTrue(response['ok'],response)
                return response['result']
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def ready():
                try:
                    with opener.open(url,timeout=.3) as response:
                        return response.status==200
                except (OSError,urllib.error.URLError):
                    return False
            first, second = start_controller(), None
            try:
                fingerprint=request(first,'products')['products'][0]['approval_fingerprint']
                self.assertTrue(request(first,'action',id='lifecycle',action='start',open=False,approval=fingerprint)['queued'])
                first.stdin.close()
                first.stdout.close()
                second = start_controller()
                self.assertEqual(request(second,'products')['products'][0]['status'],'starting')
                self.assertTrue(request(second,'action',id='lifecycle',action='start',open=False)['queued'])
                resume.touch()
                first.wait(timeout=20)
                self.assertEqual(first.returncode,0,first.stderr.read())
                self.assertTrue(ready(),'accepted startup was lost after app pipe closed')
                self.assertEqual(request(second,'products',refresh=True)['products'][0]['status'],'running')
                second.stdin.close()
                second.wait(timeout=15)
                self.assertTrue(ready(),'service stopped after both controllers exited')
                self.assertEqual(len(marker.read_text().splitlines()),1)
            finally:
                for child in (first,second):
                    if child is None: continue
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=5)
                    for stream in (child.stdin,child.stdout,child.stderr):
                        if stream and not stream.closed: stream.close()
                if marker.exists():
                    for pid in marker.read_text().splitlines():
                        command=subprocess.run(['/bin/ps','-p',pid,'-o','command='],capture_output=True,text=True)
                        if str(fixture) in command.stdout:
                            os.kill(int(pid),signal.SIGTERM)

    def test_migrate_config_and_operate_without_listener(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / 'seed.json'
            legacy = root / 'legacy.json'
            migration = root / 'migration.json'
            data = root / 'data'
            seed.write_text(json.dumps({'products': []}))
            legacy.write_text(json.dumps({'products': [], 'port': 61900, 'scan_roots': [str(root)]}))
            migration.write_text(json.dumps({'legacy_config': str(legacy)}))
            child = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(CORE / 'ipc.py'),
                                      '--data-dir', str(data), '--seed', str(seed), '--migration', str(migration)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                def request(method, **params):
                    child.stdin.write(json.dumps({'id': method, 'method': method, 'params': params})+'\n')
                    child.stdin.flush()
                    line = child.stdout.readline()
                    self.assertTrue(line, 'private pipe closed before replying')
                    return json.loads(line)

                info = request('info')['result']
                self.assertEqual(info['transport'], 'private-pipe')
                self.assertEqual(info['pid'], child.pid)
                self.assertFalse(request('shell', command='echo nope')['ok'])
                self.assertFalse(request('action', id='unknown', action='start')['ok'])
                inventory = request('products')['result']
                self.assertEqual(inventory['scan_roots'], [str(root)])
                self.assertEqual(inventory['products'], [])
                sync = request('sync', mode='sync')['result']
                self.assertTrue(sync['can_undo'])
                self.assertTrue(request('sync', mode='undo')['result']['undone'])
                self.assertNotIn('port', json.loads((data / 'products.json').read_text()))
                self.assertEqual(json.loads(legacy.read_text())['port'], 61900)
                sockets = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(child.pid), '-iTCP', '-sTCP:LISTEN'], capture_output=True, text=True)
                self.assertEqual(sockets.stdout, '')
            finally:
                child.stdin.close()
                child.wait(timeout=15)
                child.stdout.close()
                child.stderr.close()
            self.assertEqual(child.returncode, 0)


if __name__ == '__main__':
    unittest.main()
