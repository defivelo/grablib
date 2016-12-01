import re
import zipfile
from collections import OrderedDict
from io import BytesIO as IO
from pathlib import Path

import requests
from requests.exceptions import RequestException

from .common import GrablibError, logger

ALIASES = {
    'GITHUB': 'https://raw.githubusercontent.com',
    'CDNJS': 'http://cdnjs.cloudflare.com/ajax/libs',
}


class Downloader:
    """
    main class for downloading library files based on json file.
    """

    def __init__(self, *,
                 download_root: str,
                 download: dict,
                 aliases: dict=None,
                 **data):
        """
        :param download_root: path to download file to
        :param downloads: dict of urls and paths to download from from > to
        :param aliases: extra aliases for download addresses
        """
        self.download_root = Path(download_root).absolute()
        self.download = download
        self.aliases = ALIASES.copy()
        if aliases:
            self.aliases.update(aliases)
        self.downloaded = 0
        self.session = requests.Session()

    def __call__(self):
        """
        perform download and save.
        """
        logger.info('Downloading files to: %s', self.download_root)

        for url_base, value in self.download.items():
            url = self._setup_url(url_base)
            try:
                if isinstance(value, dict):
                    self._process_zip(url, value)
                else:
                    self._process_normal_file(url, value)
            except GrablibError as e:
                # create new exception to show which file download went wrong for
                if isinstance(value, OrderedDict):
                    value = dict(value)
                raise GrablibError('Error downloading "{}" to "{}"'.format(url, value)) from e
        logger.info('Download finished: %d files downloaded', self.downloaded)

    def _process_normal_file(self, url, dst):
        new_path = self._file_path(url, dst, regex=r'/(?P<filename>[^/]+)$')
        logger.info('downloading: %s > %s...', url, new_path.relative_to(self.download_root))
        content = self._get_url(url)
        self._write(new_path, content)
        self.downloaded += 1

    def _process_zip(self, url, value):
        logger.info('downloading zip: %s...', url)
        content = self._get_url(url)
        zipinmemory = IO(content)
        zcopied = 0
        with zipfile.ZipFile(zipinmemory) as zipf:
            logger.debug('%d file in zip archive', len(zipf.namelist()))

            for filepath in zipf.namelist():
                if filepath.endswith('/'):
                    continue
                target_found = False
                logger.debug('searching for target for %s...', filepath)
                for regex_pattern, targets in value.items():
                    if not re.match(regex_pattern, filepath):
                        continue
                    target_found = True
                    if targets is None:
                        logger.debug('target null, skipping')
                        break
                    if isinstance(targets, str):
                        targets = [targets]
                    for target in targets:
                        new_path = self._file_path(filepath, target, regex=regex_pattern)
                        logger.debug('%s > %s based on regex %s',
                                     filepath, new_path.relative_to(self.download_root), regex_pattern)
                        self._write(new_path, zipf.read(filepath))
                        zcopied += 1
                    break
                if not target_found:
                    logger.debug('no target found')
        logger.info('%d files copied from zip archive', zcopied)
        self.downloaded += 1

    def _file_path(self, src_path, dest, regex):
        """
        check src_path complies with regex and generate new filename
        """
        m = re.search(regex, src_path)
        if dest.endswith('/') or dest == '':
            dest += '{filename}'
        names = m.groupdict()
        if not names and m.groups():
            names = {'filename': m.groups()[-1]}
        for name, value in names.items():
            dest = dest.replace('{%s}' % name, value)
        # remove starting slash so path can't be absolute
        dest = dest.strip(' /')
        if not dest:
            logger.error('destination path must not resolve to be null')
            raise GrablibError('bad path')
        new_path = self.download_root.joinpath(dest)
        new_path.relative_to(self.download_root)
        return new_path

    def _setup_url(self, url_base):
        for name, value in self.aliases.items():
            url_base = url_base.replace(name, value)
        return url_base

    def _get_url(self, url):
        try:
            r = self.session.get(url)
        except RequestException as e:
            logger.error('Problem occurred during download: %s: %s', e.__class__.__name__, e)
            raise GrablibError('request error') from e
        else:
            if r.status_code != 200:
                logger.error('Wrong status code: %d', r.status_code)
                raise GrablibError('Wrong status code')
            return r.content

    def _write(self, new_path: Path, data):
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(data)
