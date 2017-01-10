# -*- coding: utf-8 -*-

from __future__ import absolute_import

import fnmatch
import os
import shutil
import sys
import zipfile
import click
from . import _cache
from . import _config
from . import _gitlab
from . import _paths
from . import _yaml


@click.group()
def main():
    """Art, the Gitlab artifact repository client."""


@main.command()
@click.argument('gitlab_url')
@click.argument('private_token')
def configure(**kwargs):
    """Configure Gitlab URL and access token."""

    _config.save(**kwargs)


@main.command()
def update():
    """Update latest tag/branch commits."""

    config = _config.guess_from_env() or _config.load()
    gitlab = _gitlab.Gitlab(**config)
    artifacts = _yaml.load(_paths.artifacts_file)

    for entry in artifacts:
        entry['commit'] = gitlab.get_ref_commit(entry['project'], entry['ref'])
        entry['build_id'] = gitlab.get_commit_last_successful_build(entry['project'], entry['commit'], entry['build'])
        click.echo('* %s: %s => %s => %s' % (
            entry['project'], entry['ref'], entry['commit'], entry['build_id']), sys.stderr)

    _yaml.save(_paths.artifacts_lock_file, artifacts)


@main.command()
def download():
    """Download artifacts to local cache."""

    config = _config.guess_from_env() or _config.load()
    gitlab = _gitlab.Gitlab(**config)
    _paths.check_artifacts_lock_file()
    artifacts_lock = _yaml.load(_paths.artifacts_lock_file)

    for entry in artifacts_lock:
        filename = '%s/%s.zip' % (entry['project'], entry['build_id'])
        try:
            archive = _cache.get(filename)
        except KeyError:
            click.echo('* %s: %s => downloading...' % (entry['project'], entry['build_id']))
            artifacts_zip = gitlab.get_artifacts_zip(entry['project'], entry['build_id'])
            _cache.save(filename, artifacts_zip)
            click.echo('* %s: %s => downloaded.' % (entry['project'], entry['build_id']))
        else:
            click.echo('* %s: %s => present' % (entry['project'], entry['build_id']))


@main.command()
def install():
    """Install artifacts to current directory."""

    config = _config.guess_from_env() or _config.load()
    gitlab = _gitlab.Gitlab(**config)
    _paths.check_artifacts_lock_file()
    artifacts_lock = _yaml.load(_paths.artifacts_lock_file)

    for entry in artifacts_lock:
        # convert the "install" dictionary to list of (match, translate)
        install = []
        for source, destination in entry['install'].iteritems():
            # Nb. Defaults parameters on lambda are required due to derpy
            # Python closure semantics (scope capture).
            if source == '.':
                # "copy all" filter
                install.append((
                    lambda f, s=source, d=destination: True,
                    lambda f, s=source, d=destination: os.path.join(d, f)
                ))
            elif source.endswith('/'):
                # 1:1 directory filter
                install.append((
                    lambda f, s=source, d=destination: f.startswith(s),
                    lambda f, s=source, d=destination: os.path.join(d, f[len(s):])
                ))
            else:
                # 1:1 file filter
                install.append((
                    lambda f, s=source, d=destination: f == s,
                    lambda f, s=source, d=destination: d
                ))
        # make sure there are no bugs in the lambdas above
        del source, destination

        # open the artifacts.zip archive
        filename = '%s/%s.zip' % (entry['project'], entry['build_id'])
        archive_file = _cache.get(filename)
        archive = zipfile.ZipFile(archive_file)

        # iterate over the zip archive
        for member in archive.namelist():
            for match, translate in install:
                if match(member):
                    target = translate(member)
                    click.echo('* install: %s => %s' % (member, target))
                    if os.sep in target:
                        _paths.mkdirs(os.path.dirname(target))
                    with archive.open(member) as fmember:
                        with open(target, 'wb') as ftarget:
                            shutil.copyfileobj(fmember, ftarget)
