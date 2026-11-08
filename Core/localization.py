"""Request-scoped UI translations. Stored project metadata is language-independent."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import re

_language = ContextVar('wake_language', default='en')
_english = json.loads(Path(__file__).with_name('messages.en.json').read_text(encoding='utf-8'))


def language():
    return _language.get()


@contextmanager
def use_language(value):
    token = _language.set('zh-Hans' if value == 'zh-Hans' else 'en')
    try:
        yield
    finally:
        _language.reset(token)


def tr(source, **values):
    """Format only developer-owned templates; keep project text opaque."""
    template = _english.get(source, source) if language() == 'en' else source
    return template.format(**values) if values else template


def join(values):
    return ('、' if language() == 'zh-Hans' else ', ').join(values)


def engine_message(message):
    """Render current and v1.0 startup records without rewriting persisted jobs."""
    if not isinstance(message, str):
        return message
    if match := re.fullmatch(r'已选择空闲端口 (\d+)，正在唤醒…', message):
        return tr('已选择空闲端口 {port}，正在唤醒…', port=match[1])
    if message.startswith('未通过依赖检查：'):
        return tr('未通过依赖检查：{checks}', checks=message.removeprefix('未通过依赖检查：'))
    return tr(message)


def project_text(project, field):
    """Translate generated copy only; honor overrides and manifest-provided text."""
    value = project.get(field, '')
    meta = project.get('discovery', {})
    if (not meta.get('auto') or field not in ('description', 'category', 'note')
            or not isinstance(value, str) or meta.get('generated', {}).get(field) != value):
        return value
    provided = meta.get('manifest_text')
    if field in (provided or []) or (provided is None and meta.get('identity', '').startswith('manifest:')):
        return value
    for prefix, template in (
        ('Node.js 本地服务 · ', 'Node.js 本地服务 · {entry}'),
        ('本地启动入口 · ', '本地启动入口 · {entry}'),
    ):
        if value.startswith(prefix):
            return tr(template, entry=value.removeprefix(prefix))
    return tr(value)
