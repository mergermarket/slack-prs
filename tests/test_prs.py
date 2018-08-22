import unittest
from datetime import datetime, timedelta
from collections import namedtuple
from unittest.mock import patch, Mock, MagicMock

import slack_prs


class TestArgs(unittest.TestCase):

    @patch('slack_prs.App')
    def test_args(self, App):

        # Given
        org = 'test-org'
        channel = 'test-channel'
        github_token = 'test-github-token'
        slack_token = 'test-slack-token'

        # When
        slack_prs.main([
            '--org', org,
            '--channel', channel,
            '--team-prefix', 'Pref1',
            '--team-prefix', 'Pref2',
            '--exclude-team', 'Team1',
            '--exclude-team', 'Team2',
        ], github_token, slack_token)

        # Then
        App.assert_called_once_with(
            org, channel, github_token, slack_token,
            ['Pref1', 'Pref2'], ['Team1', 'Team2'],
        )


Issue = namedtuple('Issue', 'repository id created_at html_url title user')


User = namedtuple('User', 'login')


Team = namedtuple('Team', 'name permission')


def repo(name, teams):
    repo = Mock()
    repo.name = name
    repo.get_teams.return_value = teams
    return repo


class TestReport(unittest.TestCase):

    @patch('slack_prs.SlackClient')
    @patch('slack_prs.datetime')
    @patch('slack_prs.Github')
    @patch('slack_prs.SlackWrapper')
    def test_report(self, SlackWrapper, Github, mock_datetime, _):

        # Given
        org = 'test-org'
        channel = 'test-channel'
        github_token = 'test-github-token'
        slack_token = 'test-slack-token'
        github = Mock()
        Github.return_value = github
        github_org = Mock()
        github.get_organization.return_value = github_org
        team1 = Team(name='team1', permission='admin')
        team2 = Team(name='team2', permission='admin')
        repo1 = repo(name='repo1', teams=[team1])
        repo2 = repo(name='repo2', teams=[team2])
        repo3 = repo(name='repo3', teams=[team2])
        now = datetime(2018, 1, 1)
        mock_datetime.now.return_value = now
        github_org.get_teams.return_value = [team1, team2]
        search_results = [
            Issue(
                repository=repo1,
                id='123',
                created_at=now - timedelta(days=365 + 20),
                html_url='https://link1',
                title='pr-1',
                user=User(login='test-user-1')
            ),
            Issue(
                repository=repo2,
                id='321',
                created_at=now - timedelta(days=2 * 365),
                html_url='https://link2',
                title='pr-2',
                user=User(login='test-user-2')
            ),
            Issue(
                repository=repo3,
                id='231',
                created_at=now - timedelta(days=4 * 365 + 20),
                html_url='https://link2',
                title='pr-3',
                user=User(login='test-user-2')
            )
        ]
        search_results_return_value = MagicMock()
        search_results_return_value.totalCount = len(search_results)
        search_results_return_value.__iter__.return_value = search_results
        github.search_issues.return_value = search_results_return_value
        slack = Mock()
        SlackWrapper.return_value = slack
        slack.list_channels.return_value = {
            'channels': [
                {'name': 'decoy1', 'id': 'not this'},
                {'name': channel, 'id': 'this'},
                {'name': 'decoy2', 'id': 'nor this'},
            ]
        }
        app = slack_prs.App(org, channel, github_token, slack_token, [], [])

        # When
        app.run()

        # Then
        github.search_issues.assert_called_once_with(
            '', sort='created', order='asc', **{
                'org': org,
                'archived': 'false',
                'is': 'open',
                'type': 'pr',
            }
        )
        slack.post_message.assert_called_once_with(
            channel='this',
            text='Pull requests by team:```'
            'Team    PRs   Total open duration\n'
            '=================================\n'
            'team1    1      1 year 20 days   \n'
            'team2    2      6 years 20 days  \n'
            '```'
        )
        slack.upload.assert_called_once_with(
            channels='this',
            file='team1\n'
                 '    * https://link1 - pr-1 (test-user-1, 1 year 20 days)\n'
                 '\n'
                 'team2\n'
                 '    * https://link2 - pr-2 (test-user-2, 2 years)\n'
                 '    * https://link2 - pr-3 (test-user-2, 4 years 20 days)\n',
            filename='prs-breakdown-2018-01-01.txt',
            filetype='text',
            title='Pull requests by team breakdown'
        )
