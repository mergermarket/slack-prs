Get open PRs for your Github org and send to Slack

Counts PRs and totals PR durations by Github team. Sends a league table and
breakdown of PRs by team to a specified Slack channel.

Usage
-----

    read -s -p 'github token? ' GITHUB_TOKEN
    read -s -p 'slack token? ' SLACK_BOTS_TOKEN
    docker run -i --rm -e GITHUB_TOKEN -e SLACK_BOTS_TOKEN \
        mergermarket/slack-prs \
        --org my-github-org \
        --channel my-slack-channel

Optionally takes one or more `--team-prefix` and `--exclude-team` arguments to
restrict the included teams.
