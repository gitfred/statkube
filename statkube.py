#! /usr/bin/env python
from getpass import getpass
from itertools import groupby
import csv
import operator
import os
import tempfile

from argparse import ArgumentParser
from github3 import login
from prettytable import PrettyTable
import yaml


def get_parsed_args():
    parser = ArgumentParser(
        description="Fetch pull requests stats from GitHub."
                    "Place your settings in settings.yaml or setup custom "
                    "path by settings env: STATKUBE_SETTINGS_FILE.")
    parser.add_argument("-n", "--no-pretty", action="store_true")
    parser.add_argument("-c", "--csv-path", type=str)
    parser.add_argument("-s", "--sortby", type=str,
                        default=GithubWrapper.DEFAULT_SORTBY,
                        choices=GithubWrapper.DATA_MAPPING)
    parser.add_argument("-t", "--type", type=str, default='general',
                        choices=['general', 'prs'])
    parser.add_argument("-u", "--username", type=str,
                        help="Github Username use to login")
    parser.add_argument("-p", "--password", type=str,
                        help="Github password use to login")
    parser.add_argument("-a", "--ask-for-password", action='store_true',
                        help="Force ask for password")

    args = parser.parse_args()

    return args


class GithubWrapper(object):
    DATA_MAPPING = {
        'id': operator.attrgetter('number'),
        'username': operator.attrgetter('user.login'),
        'title': operator.attrgetter('title'),
        'state': operator.attrgetter('state'),
        'comments': operator.attrgetter('comments'),
        'url': operator.attrgetter('html_url'),
        'labels': lambda pr: ', '.join(l.name for l in pr.labels),
    }
    DEFAULT_SORTBY = 'username'

    def __init__(self, args):
        self.settings = self.get_settings()
        self.args = args
        if self.args.username:
            self.settings['STATKUBE_USERNAME'] = self.args.username
        if self.args.password:
            self.settings['STATKUBE_PASSWORD'] = self.args.password
        if self.args.ask_for_password:
            self.settings['STATKUBE_PASSWORD'] = getpass(
                "GitHub Password for {}: ".format(
                    self.settings['STATKUBE_USERNAME']))

    def __str__(self):
        return "{}: {}".format(self.__class__.__name__,
                               self.settings['STATKUBE_USERNAME'])

    __repr__ = __str__

    @staticmethod
    def get_settings(yaml_path=None):
        if yaml_path is None:
            yaml_path = os.getenv(
                'STATKUBE_SETTINGS_FILE',
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'settings.yaml')
            )

        with open(yaml_path) as fp:
            settings = yaml.load(fp)

        for key in settings:
            env = os.getenv(key)
            if env:
                settings[key] = env

        return settings

    @property
    def session(self):
        try:
            return self._session
        except AttributeError:
            self._session = self.login()
            return self._session

    @property
    def pull_requests(self):
        try:
            return self._pull_requests
        except AttributeError:
            self._pull_requests = self._fetch_pull_requests()
            return self._pull_requests

    def _fetch_pull_requests(self):
        query = self._build_issue_query()
        search_iter = self.session.search_issues(query)
        return [i.issue for i in search_iter]

    def login(self, method='basic'):
        if method == 'basic':
            gh = login(
                self.settings['STATKUBE_USERNAME'],
                password=self.settings['STATKUBE_PASSWORD'])
            # to raise possible http errors
            gh.user()
            return gh

    def _build_issue_query(self, type_='pr'):
        query = 'type:{} repo:{} '.format(type_,
                                          self.settings['STATKUBE_REPO'])
        query += ' '.join(
            'author:{}'.format(user)
            for user in self.settings['STATKUBE_USERS'])

        return query

    def get_general_info(self):

        def key_username(x):
            return x.user.login

        ret = []
        for username, prs in groupby(
                sorted(self.pull_requests, key=key_username),
                key=key_username):

            prs = list(prs)
            ret.append({
                'username': username,
                'open': len(filter(lambda x: x.state == 'open', prs)),
                'closed': len(filter(lambda x: x.state == 'closed', prs)),
            })

        return ret

    def get_pull_requests_data(self):
        return [
            {key: getter(pr) for key, getter in self.DATA_MAPPING.items()}
            for pr in self.pull_requests]

    def _pretty_print(self, data, **kwargs):
        if not data:
            raise ValueError("data argument is empty!")

        header = data[0].keys()
        ptable = PrettyTable(header, **kwargs)
        with_sorted_header = operator.itemgetter(*header)

        for item in data:
            ptable.add_row(with_sorted_header(item))

        return ptable

    def pretty(self, type_, **kwargs):
        if type_ == 'general':
            return self._pretty_print(self.get_general_info(), **kwargs)
        elif type_ == 'prs':
            return self._pretty_print(self.get_pull_requests_data(), **kwargs)

    def _save_to_csv(self, path, data):
        if not data:
            raise ValueError("data argument is empty!")

        def encode_utf_8(st):
            try:
                return st.encode('utf-8')
            except AttributeError:
                return st

        header = data[0].keys()

        with open(path, 'wb') as fp:
            writer = csv.DictWriter(fp, fieldnames=header)
            writer.writeheader()
            for row in data:
                writer.writerow(
                    {encode_utf_8(k): encode_utf_8(v)
                     for k, v in row.items()}
                )

        print "Data has been saved to {}".format(os.path.abspath(path))

    def csv(self, path=None, type_='general'):
        if path is None:
            path = tempfile.mktemp(suffix='.csv')

        if type_ == 'general':
            return self._save_to_csv(path, self.get_general_info())
        elif type_ == 'prs':
            return self._save_to_csv(path, self.get_pull_requests_data())

    def run(self):
        if self.args.csv_path:
            self.csv(self.args.csv_path, self.args.type)

        if self.args.no_pretty:
            return

        print self.pretty(self.args.type, sortby=self.args.sortby)


if __name__ == '__main__':
    args = get_parsed_args()
    GithubWrapper(args).run()
