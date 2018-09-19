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

# to help debug, look into deoplete/child.py
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
        self.is_debug_enabled = True
        self.buf_paths = {}
        self.run_dirs = {}
        self.cache = {}

    def on_init(self, context):
        self.warning('init: %s', context['event'])


    def on_event(self, context):
        self.warning('event: %s', context['event'])
        self._args = self._args_from_neoinclude(context)

        # sometimes context['bufnr'] is str, sometimes it is int
        bufnr = int(context['bufnr'])
        event = context['event']

        if event == 'BufDelete':
            pass
        elif event == 'BufReadPost':
            pass
        elif event == 'Init':
            pass
        elif event == 'InsertEnter':
            pass

        # clear cache
        if self.cache:
            self.cache = {}

        if bufnr not in self.buf_paths:
            bufpath = self.vim.eval('bufname({})'.format(bufnr))
            self.buf_paths[bufnr] = bufpath
        else:
            bufpath = self.buf_paths[bufnr]

        cwd = Path(os.path.dirname(bufpath))
        clang_file, self.run_dir = self._find_clang_file(
                cwd, self.vars['clang_file_path'])
        clang = self._args_from_clang(clang_file)

        if clang:
            self._args += clang
        else:
            self._args += (self.vars['default_cpp_options']
                           if context['filetype'] == 'cpp'
                           else self.vars['default_c_options'])

    def _args_from_clang(self, clang_file):
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

    def _find_clang_file(self, cwd, names):
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
        return None, cwd

    def get_complete_position(self, context):
        inputs = context['input']
        m = re.search('[a-zA-Z0-9_]*$', inputs)
        if m:
            self.completing_word = inputs[:m.start()]
        else:
            self.completing_word = inputs
        return m.start() if m else -1

    def gather_candidates(self, context):
        if not self.executable_clang:
            return []

        line = context['position'][1]
        column = context['complete_position'] + 1
        lang = 'c++' if context['filetype'] == 'cpp' else 'c'
        bufnr = int(context['bufnr'])
        buf = '\n'.join(getlines(self.vim)).encode(self.encoding)

        if self.completing_word in self.cache:
            return self.cache[self.completing_word]

        args = [
            self.vars['clang_binary'],
            '-x', lang, '-fsyntax-only',
            '-Xclang', '-code-completion-macros',
            '-Xclang', '-code-completion-at=-:{}:{}'.format(line, column),
            '-',
            '-I', os.path.dirname(context['bufpath']),
        ]
        self.warning('=args: %s %s', bufnr, ' '.join(args))
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
            rv = []
        else:
            rv = self._parse_lines(result.splitlines())
        finally:
            self.cache[self.completing_word] = rv
            return rv

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

