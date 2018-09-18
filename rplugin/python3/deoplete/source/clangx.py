# =============================================================================
# FILE: clangx.py
# AUTHOR: Shougo Matsushita <Shougo.Matsu at gmail.com>
# =============================================================================

import re
import os.path
from os.path import expanduser, expandvars, dirname, isabs, isfile, join
from pathlib import Path
import subprocess
import shlex
from itertools import chain

from deoplete.util import getlines, error
from .base import Base

def dprint(*args, **kwargs):
    pass
# fff = open('/dev/pts/6', 'w')
# def dprint(*args, **kwargs):
#     print(*args, **kwargs, file=fff)

class Source(Base):
    run_dir = ''

    def __init__(self, vim):
        Base.__init__(self, vim)

        self.name = 'clangx'
        self.filetypes = ['c', 'cpp']
        self.mark = '[clangx]'
        self.rank = 500
        self.executable_clang = self.vim.call('executable', 'clang')
        self.encoding = self.vim.eval('&encoding')
        self.input_pattern = r'\.[a-zA-Z0-9_?!]*|[a-zA-Z]\w*::\w*|->\w*'
        self.vars = {
            'clang_binary': 'clang',
            'default_c_options': '',
            'default_cpp_options': '',
            'clang_file_path': ['.clang_complete', '.git/clang_complete'],
        }

        self._args = []

    def on_event(self, context):
        self._args = self._args_from_neoinclude(context)

        bufpath = self.vim.eval('bufname({})'.format(context['bufnr']))
        self.run_dir = Path(os.path.dirname(bufpath))
        dprint(context['bufnr'], bufpath, self.run_dir)

        clang = self._args_from_clang(context, self.vars['clang_file_path'])
        if clang:
            self._args += clang
        else:
            self._args += (self.vars['default_cpp_options']
                           if context['filetype'] == 'cpp'
                           else self.vars['default_c_options'])

    def get_complete_position(self, context):
        m = re.search('[a-zA-Z0-9_]*$', context['input'])
        return m.start() if m else -1

    def gather_candidates(self, context):
        if not self.executable_clang:
            return []

        line = context['position'][1]
        column = context['complete_position'] + 1
        lang = 'c++' if context['filetype'] == 'cpp' else 'c'
        buf = '\n'.join(getlines(self.vim)).encode(self.encoding)

        args = [
            self.vars['clang_binary'],
            '-x', lang, '-fsyntax-only',
            '-Xclang', '-code-completion-macros',
            '-Xclang', '-code-completion-at=-:{}:{}'.format(line, column),
            '-',
            '-I', os.path.dirname(context['bufpath']),
        ]
        args += self._args

        try:
            proc = subprocess.Popen(args=args,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    cwd=self.run_dir)
            result, errs = proc.communicate(buf, timeout=10)
            result = result.decode(self.encoding)
        except subprocess.TimeoutExpired as e:
            proc.kill()
            return []

        return self._parse_lines(result.splitlines())

    def _args_from_neoinclude(self, context):
        if not self.vim.call(
                'exists', '*neoinclude#get_path'):
            return []

        # Make cache
        self.vim.call('neoinclude#include#get_include_files')

        return list(chain.from_iterable(
            [['-I', x] for x in
             self.vim.call('neoinclude#get_path',
                           context['bufnr'],
                           context['filetype']).replace(';', ',').split(',')
             if x != '']))

    def _find_clang_file(self, context, names):
        cwd = self.run_dir
        dirs = [cwd.resolve()] + list(cwd.parents)
        for d in dirs:
            d = str(d)
            for name in names:
                if isabs(name):
                    if isfile(name):
                        return name, dirname(name)
                else:
                    clang_file = join(d, name)
                    if isfile(clang_file):
                        return clang_file, d
        return [], cwd

    def _args_from_clang(self, context, names):
        clang_file, self.run_dir = self._find_clang_file(context, names)
        if not clang_file:
            return []

        try:
            with open(clang_file) as f:
                args = shlex.split(' '.join(f.readlines()))
                args = [expanduser(expandvars(p)) for p in args]
                return args
        except Exception as e:
            error(self.vim, 'Parse Failed: ' + clang_file)
        return []

    pattern1 = re.compile('COMPLETION:\s+(.{,}?)( : (.*))?$')
    pattern2 = re.compile('(\[#|<#|#>|{#|#})')
    pattern3 = re.compile('#\]')

    def _parse_lines(self, lines):
        candidates = []
        for line in lines:
            # m = re.search('^COMPLETION:\s+(.{,}?) : (.{,}?)$', line)
            m = re.match(self.pattern1, line)
            if not m or m.group(1).startswith('PFNG'):
                continue
            elif m.group(2) is None:
                candidates.append({'word': m.group(1)})
                continue

            word = m.group(1)
            menu = m.group(3)
            menu = re.sub(self.pattern2, '', menu)
            menu = re.sub(self.pattern3, ' ', menu, 1)
            candidate = {'word': word, 'dup': 1}
            if menu != word:
                candidate['menu'] = menu
                candidate['info'] = menu
            candidates.append(candidate)
        return candidates

