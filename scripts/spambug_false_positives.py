from bugbug import db, bugzilla

def is_false_positive(transaction, bug):
    if transaction['who'] != 'release-mgmt-account-bot@mozilla.tld' or bug['resolution'] == 'INVALID':
        return False
    
    for change in transaction['changes']:
        if change['field_name'] == 'resolution' and change['added'] == 'INVALID':
            return True
    
    return False

def search_false_positives():
    counter = 0
    for bug in bugzilla.get_bugs():
        for transaction in bug['history']:
            if is_false_positive(transaction, bug):
                print(f"Bug ID: {bug['id']}")
                counter += 1
                break 

    return counter

if __name__ == "__main__":
    db.register(
        bugzilla.BUGS_DB,
        "https://community-tc.services.mozilla.com/api/index/v1/task/project.bugbug.data_bugs.latest/artifacts/public/bugs.json.zst",
        10
    )
    db.download(bugzilla.BUGS_DB)
    counter = search_false_positives()
    print(f"Number of bugs marked as false positives: {counter}")
