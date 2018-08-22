import os
import sys

from . import main

main(sys.argv[1:], os.environ['GITHUB_TOKEN'], os.environ['SLACK_BOT_TOKEN'])
