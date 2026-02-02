"""
GitHub update checking and git-based update mechanism.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import config
from utils.database import get_setting, set_setting

logger = logging.getLogger('intercept.updater')

# Cache keys for settings
CACHE_KEY_LAST_CHECK = 'update.last_check'
CACHE_KEY_LATEST_VERSION = 'update.latest_version'
CACHE_KEY_RELEASE_URL = 'update.release_url'
CACHE_KEY_RELEASE_NOTES = 'update.release_notes'
CACHE_KEY_DISMISSED_VERSION = 'update.dismissed_version'

# Default check interval (6 hours in seconds)
DEFAULT_CHECK_INTERVAL = 6 * 60 * 60


def _get_github_repo() -> str:
    """Get the configured GitHub repository."""
    return getattr(config, 'GITHUB_REPO', 'smittix/intercept')


def _get_check_interval() -> int:
    """Get the configured check interval in seconds."""
    hours = getattr(config, 'UPDATE_CHECK_INTERVAL_HOURS', 6)
    return hours * 60 * 60


def _is_update_check_enabled() -> bool:
    """Check if update checking is enabled."""
    return getattr(config, 'UPDATE_CHECK_ENABLED', True)


def _compare_versions(current: str, latest: str) -> int:
    """
    Compare two semantic version strings.

    Returns:
        -1 if current < latest (update available)
         0 if current == latest
         1 if current > latest
    """
    def parse_version(v: str) -> tuple:
        # Strip 'v' prefix if present
        v = v.lstrip('v')
        # Split by dots and convert to integers
        parts = []
        for part in v.split('.'):
            # Handle pre-release suffixes like 2.11.0-beta
            match = re.match(r'^(\d+)', part)
            if match:
                parts.append(int(match.group(1)))
            else:
                parts.append(0)
        # Pad to at least 3 parts
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    try:
        current_parts = parse_version(current)
        latest_parts = parse_version(latest)

        if current_parts < latest_parts:
            return -1
        elif current_parts > latest_parts:
            return 1
        return 0
    except Exception as e:
        logger.warning(f"Error comparing versions '{current}' and '{latest}': {e}")
        return 0


def _fetch_github_release() -> dict[str, Any] | None:
    """
    Fetch the latest release from GitHub API.

    Returns:
        Dict with release info or None on error
    """
    repo = _get_github_repo()
    url = f'https://api.github.com/repos/{repo}/releases/latest'

    try:
        req = Request(url, headers={
            'User-Agent': 'Intercept-SIGINT',
            'Accept': 'application/vnd.github.v3+json'
        })

        with urlopen(req, timeout=10) as response:
            # Check rate limit headers
            remaining = response.headers.get('X-RateLimit-Remaining')
            if remaining and int(remaining) < 10:
                logger.warning(f"GitHub API rate limit low: {remaining} remaining")

            data = json.loads(response.read().decode('utf-8'))
            return {
                'tag_name': data.get('tag_name', ''),
                'html_url': data.get('html_url', ''),
                'body': data.get('body', ''),
                'published_at': data.get('published_at', ''),
                'name': data.get('name', '')
            }
    except HTTPError as e:
        if e.code == 404:
            logger.info("No releases found on GitHub")
        else:
            logger.warning(f"GitHub API error: {e.code} {e.reason}")
        return None
    except URLError as e:
        logger.warning(f"Failed to fetch GitHub release: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching GitHub release: {e}")
        return None


def check_for_updates(force: bool = False) -> dict[str, Any]:
    """
    Check GitHub for updates.

    Uses caching to avoid excessive API calls. Only checks GitHub if:
    - force=True, or
    - Last check was more than check_interval ago

    Args:
        force: If True, bypass cache and check GitHub directly

    Returns:
        Dict with update status information
    """
    if not _is_update_check_enabled():
        return {
            'success': True,
            'update_available': False,
            'disabled': True,
            'message': 'Update checking is disabled'
        }

    current_version = config.VERSION

    # Check cache unless forced
    if not force:
        last_check = get_setting(CACHE_KEY_LAST_CHECK)
        if last_check:
            try:
                last_check_time = float(last_check)
                check_interval = _get_check_interval()
                if time.time() - last_check_time < check_interval:
                    # Return cached data
                    cached_version = get_setting(CACHE_KEY_LATEST_VERSION)
                    if cached_version:
                        dismissed = get_setting(CACHE_KEY_DISMISSED_VERSION)
                        update_available = _compare_versions(current_version, cached_version) < 0

                        # Don't show update if user dismissed this version
                        show_notification = update_available and dismissed != cached_version

                        return {
                            'success': True,
                            'checked': True,
                            'update_available': update_available,
                            'show_notification': show_notification,
                            'current_version': current_version,
                            'latest_version': cached_version,
                            'release_url': get_setting(CACHE_KEY_RELEASE_URL) or '',
                            'release_notes': get_setting(CACHE_KEY_RELEASE_NOTES) or '',
                            'cached': True,
                            'last_check': datetime.fromtimestamp(last_check_time).isoformat()
                        }
            except (ValueError, TypeError):
                pass

    # Fetch from GitHub
    release = _fetch_github_release()

    if not release:
        # Return cached data if available, otherwise error
        cached_version = get_setting(CACHE_KEY_LATEST_VERSION)
        if cached_version:
            update_available = _compare_versions(current_version, cached_version) < 0
            return {
                'success': True,
                'checked': True,
                'update_available': update_available,
                'current_version': current_version,
                'latest_version': cached_version,
                'release_url': get_setting(CACHE_KEY_RELEASE_URL) or '',
                'release_notes': get_setting(CACHE_KEY_RELEASE_NOTES) or '',
                'cached': True,
                'network_error': True
            }
        return {
            'success': False,
            'error': 'Failed to check for updates'
        }

    latest_version = release['tag_name'].lstrip('v')

    # Update cache
    set_setting(CACHE_KEY_LAST_CHECK, str(time.time()))
    set_setting(CACHE_KEY_LATEST_VERSION, latest_version)
    set_setting(CACHE_KEY_RELEASE_URL, release['html_url'])
    set_setting(CACHE_KEY_RELEASE_NOTES, release['body'][:2000] if release['body'] else '')

    update_available = _compare_versions(current_version, latest_version) < 0
    dismissed = get_setting(CACHE_KEY_DISMISSED_VERSION)
    show_notification = update_available and dismissed != latest_version

    return {
        'success': True,
        'checked': True,
        'update_available': update_available,
        'show_notification': show_notification,
        'current_version': current_version,
        'latest_version': latest_version,
        'release_url': release['html_url'],
        'release_notes': release['body'] or '',
        'release_name': release['name'] or f'v{latest_version}',
        'published_at': release['published_at'],
        'cached': False,
        'last_check': datetime.now().isoformat()
    }


def get_update_status() -> dict[str, Any]:
    """
    Get current update status from cache without triggering a check.

    Returns:
        Dict with cached update status
    """
    current_version = config.VERSION
    cached_version = get_setting(CACHE_KEY_LATEST_VERSION)
    last_check = get_setting(CACHE_KEY_LAST_CHECK)
    dismissed = get_setting(CACHE_KEY_DISMISSED_VERSION)

    if not cached_version:
        return {
            'success': True,
            'checked': False,
            'current_version': current_version
        }

    update_available = _compare_versions(current_version, cached_version) < 0
    show_notification = update_available and dismissed != cached_version

    last_check_time = None
    if last_check:
        try:
            last_check_time = datetime.fromtimestamp(float(last_check)).isoformat()
        except (ValueError, TypeError):
            pass

    return {
        'success': True,
        'checked': True,
        'update_available': update_available,
        'show_notification': show_notification,
        'current_version': current_version,
        'latest_version': cached_version,
        'release_url': get_setting(CACHE_KEY_RELEASE_URL) or '',
        'release_notes': get_setting(CACHE_KEY_RELEASE_NOTES) or '',
        'dismissed_version': dismissed,
        'last_check': last_check_time
    }


def dismiss_update(version: str) -> dict[str, Any]:
    """
    Dismiss update notification for a specific version.

    Args:
        version: The version to dismiss

    Returns:
        Status dict
    """
    set_setting(CACHE_KEY_DISMISSED_VERSION, version)
    return {
        'success': True,
        'dismissed_version': version
    }


def _is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--is-inside-work-tree'],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return result.returncode == 0 and result.stdout.strip() == 'true'
    except Exception:
        return False


def _get_git_status() -> dict[str, Any]:
    """Get git repository status."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        # Check for uncommitted changes
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root
        )

        has_changes = bool(result.stdout.strip())
        changed_files = result.stdout.strip().split('\n') if has_changes else []

        # Get current branch
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_root
        )
        current_branch = branch_result.stdout.strip() or 'main'

        return {
            'has_changes': has_changes,
            'changed_files': [f for f in changed_files if f],
            'current_branch': current_branch
        }
    except Exception as e:
        logger.warning(f"Error getting git status: {e}")
        return {
            'has_changes': False,
            'changed_files': [],
            'current_branch': 'unknown',
            'error': str(e)
        }


