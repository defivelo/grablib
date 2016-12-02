import re
import shutil
from datetime import datetime
from pathlib import Path

import sass
from jsmin import jsmin

from .common import GrablibError, main_logger, progress_logger


class Builder:
    """
    main class for "building" assets eg. concatenating and minifying js and compiling sass
    """

    def __init__(self, *, build_root, build, download_root: str=None, debug=False, **data):
        self.build_root = Path(build_root).absolute()
        self.build = build
        self.download_root = download_root and Path(download_root).resolve()
        self.files_built = 0
        self.debug = debug

    def __call__(self):
        wipe_data = self.build.get('wipe', None)
        wipe_data and self.wipe(wipe_data)

        cat_data = self.build.get('cat', None)
        cat_data and self.cat(cat_data)

        sass_data = self.build.get('sass', None)
        sass_data and self.sass(sass_data)

    def cat(self, data):
        start = datetime.now()
        total_files_combined = 0
        for dest, srcs in data.items():
            if not isinstance(srcs, list):
                raise GrablibError('source files for concatenation should be a list')

            final_content, files_combined = '', 0
            for src in srcs:
                if isinstance(src, str):
                    src = {'src': src}
                path = self._file_path(src['src'])
                content = self._read_file(path)
                files_combined += 1
                for pattern, rep in src.get('replace', {}).items():
                    content = re.sub(pattern, rep, content)
                final_content += '/* === {} === */\n{}\n'.format(path.name, content.strip('\n'))
                progress_logger.debug('  appending %s', path.name)

            if files_combined == 0:
                main_logger.warning('no files found to form "%s"', dest)
                continue
            dest_path = self._dest_path(dest)
            dest_path.relative_to(self.build_root)
            self._write(dest_path, final_content)
            total_files_combined += files_combined
            progress_logger.info('%d files combined to form "%s"', files_combined, dest)

        time_taken = (datetime.now() - start).total_seconds() * 1000
        main_logger.info('%d files concatenated in %0.0fms', total_files_combined, time_taken)

    def sass(self, data):
        for dest, src in data.items():
            src_path = self._file_path(src)
            dest_path = self._dest_path(dest)
            sass_gen = SassGenerator(src_path, dest_path, self.debug)
            sass_gen()

    def wipe(self, globs):
        if isinstance(globs, str):
            globs = [globs]
        count = 0
        for g in globs:
            paths = list(self.build_root.glob(g))

            progress_logger.info('deleting %d paths based on "%s"', len(paths), g)
            for path in paths:
                if path.is_dir():
                    progress_logger.info('deleting directory "%s"', path)
                    shutil.rmtree(str(path))
                    count += 1
                elif path.exists():
                    assert path.is_file()
                    progress_logger.info('deleting file "%s"', path)
                    path.unlink()
                    count += 1
        main_logger.info('%d paths deleted', count)

    def _dest_path(self, p):
        new_path = self.build_root.joinpath(p)
        new_path.relative_to(self.build_root)
        return new_path

    starts_download = re.compile('^(?:DOWNLOAD|DL)/')

    def _file_path(self, src_path: str):
        if self.starts_download.match(src_path):
            assert self.download_root
            _src_path = self.starts_download.sub('', src_path)
            return self.download_root.joinpath(_src_path).resolve()
        else:
            return Path(src_path).resolve()

    def _read_file(self, file_path: Path):
        content = file_path.read_text()
        if not self.debug and file_path.name.endswith('.js') and not file_path.name.endswith('.min.js'):
            return jsmin(content, quote_chars='\'"`')
        return content

    def _write(self, new_path: Path, data):
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(data)


class SassGenerator:
    _errors = _files_generated = None

    def __init__(self, input_dir: Path, output_dir: Path, debug: bool=False):
        self._in_dir = input_dir
        assert self._in_dir.is_dir()
        self._out_dir = output_dir
        self._debug = debug
        if self._debug:
            self._out_dir_src = self._out_dir / '.src'
            self._src_dir = self._out_dir_src
        else:
            self._src_dir = self._in_dir

    def __call__(self):
        start = datetime.now()
        self._errors, self._files_generated = 0, 0

        if self._debug:
            self._out_dir.mkdir(parents=True)
            shutil.copytree(str(self._in_dir.resolve()), str(self._out_dir_src))

        self.process_directory(self._src_dir)
        time_taken = (datetime.now() - start).total_seconds() * 1000
        if not self._errors:
            main_logger.info('%d css files generated in %0.0fms, 0 errors', self._files_generated, time_taken)
        else:
            main_logger.error('%d css files generated in %0.0fms, %d errors',
                              self._files_generated, time_taken, self._errors)
            raise GrablibError('sass errors')

    def process_directory(self, d: Path):
        assert d.is_dir()
        for p in d.iterdir():
            if p.is_dir():
                self.process_directory(p)
            else:
                assert p.is_file()
                self.process_file(p)

    def process_file(self, f: Path):
        if f.suffix not in {'.css', '.scss', '.sass'}:
            return

        if f.name.startswith('_'):
            # mixin, not copied
            return

        rel_path = f.relative_to(self._src_dir)
        css_path = (self._out_dir / rel_path).with_suffix('.css')

        map_path = None
        if self._debug:
            map_path = css_path.with_suffix('.map')

        progress_logger.info('%s ▶ %s', rel_path, css_path.relative_to(self._out_dir))
        css = self.generate_css(f, map_path)
        if not css:
            return

        css_path.parent.mkdir(parents=True, exist_ok=True)
        if self._debug:
            css, css_map = css
            # correct the link to map file in css
            css = re.sub(r'/\*# sourceMappingURL=\S+ \*/', '/*# sourceMappingURL={} */'.format(map_path.name), css)
            map_path.write_text(css_map)
        css_path.write_text(css)
        self._files_generated += 1

    def generate_css(self, f: Path, map_path=None):
        output_style = 'nested' if self._debug else 'compressed'

        try:
            return sass.compile(
                filename=str(f),
                source_map_filename=map_path and str(map_path),
                output_style=output_style,
                precision=10,
            )
        except sass.CompileError as e:
            self._errors += 1
            main_logger.error('"%s", compile error: %s', f, e)
