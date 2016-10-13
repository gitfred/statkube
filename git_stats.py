# ugly ugly ugly

import os
import git
import yaml
import re
import github3
import csv
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


DEFAULT_SETTING_FILE = os.path.join(BASE_DIR, 'settings.yaml')
yaml_path = os.getenv(
    'STATKUBE_SETTINGS_FILE', DEFAULT_SETTING_FILE)

yaml_data = yaml.load(open(yaml_path))
STATKUBE_USERS = yaml_data['STATKUBE_USERS']
GH_TOKEN = yaml_data['STATKUBE_ACCESS_TOKEN']
users_re = re.compile("^.*({}).*$".format('|'.join(STATKUBE_USERS)), re.I)
prs_numb = re.compile('^.*Merge pull request #(\d+).*$')



def log(path, branch):
    r = git.Git(path)
    logs = r.log('--oneline', '-b', branch).split('\n')
    return logs


l1 = set(log('/home/pigmej/mirantis/kubernetes_mir', '1.4-mcp'))
l2 = set(log('/home/pigmej/mirantis/kubernetes/src/k8s.io/kubernetes', 'release-1.3'))


prs = []

for x in (l1 - l2):
    if users_re.match(x):
        try:
            prs.append((prs_numb.search(x).groups()[0], x))
        except Exception:
            pass

github = github3.login(token=GH_TOKEN)

prs_full = []

for pr_num, pr in prs:
    gh_issue = github.issue("kubernetes", "kubernetes", pr_num)
    prs_full.append({'title': gh_issue.title,
                     # 'body': gh_issue.body_text,
                     'labels': '|'.join((x.name for x in gh_issue.labels())),
                     'url': gh_issue.url,
                     'number': gh_issue.number,
                     'user': gh_issue.user})
    sys.stdout.write('.')
    sys.stdout.flush()


with open('/tmp/prs.csv', 'wb') as f:
    writter = csv.DictWriter(f, prs_full[0].keys())
    writter.writeheader()
    for row in prs_full:
        writter.writerow(dict((k, str(v).encode('utf-8')) for k, v in row.iteritems()))

