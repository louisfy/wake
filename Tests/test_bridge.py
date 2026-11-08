"""Exercise the production Swift bridge and store against a faulty private-pipe peer."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'Sources/WakeApp'

HARNESS = r'''
import Foundation

@main
struct BridgeChecks {
    @MainActor static func main() async throws {
        signal(SIGPIPE, SIG_IGN)
        let arguments = CommandLine.arguments
        let resources = URL(fileURLWithPath: arguments[1])
        let directory = URL(fileURLWithPath: arguments[2])
        let bridge = ServiceBridge(resources: resources, dataDirectory: directory)
        let scenario = arguments[3]
        defer { bridge.close() }
        let first = try await bridge.request("info", as: EngineInfo.self)
        if scenario == "eof" {
            let _: ActionResult = try await bridge.request("break", as: ActionResult.self)
            try await Task.sleep(nanoseconds: 200_000_000)
            let second = try await bridge.request("info", as: EngineInfo.self)
            guard first.pid != second.pid else { fatalError("closed output pipe was reused") }
        } else if scenario == "malformed" {
            do {
                let _: ActionResult = try await bridge.request("malformed", as: ActionResult.self)
                fatalError("malformed reply was accepted")
            } catch {}
            let second = try await bridge.request("info", as: EngineInfo.self)
            guard first.pid != second.pid else { fatalError("malformed channel was reused") }
        } else if scenario == "closed" {
            bridge.close()
            do {
                let _: EngineInfo = try await bridge.request("info", as: EngineInfo.self)
                fatalError("request restarted a closed bridge")
            } catch {}
        } else if scenario == "queued-refresh" {
            let store = WakeStore(bridge: bridge)
            let automatic = Task { await store.refresh() }
            try await Task.sleep(nanoseconds: 50_000_000)
            await store.refresh(manual: true)
            await automatic.value
            let log = directory.appendingPathComponent("refreshes.txt")
            for _ in 0..<30 {
                let text = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
                if text.contains("True") { break }
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            let text = try String(contentsOf: log, encoding: .utf8)
            guard text.components(separatedBy: .newlines).filter({ !$0.isEmpty }).count == 2,
                  text.contains("False"), text.contains("True") else {
                fatalError("manual refresh was dropped while automatic refresh was active")
            }
        } else if scenario == "language" {
            let chinese = try await bridge.request("info", language: .simplifiedChinese, as: EngineInfo.self)
            let english = try await bridge.request("info", language: .english, as: EngineInfo.self)
            guard chinese.version == "zh-Hans", english.version == "en", chinese.pid == english.pid else {
                fatalError("language was not forwarded on the same pipe")
            }
        }
        print("PASS")
    }
}
'''

PEER = r'''
import json
import os
from pathlib import Path
import sys
import time

directory = Path(sys.argv[sys.argv.index('--data-dir') + 1])
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    if method == 'malformed':
        print('invalid-json', flush=True)
        continue
    if method == 'info':
        result = dict(version=request.get('language', 'fixture'), transport='private-pipe', pid=os.getpid())
    elif method == 'products':
        with (directory/'refreshes.txt').open('a') as file:
            file.write(str(request.get('params', {}).get('refresh', False))+'\n')
        time.sleep(.3)
        result = dict(products=[], checked_at=time.time(), scan_roots=[], port_issues=[])
    else:
        result = dict(message='ok')
    print(json.dumps(dict(id=request['id'], ok=True, result=result)), flush=True)
    if method == 'break':
        os.close(1)
'''


class SwiftBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('xcrun'):
            raise unittest.SkipTest('Swift command line tools are required')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        main = cls.root/'BridgeChecks.swift'
        main.write_text(HARNESS)
        cls.executable = cls.root/'bridge-checks'
        cache = cls.root/'swift-cache'
        cache.mkdir(parents=True,exist_ok=True)
        command = ['xcrun','swiftc','-parse-as-library','-O','-module-cache-path',str(cache),
                   str(SOURCE/'ServiceBridge.swift'),str(SOURCE/'Models.swift'),str(SOURCE/'Localization.swift'),str(main),
                   '-o',str(cls.executable)]
        result = subprocess.run(command,capture_output=True,text=True,timeout=90)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, scenario):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root/'Resources'
            (resources/'Python/bin').mkdir(parents=True)
            (resources/'Python/bin/python3.12').symlink_to(sys.executable)
            (resources/'Core').mkdir()
            (resources/'Core/ipc.py').write_text(PEER)
            result = subprocess.run([str(self.executable),str(resources),str(root/'data'),scenario],
                                    capture_output=True,text=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('PASS',result.stdout)

    def test_recovers_when_live_peer_closes_its_output(self):
        self.check('eof')

    def test_malformed_reply_fails_promptly_and_recovers(self):
        self.check('malformed')

    def test_closed_bridge_cannot_restart_the_engine(self):
        self.check('closed')

    def test_manual_refresh_is_queued_behind_an_automatic_refresh(self):
        self.check('queued-refresh')

    def test_language_is_forwarded_per_request_without_reconnecting(self):
        self.check('language')


if __name__ == '__main__':
    unittest.main()
