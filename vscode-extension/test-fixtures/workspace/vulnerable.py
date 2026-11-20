import hashlib
import os
import random

import yaml

AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"


def run(command):
    os.system("echo " + command)


def load(text):
    return yaml.load(text)


def token():
    return hashlib.md5(str(random.random()).encode()).hexdigest()
