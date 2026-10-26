"""Validate the requested version and restrict real publication to private, tagged source."""

import ast
import os
from pathlib import Path
import tomllib


root = Path(__file__).resolve().parents[1]
project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
requested = os.environ['RELEASE_VERSION']
assert requested == project['version'], 'Requested version differs from pyproject.toml'
tree = ast.parse((root / 'edu_host/__init__.py').read_text())
versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets)]
assert versions == [requested], 'SDK __version__ differs from project version'
if os.environ.get('PUBLISH') == 'true':
    assert os.environ.get('GITHUB_REF_TYPE') == 'tag', 'Publish from a version tag'
    assert os.environ.get('GITHUB_REF_NAME') == 'v' + requested, 'Tag must be v<version>'
    assert os.environ.get('SDK_REPOSITORY_PRIVATE') == 'true', 'Make SDK source repository private first'
print('Release preflight passed:', requested)
