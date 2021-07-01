FROM python:3.9.6 as base

WORKDIR /usr/local/app
ENV PYTHONPATH /usr/local/app

RUN pip3 install pipenv && pipenv --python $(which python3)

ADD Pipfile Pipfile.lock ./
RUN pipenv install --deploy --system

FROM base as test

RUN pipenv install --dev --system

ADD . .
RUN py.test -n=auto --cov=slack_prs --cov-report=term-missing
RUN flake8 --max-complexity=4

FROM base
ADD . .
ENTRYPOINT [ "python", "-m", "slack_prs" ]
