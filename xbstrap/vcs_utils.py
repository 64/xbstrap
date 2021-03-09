# SPDX-License-Identifier: MIT

from enum import Enum
import os
import shutil
import subprocess
import urllib.request

from . import util as _util

class RepoStatus(Enum):
	GOOD = 0
	MISSING = 1
	OUTDATED = 2

def check_repo(src, *, check_remotes=0):
	if 'git' in src._this_yml:
		def get_local_commit(ref):
			try:
				out = subprocess.check_output(['git', 'show-ref', '--verify', ref],
						cwd=src.source_dir, stderr=subprocess.DEVNULL).decode().splitlines()
			except subprocess.CalledProcessError:
				return None
			assert len(out) == 1
			(commit, outref) = out[0].split(' ')
			return commit

		def get_remote_commit(ref):
			try:
				out = subprocess.check_output(['git', 'ls-remote', '--exit-code',
					src._this_yml['git'], ref]).decode().splitlines()
			except subprocess.CalledProcessError:
				return None
			assert len(out) == 1
			(commit, outref) = out[0].split('\t')
			return commit

		# There is a TOCTOU here; we assume that users do not concurrently delete directories.
		if not os.path.isdir(src.source_dir):
			return RepoStatus.MISSING
		if 'tag' in src._this_yml:
			ref = 'refs/tags/' + src._this_yml['tag']
			tracking_ref = 'refs/tags/' + src._this_yml['tag']
		else:
			ref = 'refs/heads/' + src._this_yml['branch']
			tracking_ref = 'refs/remotes/origin/' + src._this_yml['branch']
		local_commit = get_local_commit(tracking_ref)
		if local_commit is None:
			return RepoStatus.MISSING

		# Only check remote commits for
		do_check_remote = False
		if check_remotes >= 2:
			do_check_remote = True
		if check_remotes >= 1 and 'tag' not in src._this_yml:
			do_check_remote = True

		if do_check_remote:
			_util.log_info('Checking for remote updates of {}'.format(src.name))
			remote_commit = get_remote_commit(ref)
			if local_commit != remote_commit:
				return RepoStatus.OUTDATED
	elif 'hg' in src._this_yml:
		if not os.path.isdir(src.source_dir):
			return RepoStatus.MISSING
		args = ['hg', 'manifest', '--pager', 'never', '-r',]
		if 'tag' in src._this_yml:
			args.append(src._this_yml['tag'])
		else:
			args.append(src._this_yml['branch'])
		if subprocess.call(args, cwd=src.source_dir, stdout=subprocess.DEVNULL) != 0:
			return RepoStatus.MISSING
	elif 'svn' in src._this_yml:
		if not os.path.isdir(src.source_dir):
			return RepoStatus.MISSING
	else:
		assert 'url' in src._this_yml
		if not os.access(src.source_archive_file, os.F_OK):
			return RepoStatus.MISSING

	return RepoStatus.GOOD

def fetch_repo(cfg, src):
	source = src._this_yml

	if 'git' in source:
		git = shutil.which('git')
		if git is None:
			raise GenericException("git not found; please install it and retry")
		commit_yml = cfg._commit_yml.get('commits', dict()).get(src.name, dict())
		fixed_commit = commit_yml.get('fixed_commit', None)

		init = not os.path.isdir(src.source_dir)
		if init:
			_util.try_mkdir(src.source_dir)
			subprocess.check_call([git, 'init'], cwd=src.source_dir)
			subprocess.check_call([git, 'remote', 'add', 'origin', source['git']],
					cwd=src.source_dir)

		shallow = not source.get('disable_shallow_fetch', False)
		# We have to disable shallow fetches to get rolling versions right.
		if src.is_rolling_version:
			shallow = False

		args = [git, 'fetch']
		if 'tag' in source:
			if shallow:
				args.append('--depth=1')
			args.extend([source['git'], 'tag', source['tag']])
		else:
			# If a commit is specified, we need the branch's full history.
			# TODO: it's unclear whether this is the best strategy:
			#       - for simplicity, it might be easier to always pull the full history
			#       - some remotes support fetching individual SHA1s.
			if 'commit' in source or fixed_commit is not None:
				shallow = False
			# When initializing the repository, we fetch only one commit.
			# For updates, we fetch all *new* commits (= default behavior of 'git fetch').
			# We do not unshallow the repository.
			if init and shallow:
				args.append('--depth=1')
			args.extend([source['git'], 'refs/heads/' + source['branch']
					+ ':' + 'refs/remotes/origin/' + source['branch']])
		subprocess.check_call(args, cwd=src.source_dir)
	elif 'hg' in source:
		hg = shutil.which('hg')
		if hg is None:
			raise GenericException("mercurial (hg) not found; please install it and retry")
		_util.try_mkdir(src.source_dir)
		args = [hg, 'clone', source['hg'], src.source_dir]
		subprocess.check_call(args)
	elif 'svn' in source:
		svn = shutil.which('svn')
		if svn is None:
			raise GenericException("subversion (svn) not found; please install it and retry")
		_util.try_mkdir(src.source_dir)
		args = [svn, 'co', source['svn'], src.source_dir]
		subprocess.check_call(args)
	else:
		assert 'url' in source

		_util.try_mkdir(src.source_dir)
		with urllib.request.urlopen(source['url']) as req:
			with open(src.source_archive_file, 'wb') as f:
				shutil.copyfileobj(req, f)
