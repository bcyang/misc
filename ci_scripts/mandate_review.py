import os
import re
import subprocess
from collections import defaultdict
from fnmatch import fnmatch

import requests

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    print('GITHUB_TOKEN environment variable is not set')
    exit(1)

headers = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
}
url_prefix = 'https://api.github.com/repos/bcyang/misc'


def parse_codeowners():
    codeowners = defaultdict(set)  # glob_path -> owners
    with open('.github/CODEOWNERS') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            path = parts[0]
            owners = parts[1:]
            codeowners[path] = [o[1:] for o in owners]  # get rid of the '@' prefix
    return codeowners


def os_exec(cmd) -> list:
    return [o.strip() for o in subprocess.check_output(cmd.split()).decode('utf8').strip().split('\n') if o]


def get_changed_files():
    output = os_exec('git describe --tags --abbrev=0 HEAD^')
    if not output:
        return []
    lasttag = output[0]
    return os_exec(f'git diff --name-only {lasttag}')


def get_pr_number():
    output = os_exec('git shortlog -1')
    if not output:
        return None
    branch = output[0]
    if not branch.startswith('pr/'):
        return None
    return branch[3:]


def get_approvers_by_pr(pr_number):
    if not pr_number:
        return []
    url = f'{url_prefix}/pulls/{pr_number}/reviews'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    reviews = r.json()
    approvers = set()
    for review in reviews:
        if review['state'] != 'APPROVED':
            continue
        approvers.add(review['user']['login'])
    return approvers


def get_commit_info():
    """ returns committer_github_login and title"""
    rev, title = os_exec('git log -1 --pretty=%H%n%s')
    url = f'{url_prefix}/commits/{rev}'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None, None

    commit = r.json()
    committer_github_login = commit['author']['login']
    return committer_github_login, title


def title2pr(title):
    """ title2pr('fixing XXXX-1234 (#4529)') => '4529' """
    matched = re.compile('.*\(#([0-9]+)\)$').match(title)
    return matched.group(1) if matched else None


if __name__ == '__main__':
    committer_github_login, title = get_commit_info()
    # figure out PR number from the commit title
    # if it's not found, it will have no approver, i.e. only owner can merge to this branch
    pr_number = title2pr(title)
    approvers = get_approvers_by_pr(pr_number)
    codeowners = parse_codeowners()
    not_approved = False
    for file in get_changed_files():
        for code_path_pattern, owners in codeowners.items():
            if not fnmatch('/' + file, code_path_pattern):
                # doesn't require approval
                continue
            if committer_github_login in owners or committer_github_login in approvers:
                # committer is owner or already approved
                continue
            print(f'ERROR: {file} requires approval from {owners}')
            not_approved = True
    if not_approved:
        # failing the build
        exit(1)
