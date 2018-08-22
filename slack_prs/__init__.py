import logging
import argparse
from datetime import timedelta, datetime
from github import Github
from texttable import Texttable
from slackclient import SlackClient


def sum_durations(durations):
    durations = list(durations)
    result = durations[0]
    for duration in durations[1:]:
        result += duration
    return result


def format_timedelta(d):
    years = int(d.days / 365)
    days = d.days % 365
    parts = []
    if years > 0:
        parts.append(f'{years} year{"s" if years > 1 else ""}')
    if days > 0:
        parts.append(f'{days} day{"s" if days > 1 else ""}')
    if len(parts) == 0:
        return '0'
    return ' '.join(parts)


class SlackWrapper:
    def __init__(self, slack):
        self.slack = slack

    def post_message(self, **kwargs):
        return self.slack.api_call("chat.postMessage", **kwargs)

    def upload(self, **kwargs):
        return self.slack.api_call("files.upload", **kwargs)

    def list_channels(self, **kwargs):
        return self.slack.api_call("channels.list", **kwargs)


class App:
    def __init__(
        self, org_name, channel_name, github_token, slack_token,
        team_prefixes, exclude_teams
    ):
        self.github_token = github_token
        self.github = Github(github_token)
        self.org = self.github.get_organization(org_name)
        self.slack = SlackWrapper(SlackClient(slack_token))
        self.channel_name = channel_name
        self.team_prefixes = team_prefixes
        self.exclude_teams = exclude_teams
        self.now = datetime.now()
        # don't use self.org.name, since that is "Acuris"
        self.org_name = org_name
        self.logger = logging.getLogger('prbot')
        self.repos = {}
        self.team_repos = {}
        self.repo_owners = {}
        self.team_prs = {}
        self.repo_prs = {}
        self.pr_durations = {}
        self.repo_durations = {}
        self.team_durations = {}
        self.team_counts = {}

    def run(self):
        channel_id = self.get_channel_id(self.channel_name)
        self.fetch_teams()
        for i, pr in enumerate(self.prs()):
            self.add_repo(pr.repository)
            self.add_pr(pr)
            if i != 0 and (i % 10) == 0:
                self.logger.info(f'Processed {i} PRs.')
        self.populate_team_durations_and_counts()
        self.populate_repo_durations()
        self.logger.info('Data collected, sending reports to slack...')
        self.slack.post_message(
            channel=channel_id,
            text=f'Pull requests by team:```{self.league_table()}```'
        )
        team_reports = ''
        team_reports = [
            self.team_report(team)
            for team
            in sorted(self.team_prs.keys())
        ]
        self.slack.upload(
            channels=channel_id,
            file='\n'.join(team_reports),
            filetype='text',
            filename='prs-breakdown-{}.txt'.format(
                self.now.strftime('%Y-%m-%d')
            ),
            title="Pull requests by team breakdown"
        )
        self.logger.info('Complete.')

    def fetch_teams(self):
        self.logger.info('Fetching teams...')
        self.teams = {
            team.name: team for team in self.org.get_teams()
            if self.include_team(team.name)
        }
        self.logger.info(f'Found {len(self.teams)} teams.')

    def include_team(self, team):
        return self.team_prefixes_match(team) and not self.team_excluded(team)

    def team_prefixes_match(self, team_name):
        if self.team_prefixes is None or len(self.team_prefixes) == 0:
            return True
        matching_prefixes = {
            prefix for prefix in self.team_prefixes
            if team_name.startswith(prefix)
        }
        return len(matching_prefixes) > 0

    def team_excluded(self, team_name):
        if self.exclude_teams is None or len(self.exclude_teams) == 0:
            return False
        return team_name in self.exclude_teams

    def prs(self):
        self.logger.info('Starting search...')
        results = self.github.search_issues(
            '', sort='created', order='asc', **{
                'org': self.org_name,
                'archived': 'false',
                'is': 'open',
                'type': 'pr',
            }
        )
        self.logger.info(f'Processing {results.totalCount} PRs...')
        return results

    def add_repo(self, repo):
        if self.repos.get(repo.name) is not None:
            return
        self.repos[repo.name] = repo
        # there should be a single owner, but repos may be mid-transition,
        # so report PR to both teams
        self.repo_owners[repo.name] = self.get_owner_teams(repo)
        for team_name in self.repo_owners[repo.name]:
            if self.team_repos.get(team_name) is None:
                self.team_repos[team_name] = [repo]
            else:
                self.team_repos[team_name].append(repo)

    def get_owner_teams(self, repo):
        return [
            team.name for team in repo.get_teams()
            if team.permission == 'admin'
        ]

    def add_pr(self, pr):
        repo_name = pr.repository.name

        for team_name in self.repo_owners[repo_name]:
            if self.team_prs.get(team_name) is None:
                self.team_prs[team_name] = [pr]
            else:
                self.team_prs[team_name].append(pr)

        if self.repo_prs.get(repo_name) is None:
            self.repo_prs[repo_name] = [pr]
        else:
            self.repo_prs[repo_name].append(pr)

        self.pr_durations[pr.id] = self.now - pr.created_at

    def populate_team_durations_and_counts(self):
        for team_name in self.team_repos.keys():
            self.team_durations[team_name] = sum_durations(
                sum_durations(
                    self.pr_durations[pr.id] for pr in self.repo_prs[repo.name]
                )
                for repo in self.team_repos[team_name]
            )
            self.team_counts[team_name] = sum(
                len(self.repo_prs[repo.name])
                for repo in self.team_repos[team_name]
            )

    def populate_repo_durations(self):
        for repo_name in self.repos.keys():
            self.repo_durations[repo_name] = sum_durations(
                self.pr_durations[pr.id] for pr in self.repo_prs[repo_name]
            )

    def get_channel_id(self, name):
        self.logger.info('Finding channel...')
        channels = self.slack.list_channels(
            exclude_archived=1
        )['channels']
        for channel in channels:
            if channel['name'] == name:
                self.logger.info('Found channel.')
                return channel['id']
        raise Exception(f'no channel with name {name} found')

    def league_table(self):
        table = Texttable()
        table.set_deco(Texttable.HEADER)
        table.set_cols_align(['l', 'c', 'c'])
        table.header(['Team', 'PRs', 'Total open duration'])
        zero_duration = timedelta(0)
        teams = sorted(
            self.teams.keys(),
            key=lambda team: self.team_durations.get(team, zero_duration)
        )
        for team in teams:
            table.add_row([
                team,
                self.team_counts.get(team, 0),
                format_timedelta(self.team_durations.get(team, zero_duration))
            ])
        return table.draw() + '\n'

    def team_report(self, team_name):
        report = f'{team_name}\n'
        prs = self.team_prs[team_name]
        for pr in prs:
            report += '    * {} - {} ({}, {})\n'.format(
                pr.html_url, pr.title, pr.user.login,
                format_timedelta(self.pr_durations[pr.id])
            )
        return report


def main(args, github_token, slack_bot_token):
    logging.basicConfig(level=logging.INFO)

    argument_parser = argparse.ArgumentParser('slack_prs')
    argument_parser.add_argument('--org', required=True)
    argument_parser.add_argument('--channel', required=True)
    argument_parser.add_argument(
        '--team-prefix', action='append', required=False
    )
    argument_parser.add_argument(
        '--exclude-team', action='append', required=False
    )

    arguments = argument_parser.parse_args(args)

    app = App(
        arguments.org,
        arguments.channel,
        github_token,
        slack_bot_token,
        arguments.team_prefix,
        arguments.exclude_team,
    )
    app.run()
