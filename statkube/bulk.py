import operator

from collections import defaultdict

from prettytable import PrettyTable
from statkube.wrapper import GithubWrapper


def dsum(*dicts):
    ret = defaultdict(int)
    for d in dicts:
        for k, v in d.items():
            ret[k] += v
    return dict(ret)


class Bulk(object):

    def __init__(self, parsed, repos):
        self.repos = repos
        self.parsed = parsed

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

    def pretty(self, general, per_user):
        print "Bulk"
        print self._pretty_print(
            general, header=('created', 'merged', 'closed'))
        print self._pretty_print(
            per_user,
            header=('username', 'stats (created, merged, closed)'),
            sortby=None)

    def run(self):
        data_general = []
        data_user = []
        for repo in self.repos:
            ghw = GithubWrapper(self.parsed, repo=repo)
            ghw.run()
            data_general.append(ghw.general_info)
            data_user.append(ghw.stats)
        general = [self.sum_general(data_general)]
        user = self.sum_user(data_user)
        self.pretty(general, user)

    def sum_general(self, data):
        return dsum(*data)

    def sum_user(self, data):
        d = defaultdict(list)
        for stats in data:
            for user, user_stats in stats.iteritems():
                d[user].append(user_stats)
        for user, stats in d.iteritems():
            d[user] = dsum(*stats)
        data = [
            {
                'username': user,
                'stats (created, merged, closed)': '{} / {} / {}'.format(d[user].get('created', 0),
                                                                        d[user].get('merged', 0),
                                                                        d[user].get('closed', 0))
            } for user in d]
        return data
