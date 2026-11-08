"""Public first-run boundaries use only synthetic temporary deployments."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Core'))
from engine import Manager, port_option


class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.p=dict(id='demo',name='Demo',description='synthetic',category='Demo',icon='cube',color='blue',
                    root=str(self.root),kind='process',command=['node','demo.js'],ports=[],required=[])
        self.config=self.root/'products.json'
        self.config.write_text(json.dumps(dict(products=[self.p],scan_roots=[])))
        self.manager=Manager(self.config,self.root/'runtime')

    def tearDown(self):
        for lease in self.manager.startup_leases.values():lease.close()
        self.temp.cleanup()

    def test_unreviewed_start_cannot_create_a_worker(self):
        state=dict(commands={},parents={},listeners={},cwds={},docker=False)
        with patch.object(self.manager,'snapshot',return_value=state),patch('engine.threading.Thread') as worker:
            with self.assertRaisesRegex(ValueError,'审查'):
                self.manager.action('demo','start',False)
            worker.assert_not_called()

    def test_consent_survives_reopen_but_not_a_command_change(self):
        preview=self.manager.approval(self.p)
        self.assertTrue(preview['needs_approval'])
        self.manager.approve(self.p,preview['approval_fingerprint'])
        other=Manager(self.config,self.root/'runtime')
        self.assertFalse(other.approval(self.p)['needs_approval'])
        self.p['command']=['node','different.js']
        self.assertTrue(other.approval(self.p)['needs_approval'])
        with self.assertRaisesRegex(ValueError,'已变化'):
            other.approve(self.p,preview['approval_fingerprint'])

    def test_discovery_cannot_self_approve(self):
        self.p['trusted']=True
        self.p['approval_fingerprint']='forged'
        self.assertTrue(self.manager.approval(self.p)['needs_approval'])

    def test_unreviewed_running_entry_cannot_open_a_registered_app(self):
        self.p.update(open_app=str(self.root/'untrusted.app'),match=[['demo-process']])
        self.manager.products['demo']=self.p
        state=dict(commands={123:'demo-process'},parents={},listeners={},cwds={},docker=False)
        with patch.object(self.manager,'snapshot',return_value=state),patch.object(self.manager,'open_product') as opened:
            with self.assertRaisesRegex(ValueError,'审查'):
                self.manager.action('demo','open')
            opened.assert_not_called()

    def test_scope_persists_and_preserves_product_list(self):
        self.manager.set_scan_roots([str(self.root),str(self.root)])
        saved=json.loads(self.config.read_text())
        self.assertEqual(saved['scan_roots'],[str(self.root.resolve())])
        self.assertEqual(saved['products'],[self.p])
        self.manager.set_scan_roots([])
        self.assertEqual(json.loads(self.config.read_text())['scan_roots'],[])
        with self.assertRaises(ValueError):self.manager.set_scan_roots(['relative/path'])

    def test_port_remapping_is_opt_in(self):
        self.assertIsNone(port_option(self.p))
        self.p.update(ports=[3000],url='http://127.0.0.1:3000/',port_strategy={'environment':'HTTP_PORT'})
        self.assertEqual(port_option(self.p),'HTTP_PORT')


if __name__=='__main__':unittest.main()
