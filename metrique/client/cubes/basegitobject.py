#!/usr/bin/env python
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
# Author: "Chris Ward <cward@redhat.com>

from gittle.gittle import Gittle
import os
import subprocess

from metrique.client.cubes.basecube import BaseCube
from metrique.tools.decorators import memo

TMP_DIR = '~/.metrique/gitrepos/'


class BaseGitObject(BaseCube):
    """
    Driver to help extract data from GIT repos
    """
    def __init__(self, **kwargs):
        super(BaseGitObject, self).__init__(**kwargs)

    @memo
    def get_repo(self, uri, fetch=True):
        repo_path = os.path.join(TMP_DIR, str(abs(hash(uri))))
        self.repo_path = repo_path
        self.logger.debug('GIT URI: %s' % uri)
        if fetch:
            if not os.path.exists(repo_path):
                self.logger.info('Cloning git repo to %s' % repo_path)
                cmd = 'git clone %s %s' % (uri, repo_path)
                rc = subprocess.call(cmd.split(' '))
                if rc != 0:
                    raise IOError("Failed to clone repo")
            else:
                os.chdir(repo_path)
                self.logger.info(' ... Fetching git repo (%s)' % repo_path)
                cmd = 'git pull'
                rc = subprocess.call(cmd.split(' '))
                if rc != 0:
                    raise RuntimeError('Failed to fetch repo')
                self.logger.debug(' ... Fetch complete')

        return Gittle(repo_path)
