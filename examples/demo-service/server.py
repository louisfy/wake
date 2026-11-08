"""Synthetic localhost-only demo. No credentials, dependencies, or user data."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import os
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(Path(__file__).parent/'public'),**kwargs)

    def log_message(self,*args):pass


if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','61935'))),Handler).serve_forever()
