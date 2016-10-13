from collections import OrderedDict, defaultdict
from getpass import getpass
from itertools import groupby
import csv
import datetime
import operator
import os
import re
import tempfile

from argparse import ArgumentParser
from github3 import authorize, login, GitHubError
from prettytable import PrettyTable
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETTING_FILE = os.path.join(BASE_DIR, 'settings.yaml')
GH_TOKEN_FILE = os.path.join(BASE_DIR, '.ghtoken')


def get_parsed_args(args=None):
    parser = ArgumentParser(
        description="Fetch pull requests stats from GitHub. "
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
    parser.add_argument("--token", type=str, help="Access token to Github.")
    parser.add_argument("--users", nargs='+',
                        help="GitHub usernames for lookup for example: "
                        "./statkube.py -a --users gitfred pigmej nhlfr")

    # FIXME: should be mutually exclusive with 'last'
    parser.add_argument("--from-date", type=str,
                        help="Created FROM date, format: YYYY-MM-DD")
    parser.add_argument("--to-date", type=str,
                        help="Created TO date, format: YYYY-MM-DD")
    parser.add_argument("-l", "--last", type=str, choices=[
        'day', 'week', 'month'])
    parser.add_argument("-g", "--group", type=str, help="The group of users "
                        "must be defined first in 'settings.yaml' as "
                        "must be defined first in 'settings.yaml' as "
                        "'STATKUBE_GROUP_<custom_name>'. "
                        "Then pass <custom_name> as an argument here.")
    parser.add_argument("-r", "--date-range", type=str, help="Date range "
                        "previously defined in settings.yaml")
    parser.add_argument("-q", "--query-extra", type=str, help="This will be "
                        "added to GH query. As a reference please s ee GitHub "
                        "search API. Env var: STATKUBE_QUERY_EXTRA")
    parser.add_argument("--show-default-settings", action='store_true',
                        help="Shows the localization of default settings file "
                        "which can be copied and changed. Use then "
                        "STATKUBE_SETTINGS_FILE env var.")
    parser.add_argument("--show-token-path", action='store_true',
                        help="Shows the localization of GH token file.")

    parsed = parser.parse_args(args=args)

    return parsed


class GithubWrapper(object):
    DATA_MAPPING = OrderedDict((
        ('username', operator.attrgetter('user.login')),
        ('id', operator.attrgetter('number')),
        ('title', operator.attrgetter('title')),
        ('state', operator.attrgetter('state')),
        ('comments', operator.attrgetter('comments')),
        ('url', operator.attrgetter('html_url')),
        ('labels', lambda pr: ', '.join(l.name for l in pr.labels)),
    ))
    DEFAULT_SORTBY = 'username'
    STATKUBE_GROUP_REGEXP = re.compile(r"STATKUBE_GROUP_(?P<name>\w+)")

    def __init__(self, args, settings=None, repo=None):
        self.general_info = None  # used for memo of general sum
        self.stats = None  # used for memo of general sum
        self.args = args
        self.settings = settings or self.get_settings()
        self.repo = repo

        if self.args.username:
            self.settings['STATKUBE_USERNAME'] = self.args.username

        if self.args.password:
            self.settings['STATKUBE_PASSWORD'] = self.args.password

        if self.args.token:
            self.settings['STATKUBE_ACCESS_TOKEN'] = self.args.token

        if self.args.ask_for_password:
            self.settings['STATKUBE_PASSWORD'] = getpass(
                "GitHub Password for {}: ".format(
                    self.settings['STATKUBE_USERNAME']))

        if self.args.users:
            self.settings['STATKUBE_USERS'] = self.args.users

        if self.args.query_extra:
            self.settings['STATKUBE_QUERY_EXTRA'] = self.args.query_extra

        if self.args.group:
            user_groups = {k: v for k, v in self.settings.items()
                           if self.STATKUBE_GROUP_REGEXP.search(k)}

            key = "STATKUBE_GROUP_{}".format(self.args.group)
            if key not in user_groups:
                raise ValueError(
                    "So such group defined '{}'. Defined groups: {}".format(
                        key, ', '.join(user_groups)))

            self.settings['STATKUBE_USERS'] = user_groups[key]

        if self.args.date_range:
            dr = self.args.date_range
            begin, end = \
                self.settings['STATKUBE_ITERATION_RANGES'][dr].split('..')
            self.args.from_date = begin.strip()
            self.args.to_date = end.strip()

    def __str__(self):
        return "{}: {}".format(self.__class__.__name__,
                               self.settings['STATKUBE_USERNAME'])

    __repr__ = __str__

    @staticmethod
    def get_settings(yaml_path=None):
        if yaml_path is None:
            yaml_path = os.getenv(
                'STATKUBE_SETTINGS_FILE', DEFAULT_SETTING_FILE)

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

    def login(self):
        # FIXME: token is not working, still using basic auth
        token_path = os.path.join(BASE_DIR, '.ghtoken')

        if self.settings['STATKUBE_ACCESS_TOKEN']:
            gh_token = self.settings['STATKUBE_ACCESS_TOKEN']

        else:
            if not os.path.exists(token_path):
                try:
                    auth = authorize(
                        self.settings['STATKUBE_USERNAME'],
                        self.settings['STATKUBE_PASSWORD'],
                        [], 'Statkube - fetch GH stats')

                except GitHubError as err:
                    print ("ERROR authorization. Copy existing key from "
                           "https://github.com/settings/tokens or delete it."
                           "\n{}".format(err.msg))
                    return self.basic_login()

                gh_token = auth.token

                with open(token_path, 'w') as fp:
                    fp.write(gh_token + '\n')

            else:
                with open(token_path) as fp:
                    gh_token = fp.readline().strip()

        return login(token=gh_token)

    def basic_login(self):
        auth = login(
            self.settings['STATKUBE_USERNAME'],
            self.settings['STATKUBE_PASSWORD'])
        auth.user()

        return auth

    @property
    def pull_requests(self):
        try:
            return self._pull_requests
        except AttributeError:
            self._pull_requests = self._fetch_pull_requests()
            return self._pull_requests

    def _fetch_pull_requests(self, q_kwargs=None):
        query = self.build_issue_query(q_kwargs=q_kwargs)
        search_iter = self.session.search_issues(query)
        return [i.issue for i in search_iter]

    def build_issue_query(self, q_kwargs=None):
        query = self._other_details_query()
        type_ = q_kwargs.pop('__type__', 'created')

        if self.args.last:
            last = self.args.last
            if last in ('day', 'week'):
                delta = datetime.timedelta(**{last + 's': 1})
            elif last == 'month':
                delta = datetime.timedelta(weeks=4)

            dt = datetime.datetime.now() - delta
            query += dt.strftime(' created:"%Y-%m-%d .. *"')

        elif self.args.from_date or self.args.to_date:
            if type_ == 'created':
                query += self._open_in_date_range_query()
            elif type_ == 'merged':
                query += self._merged_in_date_range()
            elif type_ == 'closed':
                query += self._closed_in_date_range()

        if q_kwargs and isinstance(q_kwargs, dict):
            tmp_kwargs = ''
            for key, val in q_kwargs.items():
                tmp_kwargs += ' {}:{} '.format(key, val)

            query += tmp_kwargs

        return query

    def _open_in_date_range_query(self):
        return ' created:"{0} .. {1}" '.format(
            self.args.from_date or '*',
            self.args.to_date or '*')

    def _merged_in_date_range(self):
        return ' merged:"{} .. {}" '.format(
            self.args.from_date or '*',
            self.args.to_date or '*')

    def _closed_in_date_range(self):
        return ' closed:"{} .. {}" '.format(
            self.args.from_date or '*',
            self.args.to_date or '*')

    def _other_details_query(self, type_='pr'):
        if '/' in self.repo:
            q = 'repo'
        else:
            q = 'org'
        query = 'type:{} {}:{} '.format(type_,
                                        q,
                                        self.repo)
        query += ' '.join(
            'author:{}'.format(user)
            for user in self.settings['STATKUBE_USERS'])

        if self.settings['STATKUBE_QUERY_EXTRA']:
            query += ' {}'.format(self.settings['STATKUBE_QUERY_EXTRA'])

        return query

    def get_general_info(self):

        is_date_range = \
            self.args.from_date or self.args.to_date or self.args.last

        def key_username(x):
            return x.user.login

        stats = defaultdict(dict)
        for type_ in ('created', 'merged', 'closed'):

            if is_date_range:
                q_kwargs = {'__type__': type_}
            else:
                q_kwargs = {'is': type_}

            for username, prs in groupby(
                    sorted(self._fetch_pull_requests(q_kwargs=q_kwargs),
                           key=key_username),
                    key=key_username):

                prs = list(prs)
                stats[username][type_] = len(prs)

        user_stats = {
            k: '{} / {} / {}'.format(v.get('created', 0),
                                     v.get('merged', 0),
                                     v.get('closed', 0))
            for k, v in stats.items()
        }

        general = {
            'created': sum(stats[user].get('created', 0) for user in stats),
            'merged': sum(stats[user].get('merged', 0) for user in stats),
            'closed': sum(stats[user].get('closed', 0) for user in stats),
        }

        self.stats = stats
        self.general_info = general
        return [general], [
            {
                'username': user,
                'stats (created, merged, closed)': user_stats[user]
            } for user in user_stats]

    def get_pull_requests_data(self):
        return [
            {key: getter(pr) for key, getter in self.DATA_MAPPING.items()}
            for pr in self.pull_requests]

    def _pretty_print(self, data, header=None, **kwargs):
        if not data:
            raise ValueError("data argument is empty!")

        if header is None:
            header = data[0].keys()
        ptable = PrettyTable(header, **kwargs)
        with_sorted_header = operator.itemgetter(*header)

        for item in data:
            ptable.add_row(with_sorted_header(item))

        return ptable

    def pretty(self, type_, **kwargs):
        print "Stats for: %s" % self.repo
        if type_ == 'general':
            general, per_user = self.get_general_info()
            ckwargs = kwargs.copy()
            sortby = ckwargs.pop('sortby', None)
            print self._pretty_print(
                general, header=('created', 'merged', 'closed'), **ckwargs)
            print self._pretty_print(
                per_user,
                header=('username', 'stats (created, merged, closed)'),
                sortby=sortby, **ckwargs)
        elif type_ == 'prs':
            print self._pretty_print(self.get_pull_requests_data(), **kwargs)

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
            general, per_user = self.get_general_info()
            abs_path, filename = os.path.split(path)
            per_user_path = os.path.join(
                abs_path,
                'per_user-{}'.format(filename)
            )
            self._save_to_csv(path, general)
            self._save_to_csv(per_user_path, per_user)
        elif type_ == 'prs':
            self._save_to_csv(path, self.get_pull_requests_data())

    def run(self):
        if self.args.csv_path:
            self.csv(self.args.csv_path, self.args.type)

        if not self.args.no_pretty:
            self.pretty(self.args.type, sortby=self.args.sortby)
