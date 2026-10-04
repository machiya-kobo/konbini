"""Release version: app/version.py holds `VERSION = "X.Y.Z"` (release tooling reads that line), app/CHANGELOG.md has a
section for it, and the running board reports it on /api/status and in Settings -> About."""
import os, re, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
src = open(os.path.join(ROOT, "app", "version.py")).read()
m = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"$', src, re.M)
assert m, "app/version.py needs a line: VERSION = \"X.Y.Z\""
version = m.group(1)
assert re.search(r"^## %s$" % re.escape(version), open(os.path.join(ROOT, "app", "CHANGELOG.md")).read(), re.M), "app/CHANGELOG.md has no section for %s" % version
sys.path.insert(0, os.path.join(ROOT, "app"))
import version as v, modern
assert v.VERSION == version
assert "<b>%s</b>" % version in "".join(modern.shell.about_section("konbini", version, "", "v0")[1]) or version in str(modern.shell.about_section("konbini", version, "", "v0")), "About does not show the version"
print("version tests: all passed")
