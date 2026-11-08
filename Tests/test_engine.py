"""Behavior tests: state ownership, fixed actions and real wake/stop."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'Core'
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('launcher',ROOT/'engine.py')
launcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def product(root,**overrides):
    p=dict(id='fixture',name='Fixture',description='test',category='test',icon='cube',color='blue',
           root=str(root),kind='process',ports=[61903],url='http://127.0.0.1:61903/',
           match=[['fixture.py']],required=[str(root)],command=['/usr/bin/python3',str(root/'fixture.py')])
    return dict(p,**overrides)


def snap(commands=None,listeners=None,cwds=None):
    return dict(commands=commands or {},listeners=listeners or {},parents={},cwds=cwds or {},docker=False)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.p=product(self.root)
        self.config=self.root/'products.json'
        self.config.write_text(json.dumps(dict(products=[self.p])))
        self.manager=launcher.Manager(self.config,self.root/'runtime')
        self.allow()

    def allow(self):
        self.manager.approve(self.p,self.manager.approval(self.p)['approval_fingerprint'])

    def tearDown(self):
        for lease in self.manager.startup_leases.values():
            lease.close()
        self.temp.cleanup()

    def test_wrong_process_is_port_conflict(self):
        item=self.manager.inspect(self.p,snap({123:'node unrelated.js'},{61903:{123}}))
        self.assertEqual(item['status'],'conflict')
        self.assertFalse(item['can_open'])
        self.assertFalse(item['can_start'])

    def test_owned_listener_and_http_required(self):
        state=snap({123:'python fixture.py'},{61903:{123}})
        with patch.object(launcher,'http_check',return_value=True):
            self.assertEqual(self.manager.inspect(self.p,state)['status'],'running')
        with patch.object(launcher,'http_check',return_value=False):
            item = self.manager.inspect(self.p,state)
            self.assertEqual(item['status'],'degraded')
            self.assertFalse(item['can_open'])
            with patch.object(self.manager,'snapshot',return_value=state):
                with self.assertRaises(ValueError):
                    self.manager.action('fixture','start',False)

    def test_existing_process_without_ready_port_never_starts_twice(self):
        state = snap({123:'python fixture.py'})
        item = self.manager.inspect(self.p,state)
        self.assertEqual(item['status'],'degraded')
        self.assertFalse(item['can_start'])
        with patch.object(self.manager,'snapshot',return_value=state),patch.object(threading.Thread,'start') as start:
            with self.assertRaises(ValueError):
                self.manager.action('fixture','start',False)
            start.assert_not_called()

    def test_declared_environment_port_needs_no_source_file_access(self):
        self.p.update(command=['node',str(self.root/'server.js')],port_strategy={'environment':'PORT'})
        with patch.object(Path,'open',side_effect=AssertionError('polling opened a source file')):
            self.assertEqual(launcher.port_option(self.p),'PORT')

    def test_sync_is_serialized_between_controllers(self):
        second = launcher.Manager(self.config,self.root/'runtime')
        with self.manager.sync_guard():
            with self.assertRaisesRegex(ValueError,'检测仍在完成'):
                second.sync()

    def test_restored_process_identity_rejects_pid_reuse(self):
        directory = self.root/'runtime/startups'
        directory.mkdir()
        record = dict(pid=123,fingerprint=self.manager.fingerprint('python fixture.py'),birth='old birth')
        (directory/'fixture.json').write_text(json.dumps(dict(state='done',process=record)))
        second = launcher.Manager(self.config,self.root/'runtime')
        state = snap({123:'python fixture.py'},{61903:{123}})
        with patch.object(second,'snapshot',return_value=state), \
             patch.object(launcher,'http_check',return_value=True), \
             patch.object(second,'process_birth',return_value='different birth'),patch.object(os,'kill') as kill:
            self.assertFalse(second.scan(True)['products'][0]['can_stop'])
            with self.assertRaises(ValueError):
                second.action('fixture','stop')
            kill.assert_not_called()

    def test_missing_dependency_is_incomplete(self):
        self.p['required']=[str(self.root/'missing')]
        self.assertEqual(self.manager.inspect(self.p,snap())['status'],'incomplete')

    def test_dependency_probe_is_never_executed_by_status_polling(self):
        self.p['probes']=[dict(label='Native dependency',command=['/usr/bin/false'])]
        with patch.object(launcher,'run',side_effect=AssertionError('poll executed a project command')):
            item=self.manager.inspect(self.p,snap())
        self.assertEqual(item['status'],'ready')
        self.assertTrue(item['deployed'])

    def test_launchagent_spawn_failure_is_visible(self):
        self.p['kind']='launchd'
        self.p.update(plist=str(self.root/'fixture.plist'),label='fixture')
        state=snap()
        state['agents']={'fixture':dict(spawn_failed=True,exit_code=78)}
        item=self.manager.inspect(self.p,state)
        self.assertEqual(item['status'],'failed')
        self.assertIn('78',item['reason'])

    def test_generic_command_requires_exact_cwd(self):
        self.p.update(match=[['next-server']],cwd_match=str(self.root))
        state=snap({1:'next-server'},{61903:{1}},{1:'/somewhere/else'})
        self.assertEqual(self.manager.inspect(self.p,state)['status'],'conflict')

    def test_duplicate_start_is_idempotent(self):
        self.manager.jobs['fixture']=dict(state='starting',message='waiting')
        with patch.object(self.manager,'snapshot',return_value=snap()),patch.object(threading.Thread,'start') as start:
            self.assertTrue(self.manager.action('fixture','start')['queued'])
            start.assert_not_called()

    def test_shared_port_reservation(self):
        other=dict(self.p,id='other')
        self.manager.products['other']=other
        self.manager.jobs['other']=dict(state='starting',message='waiting')
        with patch.object(self.manager,'snapshot',return_value=snap()):
            with self.assertRaisesRegex(ValueError,'同一端口'):
                self.manager.action('fixture','start')

    def test_startup_reservation_survives_a_second_controller(self):
        other = dict(self.p,id='other')
        self.config.write_text(json.dumps(dict(products=[self.p,other])))
        self.manager.load()
        with patch.object(self.manager,'snapshot',return_value=snap()),patch.object(threading.Thread,'start'):
            self.manager.action('fixture','start',False)
        second = launcher.Manager(self.config,self.root/'runtime')
        with patch.object(second,'snapshot',return_value=snap()):
            inventory = second.scan(True)
            self.assertEqual(inventory['products'][0]['status'],'starting')
            self.assertTrue(second.action('fixture','start',False)['queued'])
            with self.assertRaisesRegex(ValueError,'同一端口'):
                second.action('other','start',False)
        self.manager.startup_leases.pop('fixture').close()
        with patch.object(second,'snapshot',return_value=snap()):
            self.assertEqual(second.scan(True)['products'][0]['status'],'failed')
            with patch.object(threading.Thread,'start'):
                second.action('fixture','start',False)
            second.scan(True)
            self.assertEqual(second.jobs['fixture']['state'],'starting')
        for lease in second.startup_leases.values():
            lease.close()

    def test_compatible_service_avoids_fixed_and_reserved_ports(self):
        vite = str(self.root/'node_modules/vite/bin/vite.js')
        self.p.update(command=['node',vite,'--port','61903','--strictPort'],match=[[vite]])
        self.manager.products['fixture'] = self.p
        self.allow()
        self.manager.products['fixed'] = product(self.root,id='fixed')
        self.manager.products['pending'] = product(self.root,id='pending',ports=[61918])
        self.manager.jobs['pending'] = dict(state='starting',ports=[61910])
        state = snap({123:'foreign'},{61903:{123},61911:{123}})
        with patch.object(self.manager,'snapshot',return_value=state), \
             patch.object(launcher,'port_available',return_value=True), \
             patch.object(threading,'Thread') as thread:
            result = self.manager.scan(force=True)
            self.assertEqual(result['products'][0]['next_port'],61912)
            issue = next(issue for issue in result['port_issues'] if issue['port']==61903)
            self.assertEqual(len(issue['products']),2)
            self.assertIn('Fixture',issue['blocked'])
            self.assertTrue(self.manager.action('fixture','start',False)['queued'])
        planned = thread.call_args.kwargs['args'][0]
        self.assertEqual(planned['ports'],[61912])
        self.assertEqual(planned['url'],'http://127.0.0.1:61912/')
        self.assertEqual(planned['command'][3],'61912')
        self.assertEqual(self.p['ports'],[61903])
        self.assertEqual(self.manager.jobs['fixture']['ports'],[61912])

        # A new manager can find the live endpoint without startup-job memory.
        self.manager.jobs.clear()
        live = snap({123:'foreign',124:vite},{61903:{123},61912:{124}})
        with patch.object(self.manager,'snapshot',return_value=live), \
             patch.object(launcher,'http_check',return_value=True), \
             patch.object(self.manager,'open_product') as open_product:
            result = self.manager.inspect(self.p,live)
            self.assertEqual(result['status'],'running')
            self.assertEqual(result['url'],'http://127.0.0.1:61912/')
            self.manager.action('fixture','open')
            self.assertEqual(open_product.call_args.args[0]['url'],result['url'])

    def test_unknown_actions_never_spawn(self):
        with patch.object(launcher,'run') as run:
            with self.assertRaises(ValueError):self.manager.action('unknown','start')
            with self.assertRaises(ValueError):self.manager.action('fixture','shell')
            run.assert_not_called()

    def test_stop_refuses_reused_pid(self):
        self.manager.processes['fixture']=dict(pid=123,fingerprint='old')
        with patch.object(self.manager,'snapshot',return_value=snap({123:'python fixture.py'})),patch.object(os,'kill') as kill:
            with self.assertRaises(ValueError):self.manager.action('fixture','stop')
            kill.assert_not_called()

    def test_only_local_registered_open_urls(self):
        for url in ['https://example.com/','http://127.0.0.1:9999/','http://evil@127.0.0.1:61903/']:
            with self.assertRaises(ValueError):self.manager.validate_url(url,self.p)

    def test_private_entry_not_in_status(self):
        secret='private-test-token'
        f=self.root/'private.json'
        f.write_text(json.dumps({'url':'http://127.0.0.1:61903/?token='+secret}))
        self.p['entry']=dict(kind='json',file=str(f),key='url')
        self.assertNotIn(secret,json.dumps(self.manager.inspect(self.p,snap())))
        with patch.object(launcher,'http_check',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'过期'):self.manager.entry_url(self.p)

    def test_real_wake_ready_and_owned_stop(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        path=self.root/'fixture.py'
        path.write_text('from http.server import HTTPServer,BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n def do_GET(self):\n  self.send_response(200);self.end_headers();self.wfile.write(b"ready")\n def log_message(self,*args):pass\nHTTPServer(("127.0.0.1",'+str(port)+'),H).serve_forever()\n')
        self.p.update(ports=[port],url=f'http://127.0.0.1:{port}/',match=[[str(path)]])
        self.manager.products={'fixture':self.p}
        self.assertTrue(self.manager.action('fixture','start',False)['queued'])
        deadline=time.monotonic()+20
        try:
            while time.monotonic()<deadline and self.manager.jobs['fixture']['state']=='starting':time.sleep(.2)
            self.assertEqual(self.manager.jobs['fixture']['state'],'done',self.manager.jobs['fixture'])
            result=self.manager.scan(True)['products'][0]
            self.assertEqual(result['status'],'running');self.assertTrue(result['can_stop'])
            second = launcher.Manager(self.config,self.root/'runtime')
            self.assertTrue(second.scan(True)['products'][0]['can_stop'])
            second.action('fixture','stop')
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and launcher.http_check(self.p['url']):time.sleep(.1)
            self.assertFalse(launcher.http_check(self.p['url']))
            self.assertEqual(second.scan(True)['products'][0]['job']['state'],'stopped')
        finally:
            record=self.manager.processes.get('fixture')
            if record:
                record['child'].terminate();record['child'].wait(timeout=5)

    def test_stopping_a_warming_service_does_not_report_startup_failure(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            port = probe.getsockname()[1]
        path = self.root/'warming_fixture.py'
        path.write_text(
            'from http.server import HTTPServer,BaseHTTPRequestHandler\n'
            'class H(BaseHTTPRequestHandler):\n'
            ' def do_GET(self): self.send_response(503);self.end_headers()\n'
            ' def log_message(self,*args): pass\n'
            f'HTTPServer(("127.0.0.1",{port}),H).serve_forever()\n'
        )
        self.p.update(command=[sys.executable,'-B',str(path)],ports=[port],url=f'http://127.0.0.1:{port}/',match=[[str(path)]])
        self.manager.products = {'fixture':self.p}
        self.allow()
        self.config.write_text(json.dumps(dict(products=[self.p])))
        self.manager.action('fixture','start',False)
        deadline = time.monotonic()+10
        try:
            while time.monotonic()<deadline and 'fixture' not in self.manager.processes:
                time.sleep(.05)
            self.assertIn('fixture',self.manager.processes)
            second = launcher.Manager(self.config,self.root/'runtime')
            second.action('fixture','stop',False)
            while time.monotonic()<deadline and self.manager.startup_leases:
                time.sleep(.05)
            self.assertFalse(self.manager.startup_leases)
            self.assertEqual(self.manager.jobs['fixture']['state'],'stopped')
            self.assertEqual(second.scan(True)['products'][0]['job']['state'],'stopped')
        finally:
            record = self.manager.processes.get('fixture')
            if record and 'child' in record and record['child'].poll() is None:
                record['child'].terminate()
                record['child'].wait(timeout=5)


if __name__=='__main__':unittest.main(verbosity=2)
