#!/usr/bin/env python3
"""Bump the pinned yt-dlp nightly in requirements-ytdlp.txt.

Prints the resolved version to stdout and writes the file in place. Exits 0 whether
or not anything changed; the caller checks `git diff` to decide whether to commit.
"""
import json
import re
import sys
import urllib.request

REQUIREMENTS = 'requirements-ytdlp.txt'
PIN = re.compile(r'^yt-dlp==(?P<version>.+)$', re.MULTILINE)


def latest_nightly():
    with urllib.request.urlopen('https://pypi.org/pypi/yt-dlp/json', timeout=30) as r:
        releases = json.load(r)['releases']

    # Nightlies are published as PEP 440 dev releases; stable releases are not what we
    # want here, since they lag YouTube fixes by a median of 18 days.
    nightlies = {v: f for v, f in releases.items() if '.dev' in v and f}
    if not nightlies:
        sys.exit('No nightly (.dev) releases found on PyPI - refusing to guess')

    # Sort by upload time rather than parsing versions, so no packaging dependency is
    # needed and a malformed version string can't silently win
    return max(nightlies, key=lambda v: min(f['upload_time_iso_8601'] for f in nightlies[v]))


def main():
    content = open(REQUIREMENTS).read()
    match = PIN.search(content)
    if not match:
        sys.exit(f'No "yt-dlp==" pin found in {REQUIREMENTS}')

    current, newest = match.group('version'), latest_nightly()
    print(f'current={current} latest={newest}')

    if current == newest:
        print('Already up to date')
        return

    open(REQUIREMENTS, 'w').write(PIN.sub(f'yt-dlp=={newest}', content, count=1))
    print(f'Bumped to {newest}')


if __name__ == '__main__':
    main()
