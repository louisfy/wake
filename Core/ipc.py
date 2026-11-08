#!/usr/bin/env python3
"""Private JSON-line IPC. No HTTP server, TCP listener, or arbitrary command endpoint."""
import argparse
import concurrent.futures
import contextlib
import faulthandler
import json
import os
import signal
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parent))
from engine import DisplayError, Manager, VERSION, redact
from localization import engine_message, tr, use_language


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--seed',type=Path,required=True)
    parser.add_argument('--migration',type=Path)
    args=parser.parse_args()
    args.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    args.data_dir.chmod(0o700)
    config=args.data_dir/'products.json'
    if not config.exists():
        source=args.seed
        if args.migration and args.migration.exists():
            try:
                legacy=Path(json.loads(args.migration.read_text())['legacy_config'])
                if legacy.is_file():source=legacy
            except (KeyError,ValueError,OSError):pass
        definition=json.loads(source.read_text())
        # The native app owns this engine's lifecycle. A control-page port is no longer needed.
        definition.pop('port',None)
        config.write_text(json.dumps(definition,ensure_ascii=False,indent=2)+'\n')
        config.chmod(0o600)
    manager=Manager(config,args.data_dir/'Runtime')
    output=sys.stdout
    output_lock=threading.Lock()
    # Any incidental project/library prints go to the private application log, never the protocol.
    sys.stdout=sys.stderr
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)

    def emit(value):
        with output_lock:
            try:
                output.write(json.dumps(value,ensure_ascii=False)+'\n');output.flush()
            except BrokenPipeError:
                # The app may quit while a request or startup is finishing.
                pass

    def handle(request):
        with use_language(request.get('language')):
            respond(request)

    def respond(request):
        id=request.get('id')
        try:
            method=request.get('method');params=request.get('params') or {}
            if not isinstance(params,dict):raise ValueError('请求参数无效')
            if method=='info':
                result=dict(version=VERSION,transport='private-pipe',pid=os.getpid(),config=str(config),data_dir=str(args.data_dir))
            elif method=='products':
                if params.get('refresh'):manager.load()
                result=manager.scan(force=bool(params.get('refresh')))
            elif method=='action':
                result=manager.action(params.get('id'),params.get('action'),params.get('open',True) is True,params.get('approval'))
            elif method=='scan-roots':
                result=manager.set_scan_roots(params.get('roots'))
            elif method=='sync':
                if params.get('mode') not in ('sync','undo'):raise ValueError('不支持的同步操作')
                result=manager.sync(undo=params['mode']=='undo')
            else:raise ValueError('不支持的本机操作')
            emit(dict(id=id,ok=True,result=result))
        except PermissionError:
            emit(dict(id=id,ok=False,error=tr('读取部署目录需要文件夹访问权限。请在系统设置的「隐私与安全性 → 文件与文件夹」中检查唤醒的权限，然后重新检测。')))
        except DisplayError as error:
            emit(dict(id=id,ok=False,error=redact(str(error))))
        except json.JSONDecodeError:
            emit(dict(id=id,ok=False,error=tr('本地产品清单不是有效的 JSON。请修正格式后刷新。')))
        except (ValueError,RuntimeError) as error:
            emit(dict(id=id,ok=False,error=redact(engine_message(str(error)))))
        except Exception:
            emit(dict(id=id,ok=False,error=tr('操作未完成，请检查部署配置或查看本机日志。')))

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for line in sys.stdin:
            if len(line)>32768:
                emit(dict(id=None,ok=False,error=tr('请求过长')));continue
            try:
                request=json.loads(line)
                if not isinstance(request,dict) or not isinstance(request.get('id'),str):raise ValueError()
                pool.submit(handle,request)
            except (ValueError,TypeError):emit(dict(id=None,ok=False,error=tr('请求格式无效')))


if __name__=='__main__':main()
