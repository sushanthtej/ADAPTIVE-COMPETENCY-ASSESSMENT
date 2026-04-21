#!/usr/bin/env bash

export PYTHON_VERSION=3.10.13

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate