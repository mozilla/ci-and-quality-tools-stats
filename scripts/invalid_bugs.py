from bugbug import bug_features, bugzilla
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

params = {
    "f1": "longdesc",
    "o1": "casesubstring",
    "v1": "bot thinks this bug is invalid.",
    "f2": "creation_ts",
    "o2": "greaterthaneq",
    "v2": "2023-01-01",
}

logger.info("Downloading bugs matching the criteria...")
bugs_ids = bugzilla.get_ids(params)
bugzilla.download_bugs(bugs_ids)

bugs = []

with open('data/bugs.json', 'r') as f:
    for line in f:
        try:
            bug = json.loads(line)
            bugs.append(bug)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON: {e}")

invalid_bugs = []
other_bugs = []

for bug in bugs:
    if bug.get('resolution') == 'INVALID':
        invalid_bugs.append(bug)
    else:
        other_bugs.append(bug)

logger.info(f"Total bugs: {len(bugs)}")
logger.info(f"Invalid bugs: {len(invalid_bugs)}")
logger.info(f"Other bugs: {len(other_bugs)}")

invalid_bug_ids = [bug['id'] for bug in invalid_bugs]
other_bug_ids = [bug['id'] for bug in other_bugs]

print("Invalid Bugs IDs:")
print(invalid_bug_ids)

print("\nOther Bugs IDs:")
print(other_bug_ids)