def perform_update(stash_changes: bool = False) -> dict[str, Any]:
    """
    Perform a git pull to update the application.

    Args:
        stash_changes: If True, stash local changes before pulling

    Returns:
        Dict with update result information
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check if this is a git repo
    if not _is_git_repo():
        return {
            'success': False,
            'error': 'Not a git repository',
            'manual_update': True,
            'message': 'This installation is not using git. Please update manually by downloading the latest release from GitHub.'
        }

    git_status = _get_git_status()

    # Check for local changes
    if git_status['has_changes'] and not stash_changes:
        return {
            'success': False,
            'error': 'local_changes',
            'message': 'You have uncommitted local changes. Either commit them, discard them, or enable "stash changes" to temporarily save them.',
            'changed_files': git_status['changed_files']
        }

    try:
        # Stash changes if requested
        stashed = False
        if stash_changes and git_status['has_changes']:
            stash_result = subprocess.run(
                ['git', 'stash', 'push', '-m', 'INTERCEPT auto-stash before update'],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_root
            )
            if stash_result.returncode == 0:
                stashed = True
                logger.info("Stashed local changes before update")
            else:
                return {
                    'success': False,
                    'error': 'Failed to stash changes',
                    'details': stash_result.stderr
                }

        # Get current requirements.txt hash to detect changes
        req_path = os.path.join(repo_root, 'requirements.txt')
        req_hash_before = None
        if os.path.exists(req_path):
            with open(req_path, 'rb') as f:
                import hashlib
                req_hash_before = hashlib.md5(f.read()).hexdigest()

        # Fetch latest changes
        fetch_result = subprocess.run(
            ['git', 'fetch', 'origin'],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root
        )

        if fetch_result.returncode != 0:
            # Restore stash if we stashed
            if stashed:
                subprocess.run(['git', 'stash', 'pop'], cwd=repo_root, timeout=30)
            return {
                'success': False,
                'error': 'Failed to fetch updates',
                'details': fetch_result.stderr
            }

        # Get the main branch name
        branch = git_status.get('current_branch', 'main')

        # Pull changes
        pull_result = subprocess.run(
            ['git', 'pull', 'origin', branch],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=repo_root
        )

        if pull_result.returncode != 0:
            # Check for merge conflict
            if 'CONFLICT' in pull_result.stdout or 'CONFLICT' in pull_result.stderr:
                # Abort merge
                subprocess.run(['git', 'merge', '--abort'], cwd=repo_root, timeout=30)
                # Restore stash if we stashed
                if stashed:
                    subprocess.run(['git', 'stash', 'pop'], cwd=repo_root, timeout=30)
                return {
                    'success': False,
                    'error': 'merge_conflict',
                    'message': 'Merge conflict detected. The update was aborted. Please resolve conflicts manually or reset to a clean state.',
                    'details': pull_result.stdout + pull_result.stderr
                }

            # Restore stash if we stashed
            if stashed:
                subprocess.run(['git', 'stash', 'pop'], cwd=repo_root, timeout=30)
            return {
                'success': False,
                'error': 'Failed to pull updates',
                'details': pull_result.stderr
            }

        # Restore stashed changes
        if stashed:
            stash_pop_result = subprocess.run(
                ['git', 'stash', 'pop'],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_root
            )
            if stash_pop_result.returncode != 0:
                logger.warning(f"Failed to restore stashed changes: {stash_pop_result.stderr}")

        # Check if requirements changed
        requirements_changed = False
        if req_hash_before and os.path.exists(req_path):
            with open(req_path, 'rb') as f:
                import hashlib
                req_hash_after = hashlib.md5(f.read()).hexdigest()
                requirements_changed = req_hash_before != req_hash_after

        # Determine if update actually happened
        if 'Already up to date' in pull_result.stdout:
            return {
                'success': True,
                'updated': False,
                'message': 'Already up to date',
                'stashed': stashed
            }

        # Clear update cache to reflect new version
        set_setting(CACHE_KEY_LAST_CHECK, '')
        set_setting(CACHE_KEY_LATEST_VERSION, '')

        return {
            'success': True,
            'updated': True,
            'message': 'Update successful! Please restart the application.',
            'requirements_changed': requirements_changed,
            'stashed': stashed,
            'stash_restored': stashed,
            'output': pull_result.stdout
        }

    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Operation timed out',
            'message': 'The update operation timed out. Please check your network connection and try again.'
        }
    except Exception as e:
        logger.error(f"Update error: {e}")
        return {
            'success': False,
            'error': str(e)
        }
