import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'Core'
sys.path.insert(0,str(ROOT))
import discovery
import engine as launcher


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.projects=self.root/'projects';self.projects.mkdir()
        self.config=dict(products=[],scan_roots=[str(self.projects)],node_path='/usr/local/bin/node')

    def tearDown(self):self.temp.cleanup()

    def project(self,name='sample',port=43123):
        root=self.projects/name;root.mkdir()
        self.write_package(root,port)
        return root

    def write_package(self,root,port):
        (root/'package.json').write_text(json.dumps(dict(name='sample-service',scripts=dict(dev='vite --port '+str(port)))))

    def sync(self,config=None,**kw):return discovery.synchronize(config or self.config,ROOT,**kw)

    def test_new_package_adds_one_card(self):
        p=self.project();config,report=self.sync()
        self.assertEqual(len(report['added']),1)
        self.assertEqual(config['products'][0]['ports'],[43123])
        self.assertIn(str(p/'node_modules/vite/bin/vite.js'),config['products'][0]['required'])

    def test_missing_or_empty_scan_scope_never_walks_personal_folders(self):
        for config in ({'products': []}, {'products': [], 'scan_roots': []}):
            with self.subTest(config=config),patch.object(discovery.os,'walk') as walk:
                after,report=discovery.synchronize(config,ROOT)
                walk.assert_not_called()
                self.assertEqual(after['products'],[])
                self.assertEqual(report['scan_roots'],[])

    def test_port_change_updates_same_id(self):
        root=self.project();config,_=self.sync();id=config['products'][0]['id']
        self.write_package(root,43124);after,report=self.sync(config)
        self.assertEqual(after['products'][0]['id'],id)
        self.assertEqual(after['products'][0]['ports'],[43124])
        self.assertEqual(len(report['updated']),1)

    def test_vite_proxy_port_is_not_frontend_port(self):
        root=self.project();(root/'package.json').write_text(json.dumps(dict(scripts=dict(dev='vite --host 127.0.0.1'))))
        (root/'vite.config.ts').write_text('export default {server:{proxy:{"/api":{target:"http://127.0.0.1:8000"}}}}')
        config,_=self.sync();self.assertEqual(config['products'][0]['ports'],[5173])

    def test_vite_explicit_server_port_is_detected(self):
        root=self.project();(root/'package.json').write_text(json.dumps(dict(scripts=dict(dev='vite'))))
        (root/'vite.config.ts').write_text('export default {server:{host:"127.0.0.1",port:43126}}')
        config,_=self.sync();self.assertEqual(config['products'][0]['ports'],[43126])

    def test_delete_removes_only_card(self):
        root=self.project();config,_=self.sync();shutil.rmtree(root)
        after,report=self.sync(config)
        self.assertEqual(after['products'],[]);self.assertEqual(len(report['removed']),1)

    def test_unavailable_root_never_removes_cards(self):
        root=self.project();config,_=self.sync()
        shutil.rmtree(self.projects)
        after,report=self.sync(config)
        self.assertEqual(len(after['products']),1);self.assertFalse(report['removed']);self.assertTrue(report['warnings'])

    def test_running_deleted_service_is_kept(self):
        root=self.project();config,_=self.sync();shutil.rmtree(root)
        after,report=self.sync(config,is_active=lambda p:True)
        self.assertEqual(len(after['products']),1);self.assertTrue(report['warnings'])

    def test_custom_name_survives_multiple_syncs(self):
        self.project();config,_=self.sync();config['products'][0]['name']='我的工作台'
        after,_=self.sync(config);again,_=self.sync(after)
        self.assertEqual(again['products'][0]['name'],'我的工作台')

    def test_renamed_directory_keeps_id(self):
        root=self.project();config,_=self.sync();id=config['products'][0]['id']
        moved=root.with_name('renamed');root.rename(moved)
        after,report=self.sync(config)
        self.assertEqual(len(after['products']),1);self.assertEqual(after['products'][0]['id'],id)
        self.assertEqual(after['products'][0]['root'],str(moved));self.assertFalse(report['added']);self.assertFalse(report['removed'])

    def test_source_alias_does_not_duplicate_installed_product(self):
        root=self.project();candidate=discovery.detect(root,'/usr/local/bin/node')
        installed=self.root/'installed';installed.mkdir()
        candidate.update(root=str(installed),discovery={'aliases':[str(root)]})
        self.config['products']=[candidate]
        after,report=self.sync()
        self.assertEqual(len(after['products']),1);self.assertFalse(report['added'])

    def test_training_scripts_are_not_web_services(self):
        root=self.projects/'training';root.mkdir()
        (root/'run_all.sh').write_text('python3 train.py --num_iters 1000\n')
        after,report=self.sync();self.assertEqual(after['products'],[])

    def test_dependency_folders_are_ignored(self):
        root=self.projects/'node_modules';root.mkdir()
        child=root/'package';child.mkdir();self.write_package(child,43123)
        after,_=self.sync();self.assertEqual(after['products'],[])

    def test_python_server_is_discovered_without_executing_it(self):
        root=self.projects/'python-api';root.mkdir()
        (root/'app.py').write_text('import uvicorn\nPORT=43125\nuvicorn.run("app:app",port=PORT)\n')
        after,report=self.sync();p=after['products'][0]
        self.assertEqual(p['ports'],[43125]);self.assertEqual(len(report['added']),1)
        self.assertIn(str(root/'.venv/bin/python'),p['required'])

    def test_incomplete_product_promotes_when_entry_appears(self):
        root=self.projects/'ComfyUI';root.mkdir();(root/'models').mkdir();(root/'custom_nodes').mkdir()
        (root/'main.py').write_text('# ComfyUI entry')
        old=dict(id='comfyui',name='ComfyUI',description='incomplete',category='test',icon='cube',color='blue',
                 root=str(root),kind='incomplete',ports=[8188],required=[str(root/'main.py')])
        updated=discovery.update_curated(old)
        self.assertEqual(updated['id'],'comfyui');self.assertEqual(updated['kind'],'process')
        self.assertIn('--listen',updated['command'])

    def test_build_only_package_is_not_a_service(self):
        root=self.projects/'library';root.mkdir()
        (root/'package.json').write_text(json.dumps(dict(scripts=dict(build='tsc'))))
        after,_=self.sync();self.assertEqual(after['products'],[])

    def test_env_secrets_never_enter_results(self):
        root=self.project();(root/'.env').write_text('API_KEY=private-do-not-copy')
        after,report=self.sync()
        self.assertNotIn('private-do-not-copy',json.dumps((after,report)))

    def test_home_working_directory_does_not_relocate_product(self):
        import plistlib
        root=self.project();file=root/'service';file.mkdir();host=file/'host.mjs';host.write_text('')
        plist=self.root/'agent.plist';plist.write_bytes(plistlib.dumps(dict(WorkingDirectory=str(self.root),ProgramArguments=['/usr/bin/node',str(host)])))
        p=discovery.detect(root,'/usr/local/bin/node');p.update(kind='launchd',plist=str(plist),required=[str(host)])
        self.assertEqual(discovery.update_curated(p)['root'],str(root))

    def test_sync_persistence_and_undo(self):
        self.project();file=self.root/'products.json';file.write_text(json.dumps(self.config))
        manager=launcher.Manager(file,self.root/'runtime')
        state=dict(commands={},listeners={},cwds={},parents={},docker=False,agents={})
        with patch.object(manager,'snapshot',return_value=state):result=manager.sync()
        self.assertEqual(len(result['report']['added']),1)
        self.assertEqual(len(json.loads(file.read_text())['products']),1)
        self.assertEqual(len(list((self.root/'runtime/backups').glob('*.json'))),1)
        manager.sync(undo=True)
        self.assertEqual(json.loads(file.read_text())['products'],[])

    def test_undo_does_not_overwrite_later_user_edit(self):
        self.project();file=self.root/'products.json';file.write_text(json.dumps(self.config))
        manager=launcher.Manager(file,self.root/'runtime')
        state=dict(commands={},listeners={},cwds={},parents={},docker=False,agents={})
        with patch.object(manager,'snapshot',return_value=state):manager.sync()
        data=json.loads(file.read_text());data['user_note']='keep';file.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'其他修改'):manager.sync(undo=True)
        self.assertEqual(json.loads(file.read_text())['user_note'],'keep')

    def test_unsafe_manifest_is_skipped(self):
        root=self.projects/'bad';root.mkdir()
        (root/'.launchpad.json').write_text(json.dumps(dict(ports=[43123],url='https://outside.example/',command=['node','server.js'])))
        file=self.root/'products.json';file.write_text(json.dumps(self.config));manager=launcher.Manager(file,self.root/'runtime')
        state=dict(commands={},listeners={},cwds={},parents={},docker=False,agents={})
        with patch.object(manager,'snapshot',return_value=state):result=manager.sync()
        self.assertEqual(json.loads(file.read_text())['products'],[])
        self.assertTrue(result['report']['warnings']);self.assertFalse(result['report']['added'])


if __name__=='__main__':unittest.main(verbosity=2)
