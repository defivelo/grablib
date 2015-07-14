import os

from jsmin import jsmin
from csscompressor import compress as cssmin

from .common import ProcessBase, GrablibError

MINIFY_LOOKUP = [
    (r'.js$', jsmin),
    (r'.css$', cssmin),
]


class MinifyLibs(ProcessBase):
    """
    minify and concatenate js and css
    """

    def __init__(self, minify_info, **kwargs):
        """
        initialize MinifyLibs.
        :param minify_info: dict of: files to generate => list of regexes of files to generate it from
        :param sites: dict of names of sites to simplify similar urls, see examples.
        """
        super(MinifyLibs, self).__init__(**kwargs)
        self.minify_info = minify_info

    def __call__(self):
        """
        alias to minify
        """
        return self.minify()

    def minify(self):
        grablib_files = list(self.grablib_files())
        for dst, srcs in self.minify_info.items():
            if isinstance(srcs, dict):
                if 'src_files' not in srcs:
                    raise GrablibError('minifying: "src_files" not found in "%s" sources' % dst)
                srcs = srcs['src_files']
                # TODO: any options here?
            if not isinstance(srcs, list):
                raise GrablibError('minifying: strange type of src_files: %s' % type(srcs))

            final_content = ''
            files_combined = 0
            for file_path, _ in self._search_paths(grablib_files, srcs):
                full_file_path = os.path.join(self.libs_root, file_path)
                final_content += self._minify_file(full_file_path)
                files_combined += 1
            if files_combined == 0:
                self.output('no files found to form "%s"' % dst, 1)
                continue
            _, dst = self._generate_path(self.libs_root_minified, dst)
            self._write(dst, final_content)
            self.output('%d files combined to form "%s"' % (files_combined, dst), 2)
        return True

    def grablib_files(self):
        """
        get a list of file paths in the libs root directory
        """
        for root, _, files in os.walk(self.libs_root):
            for f in files:
                yield f

    @classmethod
    def _minify_file(cls, file_path):
        if file_path.endswith('.js'):
            return cls._jsmin_file(file_path)
        elif file_path.endswith('.css'):
            return cls._cssmin_file(file_path)

        with open(file_path) as original_file:
            return original_file.read()

    @staticmethod
    def _jsmin_file(file_path):
        with open(file_path) as original_file:
            return jsmin(original_file.read())

    @staticmethod
    def _cssmin_file(file_path):
        with open(file_path) as original_file:
            return cssmin(original_file.read())